import hashlib
import json
import os
import platform
import queue
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from history import add_transfer, load_history
from protocol import send_packet, receive_packet

DISCOVERY_PORT = 5001
CHAT_PORT = 5002
DISCOVERY_INTERVAL = 3
DEVICE_TIMEOUT = 10
PROTOCOL_VERSION = 2
BUFFER_SIZE = 65536
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024
MAX_FOLDER_ZIP_SIZE = 10 * 1024 * 1024 * 1024
MAX_EXTRACTED_FOLDER_SIZE = 20 * 1024 * 1024 * 1024
MAX_FOLDER_FILES = 100000
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".lan_chat")
DEVICE_FILE = os.path.join(CONFIG_DIR, "device.json")
TRUST_FILE = os.path.join(CONFIG_DIR, "trusted_devices.json")
CERT_FILE = os.path.join(CONFIG_DIR, "cert.pem")
KEY_FILE = os.path.join(CONFIG_DIR, "key.pem")
RECEIVED_FILES = "received_files"
RECEIVED_FOLDERS = "received_folders"

BG = "#0d1117"
PANEL = "#161b22"
CARD = "#1c2128"
INPUT = "#21262d"
BORDER = "#30363d"
TEXT = "#f0f6fc"
MUTED = "#8b949e"
ACCENT = "#58a6ff"
DANGER = "#f85149"

os.makedirs(CONFIG_DIR, exist_ok=True)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path, value):
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as file:
        json.dump(value, file, indent=2)
    os.replace(temp, path)


def load_device_identity():
    data = load_json(DEVICE_FILE, {})
    device_id = data.get("device_id") or uuid.uuid4().hex
    name = data.get("name", "").strip()
    if not name:
        name = platform.node().strip() or "LAN Device"
    save_json(DEVICE_FILE, {"device_id": device_id, "name": name})
    return device_id, name


def fingerprint_from_cert(cert_bytes):
    return hashlib.sha256(cert_bytes).hexdigest().upper()


def ensure_certificate():
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError(
            "OpenSSL is required for encrypted LAN connections. "
            "Install OpenSSL and start LAN Chat again."
        )
    result = subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            KEY_FILE,
            "-out",
            CERT_FILE,
            "-days",
            "3650",
            "-subj",
            "/CN=LANChat",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not create TLS certificate: {result.stderr.strip()}")
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass


def make_server_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(CERT_FILE, KEY_FILE)
    return context


def make_client_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def safe_name(name, fallback="file"):
    name = os.path.basename(name.replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f]", "_", name).strip()
    if name in {"", ".", ".."}:
        return fallback
    return name


