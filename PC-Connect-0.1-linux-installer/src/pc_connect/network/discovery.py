import socket
import threading
import time

from pc_connect import config
from pc_connect.core.models import Device


class DiscoveryService:
    def __init__(self, state, local_ip, identity, status_callback):
        self.state = state
        self.local_ip = local_ip
        self.identity = identity
        self.status_callback = status_callback

    def start(self):
        threading.Thread(target=self._listen, daemon=True).start()
        threading.Thread(target=self._announce, daemon=True).start()

    def _listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", config.DISCOVERY_PORT))
            sock.settimeout(1.0)
        except OSError as error:
            self.status_callback(f"Discovery unavailable: {error}")
            return
        while self.state.running:
            try:
                data, address = sock.recvfrom(2048)
                fields = data.decode(errors="replace").split("|", 5)
                if len(fields) != 6 or fields[0] != "PCCONNECT":
                    continue
                _, version, device_id, name, fingerprint, _port = fields
                ip = address[0]
                if ip == self.local_ip or device_id == self.identity.device_id:
                    continue
                with self.state.lock:
                    self.state.devices[ip] = Device(ip, name.strip() or "Unnamed Device", time.time(), device_id, fingerprint.upper(), int(version))
            except socket.timeout:
                continue
            except (OSError, ValueError):
                if self.state.running:
                    continue
        sock.close()

    def _announce(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self.state.running:
            try:
                message = f"PCCONNECT|{config.PROTOCOL_VERSION}|{self.identity.device_id}|{self.state.device_name}|{self.identity.fingerprint()}|{config.CHAT_PORT}".encode("utf-8")
                sock.sendto(message, ("255.255.255.255", config.DISCOVERY_PORT))
            except OSError:
                pass
            time.sleep(config.ANNOUNCE_INTERVAL)
        sock.close()
