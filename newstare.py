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
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.dates as mdates
from datetime import datetime
from collections import deque

# API configuration
BASE_URL = "https://www.okx.com"
WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

class PriceMonitor(tk.Toplevel):
    def __init__(self, selected_pairs, update_freq=1.0):
        super().__init__()
        self.selected_pairs = selected_pairs
        self.ws = None
        self.update_freq = update_freq
        self.loop = None
        
        # Price history storage with limited size to avoid memory issues
        self.price_history = {}
        self.timestamp_history = {}
        self.max_history_points = 100
        
        for pair in selected_pairs:
            self.price_history[pair] = deque(maxlen=self.max_history_points)
            self.timestamp_history[pair] = deque(maxlen=self.max_history_points)
        
        # Set up window
        self.title("Price Monitor")
        self.geometry("500x400")
        
        # Create main frame
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Create header frame with controls
        self.header_frame = ttk.Frame(self.main_frame)
        self.header_frame.pack(fill='x', pady=5)
        
        # Create close button
        self.close_button = ttk.Button(
            self.header_frame, 
            text="Close", 
            command=self.quit_app
        )
        self.close_button.pack(side='right', padx=5)
        
        # Transparency slider
        ttk.Label(self.header_frame, text="Transparency:").pack(side='left', padx=5)
        self.transparency_var = tk.DoubleVar(value=0.9)
        self.transparency_slider = ttk.Scale(
            self.header_frame,
            from_=0.3,
            to=1.0,
            orient='horizontal',
            variable=self.transparency_var,
            length=100,
            command=self.update_transparency
        )
        self.transparency_slider.pack(side='left', padx=5)
        
        # Create price display area
        self.price_frame = ttk.Frame(self.main_frame)
        self.price_frame.pack(fill='x', pady=5)
        
        # Create chart area
        self.chart_frame = ttk.Frame(self.main_frame)
        self.chart_frame.pack(fill='both', expand=True, pady=5)
        
        # Store price labels
        self.price_labels = {}
        
        # Create labels for each trading pair
        for pair in selected_pairs:
            label = ttk.Label(
                self.price_frame, 
                text=f"{pair}: Loading..."
            )
            label.pack(pady=2)
            self.price_labels[pair] = label
        
        # Initialize chart
        self.setup_chart()
        
        # Start WebSocket connection
        self.running = True
        threading.Thread(target=self.run_async_loop, daemon=True).start()
        
        # Enable window dragging
        self.header_frame.bind('<Button-1>', self.start_move)
        self.header_frame.bind('<B1-Motion>', self.on_move)
        
        # Set up chart update timer
        self.update_chart_periodically()
        
        # Set initial transparency
        self.update_transparency(0.9)

    def setup_chart(self):
        """Set up a simple time-series chart"""
        # Create figure and canvas
        self.fig = Figure(figsize=(5, 3), dpi=100)
        self.ax = self.fig.add_subplot(111)
        
        # Set title and labels
        self.ax.set_title("Price Chart", fontsize=10)
        self.ax.set_ylabel("Price", fontsize=9)
        self.ax.grid(True, linestyle='--', alpha=0.6)
        
        # Format x-axis as time
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        
        # Create canvas and add to frame
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        
        # Dictionary to store line objects for each pair
        self.lines = {}
        
        # Create empty lines for each pair
        colors = ['blue', 'red', 'green', 'purple', 'orange', 'brown', 'pink', 'gray', 'olive', 'cyan']
        for i, pair in enumerate(self.selected_pairs):
            color = colors[i % len(colors)]
            line, = self.ax.plot([], [], '-', linewidth=1.5, label=pair, color=color)
            self.lines[pair] = line
        
        # Add legend if more than one pair
        if len(self.selected_pairs) > 1:
            self.ax.legend(loc='upper left', fontsize=8)

    def update_chart_periodically(self):
        """Periodically update the chart"""
        if self.running:
            self.update_chart()
            # Set timer based on update frequency
            update_ms = max(1000, int(self.update_freq * 1000))
            self.after(update_ms, self.update_chart_periodically)

    def update_chart(self):
        """Update the chart with latest price data"""
        try:
            # Clear previous data
            self.ax.clear()
            
            # Set grid and labels
            self.ax.grid(True, linestyle='--', alpha=0.6)
            self.ax.set_title("Price Chart", fontsize=10)
            self.ax.set_ylabel("Price", fontsize=9)
            
            # Format x-axis
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            
            # Track min and max prices for y-axis scaling
            min_price = float('inf')
            max_price = float('-inf')
            
            # Plot data for each pair
            colors = ['blue', 'red', 'green', 'purple', 'orange', 'brown', 'pink', 'gray', 'olive', 'cyan']
            for i, pair in enumerate(self.selected_pairs):
                if len(self.price_history[pair]) > 1:
                    times = list(self.timestamp_history[pair])
                    prices = list(self.price_history[pair])
                    
                    color = colors[i % len(colors)]
                    self.ax.plot(times, prices, '-', linewidth=1.5, label=pair, color=color)
                    
                    # Update min and max prices
                    pair_min = min(prices) if prices else float('inf')
                    pair_max = max(prices) if prices else float('-inf')
                    
                    if pair_min < min_price:
                        min_price = pair_min
                    if pair_max > max_price:
                        max_price = pair_max
            
            # Add some padding to y-axis
            if min_price != float('inf') and max_price != float('-inf'):
                padding = (max_price - min_price) * 0.05 if max_price > min_price else max_price * 0.01
                self.ax.set_ylim(min_price - padding, max_price + padding)
            
            # Add legend if more than one pair
            if len(self.selected_pairs) > 1:
                self.ax.legend(loc='upper left', fontsize=8)
            
            # Adjust x-axis labels
            for label in self.ax.get_xticklabels():
                label.set_rotation(45)
                label.set_fontsize(8)
            
            # Adjust layout and redraw
            self.fig.tight_layout()
            self.canvas.draw()
            
        except Exception as e:
            logging.error(f"Error updating chart: {e}")

    def update_transparency(self, value):
        """Update window transparency"""
        try:
            alpha = float(value)
            self.attributes('-alpha', alpha)
        except:
            pass

    def run_async_loop(self):
        """Run event loop in a new thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.websocket_connect())

    async def websocket_connect(self):
        """Establish and maintain WebSocket connection"""
        while self.running:  # Outer loop for reconnection support
            try:
                async with websockets.connect(WS_URL) as ws:
                    self.ws = ws
                    # Subscribe to tickers for all selected pairs
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
                    
                    # Heartbeat tracking
                    last_msg_time = time.time()
                    
                    # Continuously receive messages
                    while self.running:
                        try:
                            # Set receive timeout
                            message = await asyncio.wait_for(ws.recv(), timeout=5)
                            last_msg_time = time.time()
                            
                            data = json.loads(message)
                            if 'data' in data:
                                self.handle_ticker_update(data['data'][0])
                            
                            # Check if heartbeat needed
                            if time.time() - last_msg_time > 20:
                                ping_msg = {"op": "ping"}
                                await ws.send(json.dumps(ping_msg))
                                
                        except asyncio.TimeoutError:
                            # Try sending heartbeat on timeout
                            try:
                                ping_msg = {"op": "ping"}
                                await ws.send(json.dumps(ping_msg))
                            except:
                                # Break inner loop for reconnection if heartbeat fails
                                break
                        except Exception as e:
                            logging.error(f"Error handling WebSocket message: {e}")
                            await asyncio.sleep(1)
                            
                            # Break for reconnection if no message for too long
                            if time.time() - last_msg_time > 30:
                                break
                            
            except Exception as e:
                logging.error(f"WebSocket connection error: {e}")
                if self.running:
                    # Wait before retry
                    await asyncio.sleep(5)
                    continue

    def handle_ticker_update(self, ticker_data):
        """Handle WebSocket ticker update"""
        try:
            pair = ticker_data['instId']
            last_price = float(ticker_data['last'])
            open_price = float(ticker_data['open24h'])
            
            # Add price to history
            self.price_history[pair].append(last_price)
            self.timestamp_history[pair].append(datetime.now())
            
            # Format price display
            if last_price >= 1000:
                formatted_price = f"{last_price:,.2f}"
            elif last_price >= 1:
                formatted_price = f"{last_price:.4f}"
            elif last_price >= 0.0001:
                formatted_price = f"{last_price:.6f}"
            else:
                formatted_price = f"{last_price:.8f}"
            
            # Calculate price change
            if open_price > 0:
                change_pct = ((last_price - open_price) / open_price) * 100
                if change_pct > 0:
                    color = 'green'
                    change_text = f"+{change_pct:.2f}%"
                else:
                    color = 'red'
                    change_text = f"{change_pct:.2f}%"
                
                display_text = f"{pair}: {formatted_price} ({change_text})"
            else:
                display_text = f"{pair}: {formatted_price}"
                color = 'black'
            
            # Update label safely on main thread
            self.after(0, self.update_label_safe, pair, display_text, color)
            
        except Exception as e:
            print(f"Error handling ticker update: {e}")

    def quit_app(self):
        """Exit application"""
        self.running = False
        if self.ws:
            if self.loop and self.loop.is_running():
                self.loop.create_task(self.ws.close())
        if self.loop:
            self.loop.stop()
        self.destroy()
        self.master.deiconify()  # Show main window
    
    def start_move(self, event):
        """Start window movement"""
        self.x = event.x
        self.y = event.y
    
    def on_move(self, event):
        """Move window"""
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry(f"+{x}+{y}")

    def update_label_safe(self, pair, text, color='black'):
        """Safely update label text"""
        try:
            if pair in self.price_labels and self.price_labels[pair].winfo_exists():
                self.price_labels[pair].config(
                    text=text,
                    font=('Arial', 10, 'bold'),
                    foreground=color
                )
        except Exception as e:
            print(f"Error updating label: {e}")


class CryptoDataViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("OKX Trading Products")
        self.root.geometry("1000x500")

        # Create search frame and buttons
        self.create_search_frame()
        # Create table
        self.create_table()
        # Load data
        self.load_data()

    def create_search_frame(self):
        # Create top frame
        search_frame = ttk.Frame(self.root)
        search_frame.pack(fill='x', padx=10, pady=5)

        # Search label and input
        ttk.Label(search_frame, text="Search Base Currency:").pack(side='left', padx=5)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side='left', padx=5)
        
        # Search button
        ttk.Button(search_frame, text="Search", command=self.search_currency).pack(side='left', padx=5)
        
        # Update frequency setting
        ttk.Label(search_frame, text="Update Frequency (sec):").pack(side='left', padx=5)
        self.update_freq = ttk.Entry(search_frame, width=5)
        self.update_freq.insert(0, "1")  # Default 1 second
        self.update_freq.pack(side='left', padx=5)
        
        # History points setting
        ttk.Label(search_frame, text="History Points:").pack(side='left', padx=5)
        self.history_points = ttk.Entry(search_frame, width=5)
        self.history_points.insert(0, "100")  # Default 100 points
        self.history_points.pack(side='left', padx=5)
        
        # Monitor button
        ttk.Button(search_frame, text="Start Monitoring", command=self.start_monitoring).pack(side='right', padx=5)

    def create_table(self):
        # Create frame for table and scrollbars
        frame = ttk.Frame(self.root)
        frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Create scrollbars
        scrolly = ttk.Scrollbar(frame)
        scrolly.pack(side='right', fill='y')
        
        scrollx = ttk.Scrollbar(frame, orient='horizontal')
        scrollx.pack(side='bottom', fill='x')

        # Create table
        self.tree = ttk.Treeview(frame, 
                                yscrollcommand=scrolly.set,
                                xscrollcommand=scrollx.set,
                                selectmode='none')
        
        # Set scrollbars
        scrolly.config(command=self.tree.yview)
        scrollx.config(command=self.tree.xview)

        # Define columns
        self.tree['columns'] = ('selected', 'instId', 'baseCcy', 'quoteCcy', 'state')
        
        # Format columns
        self.tree.column('#0', width=0, stretch=False)
        self.tree.column('selected', width=70, anchor='center')
        self.tree.column('instId', width=150, anchor='w')
        self.tree.column('baseCcy', width=100, anchor='w')
        self.tree.column('quoteCcy', width=100, anchor='w')
        self.tree.column('state', width=100, anchor='w')

        # Set column headings
        self.tree.heading('selected', text='Select')
        self.tree.heading('instId', text='Instrument ID')
        self.tree.heading('baseCcy', text='Base Currency')
        self.tree.heading('quoteCcy', text='Quote Currency')
        self.tree.heading('state', text='State')

        self.tree.pack(fill='both', expand=True)
        
        # Bind click event
        self.tree.bind('<Button-1>', self.toggle_selection)

    def search_currency(self):
        search_text = self.search_var.get().upper()
        for item in self.tree.get_children():
            values = self.tree.item(item)['values']
            if search_text in str(values[2]).upper():  # baseCcy is the third column
                self.tree.see(item)  # Scroll to match
                self.tree.selection_set(item)  # Select match
            else:
                self.tree.selection_remove(item)

    def start_monitoring(self):
        # Get selected pairs
        selected_pairs = []
        for item in self.tree.get_children():
            values = self.tree.item(item)['values']
            if values[0] == '✓':  # If first column has checkmark
                selected_pairs.append(values[1])  # Add instrument ID
        
        if selected_pairs:
            try:
                update_freq = float(self.update_freq.get())
                if update_freq < 0.1:  # Set minimum update interval
                    update_freq = 0.1
                
                # Create price monitor window with update frequency
                monitor = PriceMonitor(selected_pairs, update_freq)
                
                # Apply history points if set
                try:
                    history_points = int(self.history_points.get())
                    if history_points > 0:
                        for pair in selected_pairs:
                            monitor.price_history[pair] = deque(maxlen=history_points)
                            monitor.timestamp_history[pair] = deque(maxlen=history_points)
                except:
                    pass
                
                # Hide main window
                self.root.withdraw()
            except ValueError:
                tk.messagebox.showwarning("Warning", "Please enter a valid update frequency")
        else:
            tk.messagebox.showwarning("Warning", "Please select at least one trading pair")

    def toggle_selection(self, event):
        # Get clicked area
        region = self.tree.identify_region(event.x, event.y)
        if region == 'cell':
            column = self.tree.identify_column(event.x)
            if column == '#1':  # First column (selection)
                item = self.tree.identify_row(event.y)
                current_value = self.tree.item(item)['values'][0]
                new_values = list(self.tree.item(item)['values'])
                new_values[0] = '✓' if current_value == '' else ''
                self.tree.item(item, values=new_values)

    def load_data(self):
        """Get perpetual contract data"""
        try:
            url = urljoin(BASE_URL, "/api/v5/public/instruments")
            params = {
                "instType": "SWAP"
            }
            response = requests.get(url, params=params)
            result = response.json()
            
            if result and 'data' in result:
                for item in result['data']:
                    if item.get('settleCcy', '').upper() == 'USDT':
                        values = ('',
                                item.get('instId', ''),
                                item.get('uly', '').split('-')[0],  # Extract base currency from uly
                                item.get('settleCcy', ''),
                                item.get('state', ''))
                        self.tree.insert('', 'end', values=values)
            else:
                messagebox.showerror("Error", "Failed to get data, please check network connection")
        except Exception as e:
            messagebox.showerror("Error", f"Error loading data: {str(e)}\nPlease check your network connection and try again")

def main():
    root = tk.Tk()
    app = CryptoDataViewer(root)
    root.mainloop()

if __name__ == "__main__":
    main()