def unique_path(directory, filename):
    os.makedirs(directory, exist_ok=True)
    filename = safe_name(filename)
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = os.path.join(directory, f"{stem} ({counter}){ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def safe_archive_target(destination, member_name):
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("Unsafe folder path")
    target = os.path.abspath(os.path.join(destination, normalized))
    base = os.path.abspath(destination)
    if target != base and not target.startswith(base + os.sep):
        raise ValueError("Unsafe folder path")
    return target


def create_folder_zip(folder_path):
    folder_path = os.path.abspath(folder_path)
    folder_name = safe_name(os.path.basename(folder_path), "folder")
    fd, zip_path = tempfile.mkstemp(prefix="lan_chat_", suffix=".zip")
    os.close(fd)
    try:
        total = 0
        count = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for root_dir, dirs, files in os.walk(folder_path):
                for filename in files:
                    full_path = os.path.join(root_dir, filename)
                    if os.path.islink(full_path):
                        continue
                    size = os.path.getsize(full_path)
                    total += size
                    count += 1
                    if total > MAX_EXTRACTED_FOLDER_SIZE or count > MAX_FOLDER_FILES:
                        raise ValueError("Folder is too large")
                    relative_path = os.path.relpath(full_path, folder_path)
                    archive_name = os.path.join(folder_name, relative_path)
                    archive.write(full_path, archive_name)
        if os.path.getsize(zip_path) > MAX_FOLDER_ZIP_SIZE:
            raise ValueError("Compressed folder is too large")
        return zip_path, folder_name
    except Exception:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        raise


class Connection:
    def __init__(self, sock, device_id, name, fingerprint, incoming=False):
        self.sock = sock
        self.device_id = device_id
        self.name = name
        self.fingerprint = fingerprint
        self.incoming = incoming
        self.send_lock = threading.Lock()
        self.closed = threading.Event()
        self.transfers = {}
        self.incoming_queues = {}

    def send(self, message_type, transfer_id="", meta=None, payload=b""):
        with self.send_lock:
            if self.closed.is_set():
                raise ConnectionError("Connection is closed")
            send_packet(self.sock, message_type, transfer_id, meta, payload)

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class Transfer:
    def __init__(self, transfer_id, kind, name, path, size, direction):
        self.id = transfer_id
        self.kind = kind
        self.name = name
        self.path = path
        self.size = size
        self.direction = direction
        self.cancelled = threading.Event()
        self.queue = queue.Queue(maxsize=32)
        self.received = 0
        self.sent = 0
        self.lock = threading.Lock()


class LANChatApp:
    def __init__(self):
        self.device_id, self.device_name = load_device_identity()
        self.devices = {}
        self.connections = {}
        self.transfers = {}
        self.trusted = load_json(TRUST_FILE, {})
        self.lock = threading.RLock()
        self.root = tk.Tk()
        self.root.title("LAN Chat")
        self.root.geometry("1100x740")
        self.root.minsize(900, 620)
        self.root.configure(bg=BG)
        self.build_ui()
        self.setup_network()
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

    def setup_network(self):
        try:
            ensure_certificate()
            self.server_context = make_server_context()
            self.client_context = make_client_context()
        except Exception as error:
            messagebox.showerror("Security Setup Error", str(error), parent=self.root)
            self.root.destroy()
            raise SystemExit(1)
        threading.Thread(target=self.discovery_listener, daemon=True).start()
        threading.Thread(target=self.announce_device, daemon=True).start()
        threading.Thread(target=self.start_listener, daemon=True).start()
        self.refresh_devices()

    def build_ui(self):
        left = tk.Frame(self.root, bg=PANEL, width=310)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        right = tk.Frame(self.root, bg=BG)
        right.pack(side="right", fill="both", expand=True)

        brand = tk.Frame(left, bg=PANEL)
        brand.pack(fill="x", padx=22, pady=(24, 16))
        tk.Label(brand, text="LAN Chat", bg=PANEL, fg=TEXT, font=("Arial", 19, "bold")).pack(anchor="w")
        tk.Label(brand, text="Encrypted • Local • Direct", bg=PANEL, fg=MUTED, font=("Arial", 9)).pack(anchor="w", pady=(3, 0))

        me = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        me.pack(fill="x", padx=18, pady=(0, 14))
        tk.Label(me, text="YOUR DEVICE", bg=CARD, fg=MUTED, font=("Arial", 8, "bold")).pack(anchor="w", padx=14, pady=(11, 2))
        self.name_label = tk.Label(me, text=self.device_name, bg=CARD, fg=TEXT, font=("Arial", 11, "bold"))
        self.name_label.pack(anchor="w", padx=14, pady=(0, 5))
        tk.Label(me, text=self.device_id[:12], bg=CARD, fg=MUTED, font=("Arial", 8)).pack(anchor="w", padx=14, pady=(0, 11))

        header = tk.Frame(left, bg=PANEL)
        header.pack(fill="x", padx=20, pady=(2, 5))
        tk.Label(header, text="DEVICES", bg=PANEL, fg=TEXT, font=("Arial", 10, "bold")).pack(side="left")
        tk.Label(header, text="Double-click to connect", bg=PANEL, fg=MUTED, font=("Arial", 8)).pack(side="right")

        self.device_list = tk.Listbox(
            left, bg=CARD, fg=TEXT, selectbackground="#26364a", selectforeground=TEXT,
            border=0, highlightbackground=BORDER, highlightcolor=ACCENT, highlightthickness=1,
            font=("Arial", 10), activestyle="none", relief="flat"
        )
        self.device_list.pack(padx=18, pady=(0, 14), fill="both", expand=True)
        self.device_list.bind("<Double-Button-1>", lambda event: self.connect_selected())
        self.device_list.bind("<Button-3>", self.show_device_menu)

        tk.Label(left, text="ACTIONS", bg=PANEL, fg=MUTED, font=("Arial", 8, "bold")).pack(anchor="w", padx=20, pady=(0, 7))
        self.make_button(left, "  Send File", self.send_file_request, accent=True)
        self.make_button(left, "  Send Folder", self.send_folder_request)
        self.make_button(left, "  Cancel Selected Transfer", self.cancel_selected_transfer, danger=True)
        self.make_button(left, "  Transfer History", self.show_history)
        self.make_button(left, "  Change Device Name", self.change_device_name)
        tk.Label(left, text="LAN Chat • v3", bg=PANEL, fg="#6e7681", font=("Arial", 8)).pack(pady=(14, 18))

        header = tk.Frame(right, bg=BG)
        header.pack(fill="x", padx=24, pady=(22, 12))
        self.chat_title = tk.Label(header, text="Conversation", bg=BG, fg=TEXT, font=("Arial", 18, "bold"))
        self.chat_title.pack(side="left")
        self.chat_status = tk.Label(header, text="No device selected", bg=BG, fg=MUTED, font=("Arial", 9))
        self.chat_status.pack(side="right", pady=5)

        self.chat_box = tk.Text(right, bg="#11161d", fg=TEXT, insertbackground=TEXT, border=0,
                                highlightbackground=BORDER, highlightthickness=1, state="disabled",
                                font=("Arial", 11), padx=16, pady=14, wrap="word")
        self.chat_box.pack(padx=24, pady=(0, 12), fill="both", expand=True)

        self.progress_label = tk.Label(right, text="Ready", bg=BG, fg=MUTED, font=("Arial", 9))
        self.progress_label.pack(anchor="w", padx=27, pady=(0, 7))
        message_frame = tk.Frame(right, bg=BG)
        message_frame.pack(fill="x", padx=24, pady=(0, 22))
        self.message_entry = tk.Entry(message_frame, bg=INPUT, fg=TEXT, insertbackground=TEXT,
                                      border=0, highlightbackground=BORDER, highlightcolor=ACCENT,
                                      highlightthickness=1, font=("Arial", 11), relief="flat")
        self.message_entry.pack(side="left", fill="x", expand=True, ipady=11, padx=(0, 10))
        self.send_button = tk.Button(message_frame, text="Send  ➜", command=self.send_message,
                                     bg="#1f6feb", fg="white", activebackground="#388bfd",
                                     activeforeground="white", border=0, relief="flat", cursor="hand2",
                                     font=("Arial", 10, "bold"), padx=18, pady=10)
        self.send_button.pack(side="right")
        self.send_button.bind("<Enter>", lambda event: self.send_button.config(bg="#388bfd"))
        self.send_button.bind("<Leave>", lambda event: self.send_button.config(bg="#1f6feb"))
        self.message_entry.bind("<Return>", lambda event: self.send_message())

    def make_button(self, parent, text, command, accent=False, danger=False):
        if danger:
            bg, hover, fg = "#2d1717", "#4a1f1f", "#ff7b72"
        elif accent:
            bg, hover, fg = "#1f6feb", "#388bfd", "white"
        else:
            bg, hover, fg = INPUT, BORDER, TEXT
        button = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                           activebackground=hover, activeforeground=fg, border=0,
                           relief="flat", cursor="hand2", font=("Arial", 10, "bold"),
                           anchor="w", padx=14, pady=9)
        button.bind("<Enter>", lambda event: button.config(bg=hover))
        button.bind("<Leave>", lambda event: button.config(bg=bg))
        button.pack(padx=18, pady=3, fill="x")

    def change_device_name(self):
        name = simpledialog.askstring("Device Name", "Enter a unique device name:", initialvalue=self.device_name, parent=self.root)
        if name is None:
            return
        name = name.strip()
        if not name or len(name) > 64 or "|" in name:
            messagebox.showerror("Invalid Name", "Use 1–64 characters and do not use |.", parent=self.root)
            return
        with self.lock:
            duplicate = any(item["name"].casefold() == name.casefold() for item in self.devices.values() if item["device_id"] != self.device_id)
        if duplicate:
            messagebox.showerror("Name In Use", "Another discovered device is already using that name.", parent=self.root)
            return
        self.device_name = name
        save_json(DEVICE_FILE, {"device_id": self.device_id, "name": name})
        self.name_label.config(text=name)

    def discovery_listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", DISCOVERY_PORT))
        while not self.root.winfo_exists():
            time.sleep(0.1)
        while True:
            try:
                data, address = sock.recvfrom(8192)
                message = json.loads(data.decode("utf-8"))
                if message.get("type") != "LAN_CHAT_DISCOVERY":
                    continue
                if int(message.get("version", 0)) != PROTOCOL_VERSION:
                    continue
                device_id = str(message.get("device_id", ""))
                name = str(message.get("name", "")).strip()
                port = int(message.get("port", CHAT_PORT))
                if not device_id or device_id == self.device_id or not name:
                    continue
                with self.lock:
                    self.devices[device_id] = {
                        "device_id": device_id,
                        "name": name,
                        "ip": address[0],
                        "port": port,
                        "last_seen": time.time(),
                    }
            except Exception:
                continue

    def announce_device(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        message = json.dumps({
            "type": "LAN_CHAT_DISCOVERY",
            "version": PROTOCOL_VERSION,
            "device_id": self.device_id,
            "name": self.device_name,
            "port": CHAT_PORT,
        }).encode("utf-8")
        while True:
            try:
                sock.sendto(message, ("255.255.255.255", DISCOVERY_PORT))
            except OSError:
                pass
            time.sleep(DISCOVERY_INTERVAL)

    def refresh_devices(self):
        now = time.time()
        with self.lock:
            stale = [device_id for device_id, item in self.devices.items() if now - item["last_seen"] > DEVICE_TIMEOUT]
            for device_id in stale:
                self.devices.pop(device_id, None)
            items = list(self.devices.values())
            active = {device_id for device_id in self.connections}
        items.sort(key=lambda item: item["name"].casefold())
        self.device_list.delete(0, tk.END)
        self.display_devices = []
        for item in items:
            status = "● Connected" if item["device_id"] in active else "○ Available"
            self.display_devices.append(item["device_id"])
            self.device_list.insert(tk.END, f"{item['name']} • {item['ip']} [{status}]")
        self.root.after(2000, self.refresh_devices)

    def selected_device_id(self):
        selection = self.device_list.curselection()
        if not selection:
            return None
        index = selection[0]
        if index >= len(self.display_devices):
            return None
        return self.display_devices[index]

    def show_device_menu(self, event):
        index = self.device_list.nearest(event.y)
        if index < 0 or index >= len(self.display_devices):
            return
        self.device_list.selection_clear(0, tk.END)
        self.device_list.selection_set(index)
        device_id = self.display_devices[index]
        menu = tk.Menu(self.root, tearoff=0, bg="#222222", fg="white", activebackground="#444444", activeforeground="white")
        if device_id in self.connections:
            menu.add_command(label="Disconnect", command=lambda: self.disconnect_device(device_id))
        else:
            menu.add_command(label="Connect", command=lambda: self.connect_device(device_id))
        menu.add_command(label="Remove from list", command=lambda: self.remove_device(device_id))
        menu.tk_popup(event.x_root, event.y_root)

    def remove_device(self, device_id):
        self.disconnect_device(device_id)
        with self.lock:
            self.devices.pop(device_id, None)
            self.trusted.pop(device_id, None)
            save_json(TRUST_FILE, self.trusted)
        self.progress_label.config(text="Device removed")

    def disconnect_device(self, device_id):
        with self.lock:
            connection = self.connections.pop(device_id, None)
        if connection:
            connection.close()
        if self.selected_connection_id() == device_id:
            self.chat_status.config(text="Disconnected")

    def selected_connection_id(self):
        selection = self.device_list.curselection()
        if not selection or selection[0] >= len(self.display_devices):
            return None
        return self.display_devices[selection[0]]

    def ask_sync(self, title, message, kind="yesno"):
        event = threading.Event()
        result = {"value": False}
        def ask():
            if kind == "yesno":
                result["value"] = messagebox.askyesno(title, message, parent=self.root)
            event.set()
        self.root.after(0, ask)
        event.wait()
        return result["value"]

    def connect_device(self, device_id=None):
        if device_id is None:
            device_id = self.selected_device_id()
        if not device_id:
            messagebox.showwarning("No Device", "Select a device first.", parent=self.root)
            return
        with self.lock:
            info = self.devices.get(device_id)
            if device_id in self.connections:
                connection = self.connections[device_id]
            else:
                connection = None
        if connection:
            self.set_selected(device_id)
            return
        if not info:
            return
        threading.Thread(target=self._connect_worker, args=(info,), daemon=True).start()

    def _connect_worker(self, info):
        device_id = info["device_id"]
        try:
            raw = socket.create_connection((info["ip"], info["port"]), timeout=8)
            tls_sock = self.client_context.wrap_socket(raw, server_hostname="LANChat")
            tls_sock.settimeout(None)
            fingerprint = fingerprint_from_cert(tls_sock.getpeercert(binary_form=True))
            trusted = self.trusted.get(device_id)
            if trusted and trusted != fingerprint:
                tls_sock.close()
                raise RuntimeError("The device certificate changed. Connection refused.")
            if not trusted:
                accepted = self.ask_sync(
                    "Trust Device",
                    f"Connect to {info['name']}?\n\nCertificate fingerprint:\n{fingerprint}\n\nTrust this device?",
                )
                if not accepted:
                    tls_sock.close()
                    return
                with self.lock:
                    self.trusted[device_id] = fingerprint
                    save_json(TRUST_FILE, self.trusted)
            connection = Connection(tls_sock, device_id, info["name"], fingerprint, incoming=False)
            connection.send("HELLO", meta={"device_id": self.device_id, "name": self.device_name, "version": PROTOCOL_VERSION})
            header, _ = receive_packet(tls_sock)
            if header.get("type") != "HELLO_ACK" or not header.get("meta", {}).get("accepted"):
                connection.close()
                return
            with self.lock:
                self.connections[device_id] = connection
            self.set_selected(device_id)
            self.start_reader(connection)
        except Exception as error:
            self.root.after(0, lambda e=str(error): messagebox.showerror("Connection Error", e, parent=self.root))

    def start_listener(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", CHAT_PORT))
        server.listen(20)
        while True:
            try:
                raw, address = server.accept()
                threading.Thread(target=self.handle_incoming, args=(raw, address), daemon=True).start()
            except OSError:
                break

    def handle_incoming(self, raw, address):
        try:
            tls_sock = self.server_context.wrap_socket(raw, server_side=True)
            tls_sock.settimeout(10)
            header, _ = receive_packet(tls_sock)
            if header.get("type") != "HELLO":
                tls_sock.close()
                return
            meta = header.get("meta", {})
            device_id = str(meta.get("device_id", ""))
            name = str(meta.get("name", "")).strip()
            version = int(meta.get("version", 0))
            if not device_id or not name or version != PROTOCOL_VERSION:
                tls_sock.close()
                return
            fingerprint = fingerprint_from_cert(tls_sock.getpeercert(binary_form=True))
            with self.lock:
                known = self.trusted.get(device_id)
            if known and known != fingerprint:
                send_packet(tls_sock, "HELLO_ACK", meta={"accepted": False})
                tls_sock.close()
                return
            if not known:
                accepted = self.ask_sync(
                    "Incoming Connection",
                    f"{name} wants to connect.\n\nIP: {address[0]}\nCertificate fingerprint:\n{fingerprint}\n\nAllow?",
                )
                if not accepted:
                    send_packet(tls_sock, "HELLO_ACK", meta={"accepted": False})
                    tls_sock.close()
                    return
                with self.lock:
                    self.trusted[device_id] = fingerprint
                    save_json(TRUST_FILE, self.trusted)
            send_packet(tls_sock, "HELLO_ACK", meta={"accepted": True, "device_id": self.device_id, "name": self.device_name, "version": PROTOCOL_VERSION})
            tls_sock.settimeout(None)
            connection = Connection(tls_sock, device_id, name, fingerprint, incoming=True)
            with self.lock:
                old = self.connections.get(device_id)
                if old:
                    old.close()
                self.connections[device_id] = connection
                self.devices[device_id] = {
                    "device_id": device_id,
                    "name": name,
                    "ip": address[0],
                    "port": CHAT_PORT,
                    "last_seen": time.time(),
                }
            self.root.after(0, lambda: self.set_selected(device_id))
            self.start_reader(connection)
        except Exception:
            try:
                raw.close()
            except OSError:
                pass

    def start_reader(self, connection):
        threading.Thread(target=self.receive_messages, args=(connection,), daemon=True).start()

    def receive_messages(self, connection):
        try:
            while not connection.closed.is_set():
                header, payload = receive_packet(connection.sock)
                message_type = header.get("type")
                transfer_id = header.get("id", "")
                meta = header.get("meta", {})
                if message_type == "CHAT":
                    message = payload.decode("utf-8", errors="replace")
                    self.root.after(0, lambda m=message, c=connection: self.add_message(c.name, m))
                elif message_type == "FILE_REQUEST":
                    self.handle_file_request(connection, transfer_id, meta)
                elif message_type == "FOLDER_REQUEST":
                    self.handle_folder_request(connection, transfer_id, meta)
                elif message_type in {"FILE_ACCEPT", "FILE_REJECT", "FOLDER_ACCEPT", "FOLDER_REJECT"}:
                    self.handle_request_response(connection, message_type, transfer_id)
                elif message_type == "FILE_INFO":
                    self.handle_incoming_file(connection, transfer_id, meta)
                elif message_type == "FOLDER_INFO":
                    self.handle_incoming_folder(connection, transfer_id, meta)
                elif message_type in {"FILE_DATA", "FOLDER_DATA"}:
                    transfer = self.transfers.get(transfer_id)
                    if transfer and transfer.direction == "Received":
                        expected_type = "FILE_DATA" if transfer.kind == "File" else "FOLDER_DATA"
                        if message_type != expected_type:
                            raise ValueError("Transfer type mismatch")
                        if len(payload) > BUFFER_SIZE:
                            raise ValueError("Transfer chunk is too large")
                        transfer.queue.put(payload)
                elif message_type in {"FILE_END", "FOLDER_END"}:
                    transfer = self.transfers.get(transfer_id)
                    if transfer and transfer.direction == "Received":
                        transfer.queue.put(None)
                elif message_type == "CANCEL":
                    transfer = self.transfers.get(transfer_id)
                    if transfer:
                        transfer.cancelled.set()
                        if transfer.direction == "Received":
                            transfer.queue.put(None)
                elif message_type == "PING":
                    connection.send("PONG")
                elif message_type == "ERROR":
                    self.root.after(0, lambda m=meta.get("message", "Peer error"): self.progress_label.config(text=m))
        except Exception as error:
            if not connection.closed.is_set():
                self.root.after(0, lambda e=str(error): self.progress_label.config(text=f"Connection closed: {e}"))
        finally:
            connection.close()
            with self.lock:
                if self.connections.get(connection.device_id) is connection:
                    self.connections.pop(connection.device_id, None)
            self.root.after(0, self.refresh_devices)

    def handle_file_request(self, connection, transfer_id, meta):
        filename = safe_name(str(meta.get("name", "file")))
        size = int(meta.get("size", -1))
        if size < 0 or size > MAX_FILE_SIZE:
            connection.send("FILE_REJECT", transfer_id)
            return
        def ask():
            answer = messagebox.askyesno("File Request", f"{connection.name} wants to send:\n\n{filename}\nSize: {size:,} bytes\n\nAccept?", parent=self.root)
            if answer:
                connection.send("FILE_ACCEPT", transfer_id)
            else:
                connection.send("FILE_REJECT", transfer_id)
        self.root.after(0, ask)

    def handle_folder_request(self, connection, transfer_id, meta):
        folder_name = safe_name(str(meta.get("name", "folder")), "folder")
        def ask():
            answer = messagebox.askyesno("Folder Request", f"{connection.name} wants to send:\n\n{folder_name}\n\nAccept?", parent=self.root)
            if answer:
                connection.send("FOLDER_ACCEPT", transfer_id)
            else:
                connection.send("FOLDER_REJECT", transfer_id)
        self.root.after(0, ask)

    def handle_request_response(self, connection, message_type, transfer_id):
        transfer = self.transfers.get(transfer_id)
        if not transfer:
            return
        if message_type.endswith("REJECT"):
            transfer.cancelled.set()
            self.root.after(0, lambda: self.progress_label.config(text=f"{transfer.kind} transfer rejected"))
            return
        threading.Thread(target=self.send_transfer, args=(connection, transfer), daemon=True).start()

    def handle_incoming_file(self, connection, transfer_id, meta):
        filename = safe_name(str(meta.get("name", "file")))
        size = int(meta.get("size", -1))
        if size < 0 or size > MAX_FILE_SIZE:
            connection.send("ERROR", transfer_id, {"message": "File too large or invalid"})
            return
        transfer = Transfer(transfer_id, "File", filename, "", size, "Received")
        self.transfers[transfer_id] = transfer
        threading.Thread(target=self.receive_transfer, args=(connection, transfer), daemon=True).start()

    def handle_incoming_folder(self, connection, transfer_id, meta):
        folder_name = safe_name(str(meta.get("name", "folder")), "folder")
        size = int(meta.get("size", -1))
        if size < 0 or size > MAX_FOLDER_ZIP_SIZE:
            connection.send("ERROR", transfer_id, {"message": "Folder archive too large or invalid"})
            return
        transfer = Transfer(transfer_id, "Folder", folder_name, "", size, "Received")
        self.transfers[transfer_id] = transfer
        threading.Thread(target=self.receive_transfer, args=(connection, transfer), daemon=True).start()

    def receive_transfer(self, connection, transfer):
        fd, temp_path = tempfile.mkstemp(prefix="lan_recv_", suffix=".part")
        os.close(fd)
        try:
            with open(temp_path, "wb") as file:
                while transfer.received < transfer.size:
                    payload = transfer.queue.get()
                    if payload is None:
                        if transfer.cancelled.is_set():
                            raise RuntimeError("Transfer cancelled")
                        if transfer.received != transfer.size:
                            raise ValueError("Transfer ended before all data arrived")
                        break
                    if transfer.cancelled.is_set():
                        raise RuntimeError("Transfer cancelled")
                    remaining = transfer.size - transfer.received
                    if len(payload) > remaining:
                        raise ValueError("Transfer contains too much data")
                    file.write(payload)
                    transfer.received += len(payload)
                    self.update_progress(f"Receiving {transfer.kind.lower()}: {transfer.received * 100 // transfer.size}%")
                if transfer.received != transfer.size:
                    raise ValueError("Incomplete transfer")
            if transfer.kind == "File":
                destination = unique_path(RECEIVED_FILES, transfer.name)
                os.replace(temp_path, destination)
            else:
                self.extract_folder(temp_path, transfer.name)
                os.remove(temp_path)
            add_transfer("Received", transfer.kind, transfer.name, transfer.size, connection.name)
            self.update_progress(f"Received {transfer.kind.lower()}: {transfer.name}")
        except Exception as error:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            self.update_progress(f"{transfer.kind} failed: {error}")
        finally:
            self.transfers.pop(transfer.id, None)

    def extract_folder(self, zip_path, folder_name):
        destination = os.path.abspath(RECEIVED_FOLDERS)
        os.makedirs(destination, exist_ok=True)
        folder_target = unique_path(destination, folder_name)
        os.makedirs(folder_target, exist_ok=True)
        extracted_size = 0
        file_count = 0
        with zipfile.ZipFile(zip_path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FOLDER_FILES:
                raise ValueError("Too many files in folder")
            for member in infos:
                safe_archive_target(folder_target, member.filename)
                if member.is_dir():
                    continue
                extracted_size += member.file_size
                file_count += 1
                if extracted_size > MAX_EXTRACTED_FOLDER_SIZE:
                    raise ValueError("Extracted folder is too large")
                if file_count > MAX_FOLDER_FILES:
                    raise ValueError("Too many files")
            archive.extractall(folder_target)

    def send_file_request(self):
        connection = self.get_selected_connection()
        if not connection:
            messagebox.showwarning("No Device", "Connect to a device first.", parent=self.root)
            return
        path = filedialog.askopenfilename(parent=self.root)
        if not path:
            return
        size = os.path.getsize(path)
        if size > MAX_FILE_SIZE:
            messagebox.showerror("File Too Large", "Maximum file size is 10 GB.", parent=self.root)
            return
        transfer_id = uuid.uuid4().hex
        transfer = Transfer(transfer_id, "File", os.path.basename(path), path, size, "Sent")
        self.transfers[transfer_id] = transfer
        try:
            connection.send("FILE_REQUEST", transfer_id, {"name": safe_name(transfer.name), "size": size})
            self.update_progress(f"Requesting file: {transfer.name}")
        except Exception as error:
            self.transfers.pop(transfer_id, None)
            messagebox.showerror("Send Error", str(error), parent=self.root)

    def send_folder_request(self):
        connection = self.get_selected_connection()
        if not connection:
            messagebox.showwarning("No Device", "Connect to a device first.", parent=self.root)
            return
        path = filedialog.askdirectory(parent=self.root)
        if not path:
            return
        try:
            zip_path, folder_name = create_folder_zip(path)
            size = os.path.getsize(zip_path)
            os.remove(zip_path)
        except Exception as error:
            messagebox.showerror("Folder Error", str(error), parent=self.root)
            return
        transfer_id = uuid.uuid4().hex
        transfer = Transfer(transfer_id, "Folder", folder_name, path, size, "Sent")
        self.transfers[transfer_id] = transfer
        try:
            connection.send("FOLDER_REQUEST", transfer_id, {"name": folder_name})
            self.update_progress(f"Requesting folder: {folder_name}")
        except Exception as error:
            self.transfers.pop(transfer_id, None)
            messagebox.showerror("Send Error", str(error), parent=self.root)

    def send_transfer(self, connection, transfer):
        if transfer.cancelled.is_set():
            self.transfers.pop(transfer.id, None)
            return
        zip_path = None
        try:
            if transfer.kind == "Folder":
                zip_path, _ = create_folder_zip(transfer.path)
                path = zip_path
                size = os.path.getsize(path)
            else:
                path = transfer.path
                size = transfer.size
            connection.send(f"{transfer.kind.upper()}_INFO", transfer.id, {"name": safe_name(transfer.name), "size": size})
            transfer.size = size
            with open(path, "rb") as file:
                while True:
                    if transfer.cancelled.is_set():
                        connection.send("CANCEL", transfer.id)
                        return
                    data = file.read(BUFFER_SIZE)
                    if not data:
                        break
                    connection.send(f"{transfer.kind.upper()}_DATA", transfer.id, payload=data)
                    transfer.sent += len(data)
                    self.update_progress(f"Sending {transfer.kind.lower()}: {transfer.sent * 100 // size}%")
            if transfer.cancelled.is_set():
                connection.send("CANCEL", transfer.id)
                return
            connection.send(f"{transfer.kind.upper()}_END", transfer.id)
            add_transfer("Sent", transfer.kind, transfer.name, size, connection.name)
            self.update_progress(f"Sent {transfer.kind.lower()}: {transfer.name}")
        except Exception as error:
            self.update_progress(f"{transfer.kind} failed: {error}")
        finally:
            if zip_path:
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
            self.transfers.pop(transfer.id, None)

    def cancel_selected_transfer(self):
        connection = self.get_selected_connection()
        if not connection:
            return
        candidates = [item for item in self.transfers.values() if item.direction == "Sent"]
        if not candidates:
            self.progress_label.config(text="No outgoing transfer")
            return
        transfer = candidates[-1]
        transfer.cancelled.set()
        try:
            connection.send("CANCEL", transfer.id)
        except Exception:
            pass
        self.progress_label.config(text="Cancellation requested")

    def get_selected_connection(self):
        device_id = self.selected_device_id()
        if not device_id:
            return None
        with self.lock:
            return self.connections.get(device_id)

    def set_selected(self, device_id):
        def update():
            if device_id in self.display_devices:
                index = self.display_devices.index(device_id)
                self.device_list.selection_clear(0, tk.END)
                self.device_list.selection_set(index)
                self.device_list.activate(index)
            with self.lock:
                connection = self.connections.get(device_id)
            if connection:
                self.chat_title.config(text=connection.name)
                self.chat_status.config(text="🔒 Encrypted connection")
        self.root.after(0, update)

    def add_message(self, sender, message):
        self.chat_box.config(state="normal")
        self.chat_box.insert(tk.END, f"{sender}: {message}\n")
        self.chat_box.config(state="disabled")
        self.chat_box.see(tk.END)

    def send_message(self):
        connection = self.get_selected_connection()
        if not connection:
            messagebox.showwarning("No Device", "Connect to a device first.", parent=self.root)
            return
        message = self.message_entry.get().strip()
        if not message:
            return
        try:
            connection.send("CHAT", payload=message.encode("utf-8"))
            self.add_message("You", message)
            self.message_entry.delete(0, tk.END)
        except Exception as error:
            messagebox.showerror("Send Error", str(error), parent=self.root)

    def update_progress(self, text):
        self.root.after(0, lambda: self.progress_label.config(text=text))

    def show_history(self):
        window = tk.Toplevel(self.root)
        window.title("Transfer History")
        window.geometry("900x500")
        window.configure(bg="#111111")
        box = tk.Text(window, bg="#151515", fg="white", insertbackground="white", border=0, font=("Arial", 10))
        box.pack(fill="both", expand=True, padx=15, pady=15)
        history = load_history()
        if not history:
            box.insert(tk.END, "No transfers yet.\n")
        else:
            for item in history:
                box.insert(tk.END, f"{item['time']} | {item['direction']} | {item['type']} | {item['name']} | {item['size']} bytes | {item.get('peer', '')}\n")
        box.config(state="disabled")

    def shutdown(self):
        with self.lock:
            connections = list(self.connections.values())
            self.connections.clear()
        for connection in connections:
            connection.close()
        self.root.destroy()


if __name__ == "__main__":
    LANChatApp().root.mainloop()
