import os
import platform
import time
import threading
import tkinter as tk
try:
    from tkinterdnd2 import TkinterDnD
except ImportError:
    TkinterDnD = None
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from pc_connect import APP_NAME, __version__
from pc_connect import config
from pc_connect.core.models import TransferDirection, TransferRequest, TransferType
from pc_connect.core.state import AppState
from pc_connect.network.connection import ConnectionService, close_socket
from pc_connect.security.identity import IdentityManager
from pc_connect.network.discovery import DiscoveryService
from pc_connect.network.protocol import control, parse_control, send_packet
from pc_connect.services.chat import ChatService
from pc_connect.services.history import HistoryService
from pc_connect.services.transfer import TransferService
from pc_connect.ui import theme
from pc_connect.utils.files import ensure_data_directories, format_size, safe_name
from pc_connect.utils.network import get_local_ip


class PCConnectApp:
    def __init__(self):
        self.root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
        self.root.title(f"{APP_NAME} {__version__}")
        self.root.geometry("1180x760")
        self.root.minsize(980, 650)
        self.root.configure(bg=theme.BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.state = AppState()
        self.local_ip = get_local_ip()
        self.identity = IdentityManager(config.DATA_DIR)
        ensure_data_directories(config.DATA_DIR, config.RECEIVED_FILES_DIR, config.RECEIVED_FOLDERS_DIR)
        self.history = HistoryService(config.HISTORY_FILE, config.MAX_HISTORY_ENTRIES)
        self.last_requests = {}
        self.transfer_cards = {}
        self.listed_ips = []
        self._ask_device_name()
        self._build_ui()
        self.chat = ChatService(self.state, self.set_status, self.add_message, self.state.device_name_for)
        self.transfers = TransferService(self.state, self.history, config, self.on_transfer_progress, self.on_transfer_finished, self.on_transfer_error, self.handle_side_packet)
        self.discovery = DiscoveryService(self.state, self.local_ip, self.identity, self.set_status)
        self.connections = ConnectionService(self.state, self.handle_packet, self.on_connected, self.on_disconnected, self.connection_error, self.identity, self.confirm_trust)
        self._enable_optional_drag_drop()

    def _ask_device_name(self):
        default = platform.node() or "My PC"
        while not self.state.device_name.strip():
            value = simpledialog.askstring("Welcome to PC Connect", "Choose the name other devices will see:", initialvalue=default, parent=self.root)
            self.state.device_name = (value or default).strip() or default

    def _build_ui(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("PC.Horizontal.TProgressbar", troughcolor=theme.INPUT, background=theme.ACCENT, bordercolor=theme.INPUT, lightcolor=theme.ACCENT, darkcolor=theme.ACCENT)

        self.sidebar = tk.Frame(self.root, bg=theme.PANEL, width=310)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.content = tk.Frame(self.root, bg=theme.BG)
        self.content.pack(side="right", fill="both", expand=True)

        brand = tk.Frame(self.sidebar, bg=theme.PANEL)
        brand.pack(fill="x", padx=22, pady=(22, 18))
        tk.Label(brand, text="PC Connect", bg=theme.PANEL, fg=theme.TEXT, font=("Arial", 21, "bold")).pack(anchor="w")
        tk.Label(brand, text="Nearby. Private. Direct.", bg=theme.PANEL, fg=theme.MUTED, font=("Arial", 9)).pack(anchor="w", pady=(2, 0))

        me = tk.Frame(self.sidebar, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
        me.pack(fill="x", padx=16, pady=(0, 16))
        tk.Label(me, text="THIS PC", bg=theme.CARD, fg=theme.MUTED, font=("Arial", 8, "bold")).pack(anchor="w", padx=14, pady=(11, 1))
        tk.Label(me, text=self.state.device_name, bg=theme.CARD, fg=theme.TEXT, font=("Arial", 11, "bold")).pack(anchor="w", padx=14)
        tk.Label(me, text=self.local_ip, bg=theme.CARD, fg=theme.MUTED, font=("Arial", 8)).pack(anchor="w", padx=14, pady=(1, 2))
        tk.Label(me, text=f"Secure ID  {self.identity.short_fingerprint()}", bg=theme.CARD, fg=theme.MUTED, font=("Arial", 7)).pack(anchor="w", padx=14, pady=(0, 11))

        header = tk.Frame(self.sidebar, bg=theme.PANEL)
        header.pack(fill="x", padx=18, pady=(0, 7))
        tk.Label(header, text="NEARBY DEVICES", bg=theme.PANEL, fg=theme.TEXT, font=("Arial", 9, "bold")).pack(side="left")
        self.device_count = tk.Label(header, text="0", bg=theme.PANEL, fg=theme.MUTED, font=("Arial", 9))
        self.device_count.pack(side="right")

        self.device_list = tk.Listbox(self.sidebar, bg=theme.CARD, fg=theme.TEXT, selectbackground="#29415a", selectforeground=theme.TEXT, border=0, highlightbackground=theme.BORDER, highlightthickness=1, font=("Arial", 10), activestyle="none", relief="flat", exportselection=False)
        self.device_list.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.device_list.bind("<Double-Button-1>", self.connect_selected)
        self.device_list.bind("<<ListboxSelect>>", self.on_list_select)
        self.device_list.bind("<Button-3>", self.device_menu)

        self.make_button(self.sidebar, "Send files", self.choose_files, accent=True)
        self.make_button(self.sidebar, "Send folder", self.choose_folder)
        self.make_button(self.sidebar, "Transfer history", self.show_history)
        self.make_button(self.sidebar, "Settings", self.show_settings)
        tk.Label(self.sidebar, text="Drag files anywhere into PC Connect", bg=theme.PANEL, fg=theme.MUTED, font=("Arial", 8)).pack(pady=(8, 14))

        top = tk.Frame(self.content, bg=theme.BG)
        top.pack(fill="x", padx=24, pady=(20, 10))
        self.device_title = tk.Label(top, text="Select a nearby device", bg=theme.BG, fg=theme.TEXT, font=("Arial", 18, "bold"))
        self.device_title.pack(side="left")
        self.connection_label = tk.Label(top, text="Ready", bg=theme.BG, fg=theme.MUTED, font=("Arial", 9))
        self.connection_label.pack(side="right", pady=6)

        self.notebook = ttk.Notebook(self.content)
        self.notebook.pack(fill="both", expand=True, padx=24, pady=(0, 10))
        self.chat_tab = tk.Frame(self.notebook, bg=theme.BG)
        self.transfer_tab = tk.Frame(self.notebook, bg=theme.BG)
        self.notebook.add(self.chat_tab, text="  Chat  ")
        self.notebook.add(self.transfer_tab, text="  Transfers  ")
        self._build_chat_tab()
        self._build_transfer_tab()

        status = tk.Frame(self.content, bg=theme.BG)
        status.pack(fill="x", padx=24, pady=(0, 14))
        self.status_label = tk.Label(status, text="Discovering nearby devices…", bg=theme.BG, fg=theme.MUTED, font=("Arial", 9))
        self.status_label.pack(side="left")
        self.drop_hint = tk.Label(status, text="Local network only", bg=theme.BG, fg=theme.MUTED, font=("Arial", 9))
        self.drop_hint.pack(side="right")

    def _build_chat_tab(self):
        self.chat_box = tk.Text(self.chat_tab, bg="#10161d", fg=theme.TEXT, insertbackground=theme.TEXT, border=0, highlightbackground=theme.BORDER, highlightthickness=1, state="disabled", font=("Arial", 11), padx=18, pady=16, wrap="word")
        self.chat_box.pack(fill="both", expand=True, padx=8, pady=(8, 10))
        composer = tk.Frame(self.chat_tab, bg=theme.BG)
        composer.pack(fill="x", padx=8, pady=(0, 8))
        self.message_entry = tk.Entry(composer, bg=theme.INPUT, fg=theme.TEXT, insertbackground=theme.TEXT, border=0, highlightbackground=theme.BORDER, highlightthickness=1, font=("Arial", 11), relief="flat")
        self.message_entry.pack(side="left", fill="x", expand=True, ipady=12, padx=(0, 8))
        self.send_button = self.make_inline_button(composer, "Send", self.send_message, accent=True)
        self.message_entry.bind("<Return>", lambda event: self.send_message())

        drop = tk.Frame(self.chat_tab, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
        drop.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(drop, text="Drop files here to send", bg=theme.CARD, fg=theme.TEXT, font=("Arial", 10, "bold")).pack(pady=(10, 2))
        tk.Label(drop, text="Or use Send files / Send folder", bg=theme.CARD, fg=theme.MUTED, font=("Arial", 8)).pack(pady=(0, 10))
        self.drop_target = drop

    def _build_transfer_tab(self):
        self.transfer_canvas = tk.Canvas(self.transfer_tab, bg=theme.BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.transfer_tab, orient="vertical", command=self.transfer_canvas.yview)
        self.transfer_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.transfer_canvas.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        self.transfer_inner = tk.Frame(self.transfer_canvas, bg=theme.BG)
        self.transfer_window = self.transfer_canvas.create_window((0, 0), window=self.transfer_inner, anchor="nw")
        self.transfer_inner.bind("<Configure>", lambda event: self.transfer_canvas.configure(scrollregion=self.transfer_canvas.bbox("all")))
        self.transfer_canvas.bind("<Configure>", lambda event: self.transfer_canvas.itemconfigure(self.transfer_window, width=event.width))
        tk.Label(self.transfer_inner, text="Transfers appear here", bg=theme.BG, fg=theme.MUTED, font=("Arial", 10)).pack(pady=35)

    def make_button(self, parent, text, command, accent=False):
        bg = theme.ACCENT if accent else theme.INPUT
        hover = theme.ACCENT_HOVER if accent else theme.CARD_2
        fg = "white"
        button = tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=hover, activeforeground=fg, border=0, relief="flat", cursor="hand2", font=("Arial", 10, "bold"), anchor="w", padx=14, pady=9)
        button.bind("<Enter>", lambda event: button.config(bg=hover))
        button.bind("<Leave>", lambda event: button.config(bg=bg))
        button.pack(padx=16, pady=3, fill="x")
        return button

    def make_inline_button(self, parent, text, command, accent=False):
        bg = theme.ACCENT if accent else theme.INPUT
        return tk.Button(parent, text=text, command=command, bg=bg, fg="white", activebackground=theme.ACCENT_HOVER, activeforeground="white", border=0, relief="flat", cursor="hand2", font=("Arial", 10, "bold"), padx=20, pady=10)

    def _enable_optional_drag_drop(self):
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
        except ImportError:
            return
        if TkinterDnD is None:
            return
        self.drop_target.drop_target_register(DND_FILES)
        self.drop_target.dnd_bind("<<Drop>>", self.on_drop)

    def on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        self.send_paths(list(paths))

    def confirm_trust(self, ip, name, device_id, fingerprint):
        result = {"value": False}
        event = threading.Event()
        def ask():
            text = (f"PC Connect found a new secure device.\n\n"
                    f"Name: {name}\nIP: {ip}\n\n"
                    f"Security fingerprint:\n{fingerprint[:16]}\n\n"
                    "Only approve this device if the fingerprint matches what you expect.")
            result["value"] = messagebox.askyesno("Trust this device?", text, parent=self.root)
            event.set()
        self.root.after(0, ask)
        event.wait(timeout=60)
        return result["value"]

    def run(self):
        self.discovery.start()
        self.connections.start()
        self.refresh_loop()
        self.root.mainloop()

    def ui(self, callback):
        if self.state.running:
            self.root.after(0, callback)

    def set_status(self, text):
        self.ui(lambda: self.status_label.config(text=text))

    def add_message(self, sender, message):
        def update():
            self.chat_box.config(state="normal")
            self.chat_box.insert(tk.END, f"{sender}: {message}\n")
            self.chat_box.config(state="disabled")
            self.chat_box.see(tk.END)
        self.ui(update)

    def get_selected_ip(self):
        selection = self.device_list.curselection()
        if not selection or selection[0] >= len(self.listed_ips):
            return None
        return self.listed_ips[selection[0]]

    def selected_connection(self):
        ip = self.state.selected_device
        if not ip:
            messagebox.showwarning("Choose a device", "Select a nearby device first.")
            return None, None
        connection = self.state.get_connection(ip)
        if not connection:
            self.connect_device(ip)
            connection = self.state.get_connection(ip)
        if not connection:
            return None, None
        return ip, connection

    def refresh_loop(self):
        if not self.state.running:
            return
        self.update_device_list()
        self.root.after(1200, self.refresh_loop)

    def update_device_list(self):
        selected = self.state.selected_device
        now = time.time()
        with self.state.lock:
            stale = [ip for ip, device in self.state.devices.items() if now - device.last_seen > config.STALE_SECONDS and ip not in self.state.connections]
            for ip in stale:
                self.state.devices.pop(ip, None)
            entries = [(ip, d.name, ip in self.state.connections) for ip, d in self.state.devices.items()]
            for ip in self.state.connections:
                if not any(item[0] == ip for item in entries):
                    entries.append((ip, ip, True))
        entries.sort(key=lambda item: item[1].lower())
        self.device_list.delete(0, tk.END)
        self.listed_ips = []
        for ip, name, connected in entries:
            marker = "●" if connected else "○"
            self.device_list.insert(tk.END, f"{marker}  {name}\n    {ip}")
            self.listed_ips.append(ip)
        self.device_count.config(text=str(len(entries)))
        if selected in self.listed_ips:
            index = self.listed_ips.index(selected)
            self.device_list.selection_clear(0, tk.END)
            self.device_list.selection_set(index)
            self.device_list.activate(index)
        self.update_header()

    def on_list_select(self, event=None):
        ip = self.get_selected_ip()
        if ip:
            self.state.selected_device = ip
            self.update_header()

    def update_header(self):
        ip = self.state.selected_device
        if not ip:
            self.device_title.config(text="Select a nearby device")
            self.connection_label.config(text="Ready", fg=theme.MUTED)
            return
        name = self.state.device_name_for(ip)
        self.device_title.config(text=name)
        if self.state.get_connection(ip):
            self.connection_label.config(text="Connected", fg=theme.SUCCESS)
        else:
            self.connection_label.config(text="Available", fg=theme.MUTED)

    def connect_selected(self, event=None):
        self.connect_device(self.get_selected_ip())

    def connect_device(self, ip=None):
        if not ip:
            return
        if self.state.get_connection(ip):
            self.state.selected_device = ip
            self.update_header()
            return
        try:
            self.connections.connect(ip)
            self.state.selected_device = ip
        except Exception as error:
            messagebox.showerror("Connection failed", str(error))

    def device_menu(self, event):
        index = self.device_list.nearest(event.y)
        if index < 0 or index >= len(self.listed_ips):
            return
        self.device_list.selection_clear(0, tk.END)
        self.device_list.selection_set(index)
        ip = self.listed_ips[index]
        menu = tk.Menu(self.root, tearoff=0, bg=theme.CARD, fg=theme.TEXT)
        menu.add_command(label="Connect", command=lambda: self.connect_device(ip))
        menu.add_command(label="Remove", command=lambda: self.remove_device(ip))
        menu.tk_popup(event.x_root, event.y_root)

    def remove_device(self, ip):
        with self.state.lock:
            connection = self.state.connections.pop(ip, None)
            self.state.devices.pop(ip, None)
        if connection:
            close_socket(connection)
        if self.state.selected_device == ip:
            self.state.selected_device = None
        self.update_header()
        self.set_status("Device removed")

    def on_connected(self, ip):
        def update():
            self.state.selected_device = ip
            self.update_header()
            self.set_status(f"Connected to {self.state.device_name_for(ip)}")
        self.ui(update)

    def on_disconnected(self, ip):
        self.ui(lambda: (self.update_header(), self.set_status(f"Disconnected from {self.state.device_name_for(ip)}")))

    def connection_error(self, message):
        self.set_status(message)

    def send_message(self):
        ip, connection = self.selected_connection()
        if not connection:
            return
        message = self.message_entry.get().strip()
        if not message:
            return
        if len(message) > config.MAX_CHAT_LENGTH:
            messagebox.showwarning("Message too long", "Please keep messages under 10,000 characters.")
            return
        try:
            self.chat.send(ip, message)
            self.message_entry.delete(0, tk.END)
        except Exception as error:
            messagebox.showerror("Send failed", str(error))

    def choose_files(self):
        paths = filedialog.askopenfilenames(title="Select files to send")
        self.send_paths(list(paths))

    def choose_folder(self):
        path = filedialog.askdirectory(title="Select folder to send")
        if path:
            self.send_paths([path])

    def send_paths(self, paths):
        ip, connection = self.selected_connection()
        if not connection:
            return
        for path in paths:
            path = os.path.abspath(path)
            if os.path.isfile(path):
                self.start_send(ip, connection, path, TransferType.FILE)
            elif os.path.isdir(path):
                self.start_send(ip, connection, path, TransferType.FOLDER)

    def start_send(self, ip, connection, path, transfer_type):
        source = Path(path)
        name = source.name
        request_id = f"request-{time.time_ns()}"
        self.last_requests[request_id] = TransferRequest(name, str(source), transfer_type)
        send_packet(connection, control("send_request", id=request_id, kind=transfer_type.value, name=name, size=source.stat().st_size if source.is_file() else 0))
        self.set_status(f"Waiting for {self.state.device_name_for(ip)} to accept {name}")

    def request_acceptance(self, connection, ip, action):
        request_id = action.get("id")
        request = self.last_requests.pop(request_id, None)
        if request is None:
            return
        if action.get("action") == "send_accept":
            threading.Thread(target=self.transfers.send_path, args=(connection, ip, request.path, request.transfer_type), daemon=True).start()
        else:
            self.set_status(f"Transfer declined: {request.name}")

    def ask_incoming(self, connection, ip, action):
        name = safe_name(action.get("name", "file"))
        kind = action.get("kind", "file")
        size = int(action.get("size", 0) or 0)
        type_label = "folder" if kind == "folder" else "file"
        answer = messagebox.askyesno("Incoming transfer", f"{self.state.device_name_for(ip)} wants to send:\n\n{name}\n{format_size(size)}\n\nAccept this {type_label}?", parent=self.root)
        response = "send_accept" if answer else "send_reject"
        send_packet(connection, control(response, id=action.get("id")))
        if answer:
            self.set_status(f"Receiving {name}")

    def handle_side_packet(self, connection, ip, packet):
        if packet.startswith(b"CHAT|"):
            self.chat.handle_chat_packet(ip, packet)
        else:
            action = parse_control(packet)
            if action and action.get("action") == "send_request":
                self.ui(lambda: self.ask_incoming(connection, ip, action))

    def handle_packet(self, connection, ip, packet):
        if packet.startswith(b"CHAT|"):
            self.chat.handle_chat_packet(ip, packet)
            return
        action = parse_control(packet)
        if not action:
            self.handle_side_packet(connection, ip, packet)
            return
        name = action.get("action")
        if name == "send_request":
            self.ui(lambda: self.ask_incoming(connection, ip, action))
            return
        if name in {"send_accept", "send_reject"}:
            self.ui(lambda: self.request_acceptance(connection, ip, action))
            return
        if name == "transfer_start":
            transfer_id = action.get("id")
            transfer_type = TransferType(action.get("kind", "file"))
            transfer = self.transfers
            transfer.receive_payload(connection, ip, transfer_id, action.get("name", "file"), int(action.get("size", 0)), transfer_type)
            return
        if name in {"pause", "resume", "cancel", "transfer_end"}:
            transfer_id = action.get("id")
            controls = self.state.transfer_controls.get(transfer_id)
            if controls:
                if name == "pause":
                    controls["pause"].set()
                elif name == "resume":
                    controls["pause"].clear()
                elif name == "cancel":
                    controls["cancel"].set()
            return

    def on_transfer_progress(self, progress):
        self.ui(lambda: self.render_transfer(progress))

    def render_transfer(self, progress):
        card = self.transfer_cards.get(progress.transfer_id)
        if card is None:
            card = tk.Frame(self.transfer_inner, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
            card.pack(fill="x", padx=8, pady=6)
            top = tk.Frame(card, bg=theme.CARD)
            top.pack(fill="x", padx=14, pady=(12, 4))
            title = tk.Label(top, text=progress.name, bg=theme.CARD, fg=theme.TEXT, font=("Arial", 10, "bold"))
            title.pack(side="left")
            state = tk.Label(top, text="", bg=theme.CARD, fg=theme.MUTED, font=("Arial", 8))
            state.pack(side="right")
            bar = ttk.Progressbar(card, style="PC.Horizontal.TProgressbar", maximum=100)
            bar.pack(fill="x", padx=14, pady=(0, 6))
            bottom = tk.Frame(card, bg=theme.CARD)
            bottom.pack(fill="x", padx=14, pady=(0, 10))
            info = tk.Label(bottom, text="", bg=theme.CARD, fg=theme.MUTED, font=("Arial", 8))
            info.pack(side="left")
            pause = tk.Button(bottom, text="Pause", bg=theme.INPUT, fg=theme.TEXT, border=0, command=lambda tid=progress.transfer_id: self.toggle_pause(tid))
            pause.pack(side="right", padx=(5, 0))
            cancel = tk.Button(bottom, text="Cancel", bg="#3a2024", fg=theme.DANGER, border=0, command=lambda tid=progress.transfer_id: self.cancel_transfer(tid))
            cancel.pack(side="right")
            self.transfer_cards[progress.transfer_id] = {"frame": card, "state": state, "bar": bar, "info": info, "pause": pause, "cancel": cancel}
            if len(self.transfer_cards) == 1:
                for child in self.transfer_inner.winfo_children():
                    if isinstance(child, tk.Label) and child.cget("text") == "Transfers appear here":
                        child.destroy()
        card = self.transfer_cards[progress.transfer_id]
        direction = "Sending" if progress.direction is TransferDirection.SEND else "Receiving"
        card["state"].config(text=progress.status.capitalize())
        card["bar"]["value"] = progress.percent
        card["info"].config(text=f"{direction} • {format_size(progress.completed)} / {format_size(progress.total)} • {progress.percent}%")
        card["pause"].config(text="Resume" if progress.status == "paused" else "Pause")
        if progress.status in {"completed", "cancelled", "failed"}:
            card["pause"].config(state="disabled")
            card["cancel"].config(state="disabled")

    def on_transfer_finished(self, progress):
        self.ui(lambda: self.set_status(f"{progress.status.capitalize()}: {progress.name}"))

    def on_transfer_error(self, progress, error):
        self.ui(lambda: self.set_status(f"Transfer failed: {progress.name}: {error}"))

    def toggle_pause(self, transfer_id):
        progress = self.state.active_transfers.get(transfer_id)
        if not progress:
            return
        connection = self.state.get_connection(progress.ip)
        if connection:
            self.transfers.pause(transfer_id, connection)

    def cancel_transfer(self, transfer_id=None):
        if transfer_id is None:
            active = list(self.state.active_transfers.values())
            if not active:
                return
            transfer_id = active[-1].transfer_id
        progress = self.state.active_transfers.get(transfer_id)
        if not progress:
            return
        connection = self.state.get_connection(progress.ip)
        if connection:
            self.transfers.cancel(transfer_id, connection)

    def show_history(self):
        window = tk.Toplevel(self.root)
        window.title("Transfer history")
        window.geometry("850x500")
        window.configure(bg=theme.BG)
        text = tk.Text(window, bg=theme.CARD, fg=theme.TEXT, border=0, font=("Arial", 10), padx=14, pady=14)
        text.pack(fill="both", expand=True, padx=14, pady=14)
        history = self.history.load()
        if not history:
            text.insert(tk.END, "No transfers yet.\n")
        else:
            for item in reversed(history):
                text.insert(tk.END, f'{item.get("time", "?")}  •  {item.get("direction", "?")}  •  {item.get("type", "?")}  •  {item.get("name", "?")}  •  {format_size(item.get("size", 0))}\n')
        text.config(state="disabled")

    def show_settings(self):
        window = tk.Toplevel(self.root)
        window.title("PC Connect settings")
        window.geometry("460x300")
        window.configure(bg=theme.BG)
        tk.Label(window, text="Device name", bg=theme.BG, fg=theme.TEXT, font=("Arial", 11, "bold")).pack(anchor="w", padx=24, pady=(24, 6))
        entry = tk.Entry(window, bg=theme.INPUT, fg=theme.TEXT, insertbackground=theme.TEXT, border=0, font=("Arial", 11))
        entry.insert(0, self.state.device_name)
        entry.pack(fill="x", padx=24, ipady=10)
        tk.Label(window, text="Received files", bg=theme.BG, fg=theme.MUTED, font=("Arial", 9)).pack(anchor="w", padx=24, pady=(20, 3))
        tk.Label(window, text=str(config.RECEIVED_FILES_DIR), bg=theme.BG, fg=theme.TEXT, font=("Arial", 8), wraplength=410, justify="left").pack(anchor="w", padx=24)
        def save():
            value = entry.get().strip()
            if value:
                self.state.device_name = value
                self.set_status("Device name updated")
                window.destroy()
        tk.Button(window, text="Save", command=save, bg=theme.ACCENT, fg="white", border=0, padx=20, pady=9).pack(anchor="e", padx=24, pady=25)

    def close(self):
        self.state.running = False
        self.connections.close_all()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


LanChatApp = PCConnectApp
