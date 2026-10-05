import threading


class AppState:
    def __init__(self):
        self.lock = threading.RLock()
        self.devices = {}
        self.connections = {}
        self.outgoing_requests = {}
        self.accepted_incoming = {}
        self.active_transfers = {}
        self.transfer_controls = {}
        self.transfer_requests = {}
        self.device_name = ""
        self.selected_device = None
        self.running = True

    def get_connection(self, ip):
        with self.lock:
            return self.connections.get(ip)

    def device_name_for(self, ip):
        with self.lock:
            device = self.devices.get(ip)
            return device.name if device else ip
