import requests
import websockets
import asyncio
import json
from urllib.parse import urljoin
import tkinter as tk
from tkinter import ttk, messagebox
import time
import threading
import logging
# 添加 API 配置
BASE_URL = "https://www.okx.com"
WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

class PriceMonitor(tk.Toplevel):
    def __init__(self, selected_pairs, update_freq=1.0):
        super().__init__()
        self.selected_pairs = selected_pairs
        self.ws = None
        self.ws_task = None
        self.update_freq = update_freq  # 存储更新频率
        self.loop = None
        
        # 设置窗口完全透明和置顶
        self.attributes('-alpha', 1.0, '-topmost', True, '-transparentcolor', 'white')
        self.configure(bg='white')
        self.title("价格监控")
        self.geometry("300x400")
        self.overrideredirect(True)
        
        # 创建主框架
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # 创建标题栏框架
        self.title_frame = ttk.Frame(self.main_frame)
        self.title_frame.pack(fill='x', pady=(0, 5))
        
        # 创建关闭按钮（初始隐藏）
        self.close_button = ttk.Button(
            self.title_frame, 
            text="×", 
            width=3,
            command=self.quit_app
        )
        # 不要立即pack关闭按钮，等待鼠标移入时再显示
        
        # 创建价格显示区域
        self.price_frame = ttk.Frame(self.main_frame)
        self.price_frame.pack(fill='both', expand=True)
        
        # 样式设置
        self.style = ttk.Style()
        self.style.configure("Transparent.TFrame", background='white')
        self.style.configure("Transparent.TLabel", 
                           background='white',
                           font=('Arial', 10),
                           foreground='#333333')
        
        self.main_frame.configure(style="Transparent.TFrame")
        self.price_frame.configure(style="Transparent.TFrame")
        self.title_frame.configure(style="Transparent.TFrame")
        
        # 存储标签的字典和流量统计
        self.price_labels = {}
        self.traffic_bytes = 0
        
        # 创建流量统计标签
        self.traffic_label = ttk.Label(
            self.price_frame, 
            text="流量统计: 0 KB",
            style="Transparent.TLabel"
        )
        self.traffic_label.pack(pady=2)
        
        # 为每个选中的交易对创建标签
        for pair in selected_pairs:
            label = ttk.Label(
                self.price_frame, 
                text=f"{pair}: 加载中...",
                style="Transparent.TLabel"
            )
            label.pack(pady=2)
            self.price_labels[pair] = label
        
        # 启动 WebSocket 连接
        self.running = True
        # 在新线程中运行事件循环
        threading.Thread(target=self.run_async_loop, daemon=True).start()
        
        # 绑定鼠标事件
        self.bind('<Enter>', self.on_enter)
        self.bind('<Leave>', self.on_leave)
        self.title_frame.bind('<Button-1>', self.start_move)
        self.title_frame.bind('<B1-Motion>', self.on_move)
        
        # 初始状态设置为半透明
        self.on_leave(None)

    def run_async_loop(self):
        """在新线程中运行事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.websocket_connect())

    async def websocket_connect(self):
        """建立并维护 WebSocket 连接"""
        while self.running:  # 添加外层循环以支持重连
            try:
                async with websockets.connect(WS_URL) as ws:
                    self.ws = ws
                    # 订阅所有选中交易对的 tickers
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": [
                            {
                                "channel": "tickers",
                                "instId": pair
                            } for pair in self.selected_pairs
                        ]
                    }
                    await ws.send(json.dumps(subscribe_msg))
                    
                    # 添加心跳检测
                    last_msg_time = time.time()
                    
                    # 持续接收消息
                    while self.running:
                        try:
                            # 设置接收超时
                            message = await asyncio.wait_for(ws.recv(), timeout=5)
                            last_msg_time = time.time()
                            
                            # 更新流量统计（添加接收到的消息大小）
                            self.update_traffic_stats(len(message))
                            data = json.loads(message)
                            if 'data' in data:
                                self.handle_ticker_update(data['data'][0])
                            
                            # 检查是否需要发送心跳
                            if time.time() - last_msg_time > 20:
                                ping_msg = {"op": "ping"}
                                await ws.send(json.dumps(ping_msg))
                                
                        except asyncio.TimeoutError:
                            # 超时后尝试发送心跳
                            try:
                                ping_msg = {"op": "ping"}
                                await ws.send(json.dumps(ping_msg))
                            except:
                                # 如果发送心跳失败，跳出内层循环进行重连
                                break
                        except Exception as e:
                            logging.error(f"处理 WebSocket 消息时出错: {e}")
                            # 短暂等待后继续尝试
                            await asyncio.sleep(1)
                            
                            # 如果太长时间没有收到消息，跳出内层循环进行重连
                            if time.time() - last_msg_time > 30:
                                break
                            
            except Exception as e:
                logging.error(f"WebSocket 连接错误: {e}")
                if self.running:
                    # 连接失败后等待一段时间再重试
                    await asyncio.sleep(5)
                    # 继续外层循环，进行重连
                    continue

    def handle_ticker_update(self, ticker_data):
        """处理 WebSocket ticker 更新"""
        try:
            pair = ticker_data['instId']
            last_price = float(ticker_data['last'])
            open_price = float(ticker_data['open24h'])
            high_24h = float(ticker_data['high24h'])
            low_24h = float(ticker_data['low24h'])
            
            # 格式化价格显示逻辑保持不变
            if last_price >= 1000:
                formatted_price = f"{last_price:,.2f}"
            elif last_price >= 1:
                formatted_price = f"{last_price:.4f}"
            elif last_price >= 0.0001:
                formatted_price = f"{last_price:.6f}"
            else:
                formatted_price = f"{last_price:.8f}"
            
            # 计算涨跌幅逻辑保持不变
            if open_price > 0:
                change_pct = ((last_price - open_price) / open_price) * 100
                if change_pct > 0:
                    color = 'green'
                    change_text = f"+{change_pct:.2f}%"
                else:
                    color = 'red'
                    change_text = f"{change_pct:.2f}%"
                
                display_text = (
                    f"{pair}: {formatted_price} ({change_text})\n"
                    f"24h高: {high_24h:.4f} 低: {low_24h:.4f}"
                )
            else:
                display_text = f"{pair}: {formatted_price}"
                color = 'black'
            
            self.after(0, self.update_label_safe, pair, display_text, color)
            
        except Exception as e:
            print(f"处理ticker更新时出错: {e}")

    def quit_app(self):
        """完全退出应用"""
        self.running = False
        if self.ws:
            if self.loop and self.loop.is_running():
                self.loop.create_task(self.ws.close())
        if self.loop:
            self.loop.stop()
        self.destroy()  # 只关闭监控窗口
        self.master.deiconify()  # 显示主窗口

    def on_enter(self, event):
        """鼠标进入窗口"""
        # 检查鼠标是否在窗口范围内
        x, y = self.winfo_pointerxy()
        widget = self.winfo_containing(x, y)
        if widget is not None and widget.winfo_toplevel() == self:
            self.configure(bg='#f0f0f0')
            self.attributes('-transparentcolor', '')
            self.attributes('-alpha', 0.9)
            # 显示关闭按钮
            if not self.close_button.winfo_ismapped():
                self.close_button.pack(side='right')
    
    def on_leave(self, event):
        """鼠标离开窗口"""
        x, y = self.winfo_pointerxy()
        widget = self.winfo_containing(x, y)
        if widget is None or widget.winfo_toplevel() != self:
            self.configure(bg='white')
            self.attributes('-transparentcolor', 'white')
            self.attributes('-alpha', 0.7)
            # 隐藏关闭按钮
            if self.close_button.winfo_ismapped():
                self.close_button.pack_forget()
    
    def start_move(self, event):
        """开始移动窗口"""
        self.x = event.x
        self.y = event.y
    
    def on_move(self, event):
        """移动窗口"""
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry(f"+{x}+{y}")
    
    def update_traffic_stats(self, bytes_count):
        """更新流量统计"""
        self.traffic_bytes += bytes_count
        kb_traffic = self.traffic_bytes / 1024
        if kb_traffic > 1024:
            mb_traffic = kb_traffic / 1024
            self.traffic_label.config(text=f"流量统计: {mb_traffic:.2f} MB")
        else:
            self.traffic_label.config(text=f"流量统计: {kb_traffic:.2f} KB")

    def update_label_safe(self, pair, text, color='black'):
        """安全地更新标签文本"""
        try:
            if pair in self.price_labels and self.price_labels[pair].winfo_exists():
                self.price_labels[pair].config(
                    text=text,
                    font=('Arial', 10, 'bold'),
                    foreground=color
                )
        except Exception as e:
            print(f"更新标签出错: {e}")

class CryptoDataViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("欧易交易产品信息")
        self.root.geometry("1200x600")

        # 创建搜索框和按钮框架
        self.create_search_frame()
        # 创建表格
        self.create_table()
        # 加载数据
        self.load_data()

    def create_search_frame(self):
        # 创建顶部框架
        search_frame = ttk.Frame(self.root)
        search_frame.pack(fill='x', padx=10, pady=5)

        # 搜索标签和输入框
        ttk.Label(search_frame, text="搜索基础货币:").pack(side='left', padx=5)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side='left', padx=5)
        
        # 搜索按钮
        ttk.Button(search_frame, text="搜索", command=self.search_currency).pack(side='left', padx=5)
        
        # 更新频率设置
        ttk.Label(search_frame, text="更新频率(秒):").pack(side='left', padx=5)
        self.update_freq = ttk.Entry(search_frame, width=5)
        self.update_freq.insert(0, "1")  # 默认1秒
        self.update_freq.pack(side='left', padx=5)
        
        # 盯盘提交按钮
        ttk.Button(search_frame, text="盯盘提交", command=self.start_monitoring).pack(side='right', padx=5)

    def create_table(self):
        # 创建一个框架来容纳表格和滚动条
        frame = ttk.Frame(self.root)
        frame.pack(fill='both', expand=True, padx=10, pady=5)

        # 创建滚动条
        scrolly = ttk.Scrollbar(frame)
        scrolly.pack(side='right', fill='y')
        
        scrollx = ttk.Scrollbar(frame, orient='horizontal')
        scrollx.pack(side='bottom', fill='x')

        # 创建表格
        self.tree = ttk.Treeview(frame, 
                                yscrollcommand=scrolly.set,
                                xscrollcommand=scrollx.set,
                                selectmode='none')
        
        # 设置滚动条
        scrolly.config(command=self.tree.yview)
        scrollx.config(command=self.tree.xview)

        # 修改定义列
        self.tree['columns'] = ('selected', 'instId', 'baseCcy', 'quoteCcy', 'state', 'ctVal', 'lever', 'ctValCcy')
        
        # 格式化列
        self.tree.column('#0', width=0, stretch=False)
        self.tree.column('selected', width=70, anchor='center')
        self.tree.column('instId', width=120, anchor='w')
        self.tree.column('baseCcy', width=100, anchor='w')
        self.tree.column('quoteCcy', width=100, anchor='w')
        self.tree.column('state', width=100, anchor='w')
        self.tree.column('ctVal', width=100, anchor='w')
        self.tree.column('lever', width=100, anchor='w')
        self.tree.column('ctValCcy', width=100, anchor='w')

        # 设置列标题
        self.tree.heading('selected', text='选择')
        self.tree.heading('instId', text='合约名称')
        self.tree.heading('baseCcy', text='基础货币')
        self.tree.heading('quoteCcy', text='计价货币')
        self.tree.heading('state', text='合约状态')
        self.tree.heading('ctVal', text='面值')
        self.tree.heading('lever', text='最大杠杆')
        self.tree.heading('ctValCcy', text='面值计价币种')

        self.tree.pack(fill='both', expand=True)
        
        # 绑定点击事件
        self.tree.bind('<Button-1>', self.toggle_selection)

    def search_currency(self):
        search_text = self.search_var.get().upper()
        for item in self.tree.get_children():
            values = self.tree.item(item)['values']
            if search_text in str(values[2]).upper():  # baseCcy是第三列
                self.tree.see(item)  # 滚动到匹配项
                self.tree.selection_set(item)  # 选中匹配项
            else:
                self.tree.selection_remove(item)

    def start_monitoring(self):
        # 获取选中的交易对
        selected_pairs = []
        for item in self.tree.get_children():
            values = self.tree.item(item)['values']
            if values[0] == '✓':  # 如果第一列有勾选标记
                selected_pairs.append(values[1])  # 添加交易对ID
        
        if selected_pairs:
            try:
                update_freq = float(self.update_freq.get())
                if update_freq < 0.1:  # 设置最小更新间隔
                    update_freq = 0.1
                # 创建价格监控窗口，传入更新频率
                monitor = PriceMonitor(selected_pairs, update_freq)
                # 关闭主窗口
                self.root.withdraw()
            except ValueError:
                tk.messagebox.showwarning("警告", "请输入有效的更新频率")
        else:
            tk.messagebox.showwarning("警告", "请至少选择一个交易对")

    def toggle_selection(self, event):
        # 获取点击的区域
        region = self.tree.identify_region(event.x, event.y)
        if region == 'cell':
            column = self.tree.identify_column(event.x)
            if column == '#1':  # 第一列（选择列）
                item = self.tree.identify_row(event.y)
                current_value = self.tree.item(item)['values'][0]
                new_values = list(self.tree.item(item)['values'])
                new_values[0] = '✓' if current_value == '' else ''
                self.tree.item(item, values=new_values)

    def load_data(self):
        """获取永续合约数据"""
        try:
            url = urljoin(BASE_URL, "/api/v5/public/instruments")
            params = {
                "instType": "SWAP"  # 改为SWAP获取永续合约
            }
            response = requests.get(url, params=params)
            result = response.json()
            
            if result and 'data' in result:
                for item in result['data']:
                    if item.get('settleCcy', '').upper() == 'USDT':  # 使用settleCcy替代quoteCcy
                        values = ('',
                                item.get('instId', ''),
                                item.get('uly', '').split('-')[0],  # 从uly中提取基础货币
                                item.get('settleCcy', ''),
                                item.get('state', ''),
                                item.get('ctVal', ''),
                                item.get('lever', ''),
                                item.get('ctValCcy', ''))
                        self.tree.insert('', 'end', values=values)
            else:
                messagebox.showerror("错误", "获取数据失败，请检查网络连接")
        except Exception as e:
            messagebox.showerror("错误", f"加载数据时出错：{str(e)}\n请检查网络连接后重试")

def main():
    root = tk.Tk()
    app = CryptoDataViewer(root)
    root.mainloop()

if __name__ == "__main__":
ever', ''),
                                item.get('ctValCcy', ''))
                        self.tree.insert('', 'end', values=values)
            else:
                messagebox.showerror("错误", "获取数据失败，请检查网络连接")
        except Exception as e:
            messagebox.showerror("错误", f"加载数据时出错：{str(e)}\n请检查网络连接后重试")

def main():
    root = tk.Tk()
    app = CryptoDataViewer(root)
    root.mainloop()

if __name__ == "__main__":
    main()