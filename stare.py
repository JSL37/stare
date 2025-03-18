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
import aiohttp
import sys

# API 配置
OKX_BASE_URL = "https://www.okx.com"
OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
BINANCE_BASE_URL = "https://fapi.binance.com"
BINANCE_WS_URL = "wss://fstream.binance.com/stream"

# 默认代理设置，将在UI中可修改
DEFAULT_PROXY = {
    'http': 'http://127.0.0.1:7897',
    'https': 'http://127.0.0.1:7897'
}

class PriceMonitor(tk.Toplevel):
    def __init__(self, selected_pairs, exchange="okx", use_proxy=False, proxy_settings=None):
        super().__init__()
        self.selected_pairs = selected_pairs
        self.exchange = exchange.lower()
        self.ws = None
        self.loop = None
        self.running = True
        self.use_proxy = use_proxy
        self.proxy_settings = proxy_settings
        
        # 设置窗口属性
        self.setup_window()
        # 创建UI组件
        self.create_ui()
        # 启动WebSocket连接
        threading.Thread(target=self.run_async_loop, daemon=True).start()
        
        # 绑定鼠标事件
        self.bind('<Enter>', self.on_enter)
        self.bind('<Leave>', self.on_leave)
        self.title_frame.bind('<Button-1>', self.start_move)
        self.title_frame.bind('<B1-Motion>', self.on_move)
        
        # 初始状态设置为半透明
        self.on_leave(None)
    
    def setup_window(self):
        """设置窗口属性"""
        self.attributes('-alpha', 1.0, '-topmost', True, '-transparentcolor', 'white')
        self.configure(bg='white')
        self.title("价格监控")
        self.geometry("300x400")
        self.overrideredirect(True)
    
    def create_ui(self):
        """创建UI组件"""
        # 创建主框架
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # 创建标题栏框架
        self.title_frame = ttk.Frame(self.main_frame)
        self.title_frame.pack(fill='x', pady=(0, 5))
        
        # 添加交易所标签
        self.exchange_label = ttk.Label(
            self.title_frame,
            text=f"交易所: {self.exchange.upper()}",
            style="Transparent.TLabel"
        )
        self.exchange_label.pack(side='left', padx=5)
        
        # 创建关闭按钮（初始隐藏）
        self.close_button = ttk.Button(
            self.title_frame, 
            text="×", 
            width=3,
            command=self.quit_app
        )
        
        # 创建价格显示区域
        self.price_frame = ttk.Frame(self.main_frame)
        self.price_frame.pack(fill='both', expand=True)
        
        # 样式设置
        self.setup_styles()
        
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
        for pair in self.selected_pairs:
            label = ttk.Label(
                self.price_frame, 
                text=f"{pair}: 加载中...",
                style="Transparent.TLabel"
            )
            label.pack(pady=2)
            self.price_labels[pair] = label
    
    def setup_styles(self):
        """设置UI样式"""
        self.style = ttk.Style()
        self.style.configure("Transparent.TFrame", background='white')
        self.style.configure("Transparent.TLabel", 
                           background='white',
                           font=('Arial', 10),
                           foreground='#333333')
        
        self.main_frame.configure(style="Transparent.TFrame")
        self.price_frame.configure(style="Transparent.TFrame")
        self.title_frame.configure(style="Transparent.TFrame")

    def run_async_loop(self):
        """在新线程中运行事件循环"""
        try:
            # 在Windows上使用SelectorEventLoop
            if sys.platform.startswith('win'):
                loop = asyncio.SelectorEventLoop()
                asyncio.set_event_loop(loop)
            else:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            self.loop = loop
            
            if self.exchange == "okx":
                self.loop.run_until_complete(self.okx_websocket_connect())
            elif self.exchange == "binance":
                self.loop.run_until_complete(self.binance_websocket_connect())
        except Exception as e:
            logging.error(f"WebSocket事件循环错误: {e}")
        finally:
            # 确保循环正确关闭
            if self.loop and self.loop.is_running():
                self.loop.stop()
            if self.loop and not self.loop.is_closed():
                self.loop.close()

    async def okx_websocket_connect(self):
        """建立并维护OKX WebSocket连接"""
        while self.running:  # 添加外层循环以支持重连
            try:
                async with websockets.connect(OKX_WS_URL) as ws:
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
                                self.handle_okx_ticker_update(data['data'][0])
                            
                            # 检查是否需要发送心跳
                            if time.time() - last_msg_time > 20:
                                await ws.send(json.dumps({"op": "ping"}))
                                
                        except asyncio.TimeoutError:
                            # 超时后尝试发送心跳
                            try:
                                await ws.send(json.dumps({"op": "ping"}))
                            except:
                                # 如果发送心跳失败，跳出内层循环进行重连
                                break
                        except Exception as e:
                            logging.error(f"处理 WebSocket 消息时出错: {e}")
                            await asyncio.sleep(1)
                            
                            # 如果太长时间没有收到消息，跳出内层循环进行重连
                            if time.time() - last_msg_time > 30:
                                break
                            
            except Exception as e:
                logging.error(f"WebSocket 连接错误: {e}")
                if self.running:
                    # 连接失败后等待一段时间再重试
                    await asyncio.sleep(5)

    async def binance_websocket_connect(self):
        """建立并维护Binance WebSocket连接"""
        while self.running:
            try:
                # 构建订阅数据
                subscribe_message = {
                    "method": "SUBSCRIBE",
                    "params": [
                        f"{pair.lower()}@ticker" for pair in self.selected_pairs
                    ],
                    "id": 1
                }
                
                # 修改连接器配置，禁用DNS缓存
                connector = aiohttp.TCPConnector(ssl=False, use_dns_cache=False)
                
                # 根据代理设置决定是否使用代理
                proxy = self.proxy_settings.get('http', None) if self.use_proxy else None
                
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.ws_connect(
                        BINANCE_WS_URL,
                        proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=30),
                        heartbeat=20
                    ) as ws:
                        self.ws = ws
                        # 发送订阅消息
                        await ws.send_json(subscribe_message)
                        
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                # 添加流量统计
                                self.update_traffic_stats(len(msg.data))
                                data = json.loads(msg.data)
                                # 修正数据处理逻辑
                                if 'e' in data and data['e'] == '24hrTicker':
                                    self.handle_binance_ticker_update(data)
                                elif 'data' in data:
                                    self.handle_binance_ticker_update(data['data'])
                            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                                break

            except Exception as e:
                logging.error(f"Binance WebSocket 连接错误: {e}")
                if self.running:
                    await asyncio.sleep(5)

    def handle_okx_ticker_update(self, ticker_data):
        """处理OKX WebSocket ticker更新"""
        try:
            pair = ticker_data['instId']
            last_price = float(ticker_data['last'])
            open_price = float(ticker_data['open24h'])
            high_24h = float(ticker_data['high24h'])
            low_24h = float(ticker_data['low24h'])
            
            # 格式化价格和计算涨跌幅
            formatted_price = self.format_price(last_price)
            display_text, color = self.calculate_change(pair, last_price, open_price, high_24h, low_24h, formatted_price)
            
            self.after(0, self.update_label_safe, pair, display_text, color)
            
        except Exception as e:
            logging.error(f"处理OKX ticker更新时出错: {e}")

    def handle_binance_ticker_update(self, ticker_data):
        """处理 Binance WebSocket ticker 更新"""
        try:
            # 获取原始交易对名称
            symbol = ticker_data.get('s', '')
            
            # 在选中的交易对中查找匹配项
            for original_pair in self.selected_pairs:
                # 将原始交易对转换为 Binance 格式进行比较
                cleaned_pair = original_pair.replace('-', '').replace('SWAP', '').upper()
                if cleaned_pair == symbol:
                    last_price = float(ticker_data.get('c', ticker_data.get('lastPrice', 0)))  # 最新价格
                    open_price = float(ticker_data.get('o', ticker_data.get('openPrice', 0)))  # 24小时开盘价
                    high_24h = float(ticker_data.get('h', ticker_data.get('highPrice', 0)))    # 24小时最高价
                    low_24h = float(ticker_data.get('l', ticker_data.get('lowPrice', 0)))     # 24小时最低价
                    
                    # 格式化价格和计算涨跌幅
                    formatted_price = self.format_price(last_price)
                    display_text, color = self.calculate_change(original_pair, last_price, open_price, high_24h, low_24h, formatted_price)
                    
                    self.after(0, self.update_label_safe, original_pair, display_text, color)
                    break
                
        except Exception as e:
            logging.error(f"处理 Binance ticker 更新时出错: {e}")
    
    def format_price(self, price):
        """格式化价格显示"""
        if price >= 1000:
            return f"{price:,.2f}"
        elif price >= 1:
            return f"{price:.4f}"
        elif price >= 0.0001:
            return f"{price:.6f}"
        else:
            return f"{price:.8f}"
    
    def calculate_change(self, pair, last_price, open_price, high_24h, low_24h, formatted_price):
        """计算价格变化并返回显示文本和颜色"""
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
        
        return display_text, color

    def quit_app(self):
        """完全退出应用"""
        self.running = False
        if self.ws and self.loop and self.loop.is_running():
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
            logging.error(f"更新标签出错: {e}")

class CryptoDataViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("加密货币交易产品信息")
        self.root.geometry("1200x600")
        
        # 添加交易所选择
        self.exchange = tk.StringVar(value="okx")  # 默认为OKX
        
        # 代理设置
        self.use_proxy = tk.BooleanVar(value=False)  # 默认不使用代理
        self.proxy_host = tk.StringVar(value="127.0.0.1")
        self.proxy_port = tk.StringVar(value="7897")
        
        # 创建UI组件
        self.create_top_frame()
        self.create_table()
        self.load_data()

    def create_top_frame(self):
        # 创建顶部框架
        top_frame = ttk.Frame(self.root)
        top_frame.pack(fill='x', padx=10, pady=5)
        
        # 交易所选择框架
        exchange_frame = ttk.Frame(top_frame)
        exchange_frame.pack(side='left', padx=5)
        
        ttk.Label(exchange_frame, text="选择交易所:").pack(side='left', padx=5)
        ttk.Radiobutton(exchange_frame, text="OKX", variable=self.exchange, value="okx").pack(side='left')
        ttk.Radiobutton(exchange_frame, text="Binance", variable=self.exchange, value="binance").pack(side='left')
        ttk.Button(exchange_frame, text="刷新", command=self.refresh_data).pack(side='left', padx=10)
        
        # 搜索框架
        search_frame = ttk.Frame(top_frame)
        search_frame.pack(side='left', padx=20)
        
        ttk.Label(search_frame, text="搜索基础货币:").pack(side='left', padx=5)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side='left', padx=5)
        ttk.Button(search_frame, text="搜索", command=self.search_currency).pack(side='left', padx=5)
        
        # 代理设置框架
        proxy_frame = ttk.Frame(top_frame)
        proxy_frame.pack(side='left', padx=20)
        
        ttk.Checkbutton(proxy_frame, text="使用代理", variable=self.use_proxy).pack(side='left')
        ttk.Label(proxy_frame, text="主机:").pack(side='left', padx=2)
        ttk.Entry(proxy_frame, textvariable=self.proxy_host, width=12).pack(side='left', padx=2)
        ttk.Label(proxy_frame, text="端口:").pack(side='left', padx=2)
        ttk.Entry(proxy_frame, textvariable=self.proxy_port, width=6).pack(side='left', padx=2)
        
        # 盯盘提交按钮
        submit_frame = ttk.Frame(top_frame)
        submit_frame.pack(side='right', padx=10)
        ttk.Button(submit_frame, text="盯盘提交", command=self.start_monitoring).pack(side='right')

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

        # 定义列 - 兼容两个交易所
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

    def refresh_data(self):
        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)
        # 重新加载数据
        self.load_data()

    def load_data(self):
        """根据选择的交易所获取数据"""
        if self.exchange.get() == "okx":
            self.load_okx_data()
        else:
            self.load_binance_data()

    def load_okx_data(self):
        """获取OKX永续合约数据"""
        try:
            url = urljoin(OKX_BASE_URL, "/api/v5/public/instruments")
            params = {
                "instType": "SWAP"  # 获取永续合约
            }
            
            # 根据代理设置决定是否使用代理
            proxy = self.get_proxy_settings() if self.use_proxy.get() else None
            
            response = requests.get(url, params=params, proxies=proxy)
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
                messagebox.showerror("错误", "获取OKX数据失败，请检查网络连接")
        except Exception as e:
            messagebox.showerror("错误", f"加载OKX数据时出错：{str(e)}\n请检查网络连接后重试")

    def load_binance_data(self):
        """获取Binance永续合约数据"""
        try:
            # 获取Binance的合约信息
            url = urljoin(BINANCE_BASE_URL, "/fapi/v1/exchangeInfo")
            
            # 根据代理设置决定是否使用代理
            proxy = self.get_proxy_settings() if self.use_proxy.get() else None
            
            response = requests.get(url, proxies=proxy)
            result = response.json()
            
            if result and 'symbols' in result:
                for item in result['symbols']:
                    if item.get('quoteAsset', '') == 'USDT' and item.get('status', '') == 'TRADING':
                        # 获取杠杆信息
                        lever_info = "N/A"
                        try:
                            # 尝试获取杠杆信息
                            for lev in item.get('leverageBracket', []):
                                if 'bracket' in lev and lev['bracket'] == 0:
                                    lever_info = str(lev.get('initialLeverage', 'N/A'))
                                    break
                        except:
                            pass
                        
                        values = ('',
                                item.get('symbol', ''),  # 合约名称
                                item.get('baseAsset', ''),  # 基础货币
                                item.get('quoteAsset', ''),  # 计价货币
                                item.get('status', ''),  # 合约状态
                                item.get('contractSize', 'N/A'),  # 面值
                                lever_info,  # 最大杠杆
                                item.get('quoteAsset', 'N/A'))  # 面值计价币种
                        self.tree.insert('', 'end', values=values)
            else:
                messagebox.showerror("错误", "获取Binance数据失败，请检查网络连接")
        except Exception as e:
            messagebox.showerror("错误", f"加载Binance数据时出错：{str(e)}\n请检查网络连接后重试")

    def get_proxy_settings(self):
        """根据UI中的设置构建代理字典"""
        host = self.proxy_host.get()
        port = self.proxy_port.get()
        if host and port:
            proxy_url = f"http://{host}:{port}"
            return {
                'http': proxy_url,
                'https': proxy_url
            }
        return None

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
            # 获取代理设置
            use_proxy = self.use_proxy.get()
            proxy_settings = self.get_proxy_settings() if use_proxy else None
            
            # 创建价格监控窗口，传入交易所信息和代理设置
            monitor = PriceMonitor(
                selected_pairs, 
                self.exchange.get(),
                use_proxy,
                proxy_settings
            )
            # 关闭主窗口
            self.root.withdraw()
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

def main():
    root = tk.Tk()
    app = CryptoDataViewer(root)
    root.mainloop()

if __name__ == "__main__":
    main()