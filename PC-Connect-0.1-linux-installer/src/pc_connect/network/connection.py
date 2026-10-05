import socket
import ssl
import threading
import time

from pc_connect.config import CHAT_PORT, CONNECT_TIMEOUT, PROTOCOL_VERSION
from pc_connect.network.protocol import control, parse_control, receive_packet, send_packet


class ConnectionService:
    def __init__(self, state, packet_handler, connected_callback, disconnected_callback, error_callback, identity, trust_callback):
        self.state = state
        self.packet_handler = packet_handler
        self.connected_callback = connected_callback
        self.disconnected_callback = disconnected_callback
        self.error_callback = error_callback
        self.identity = identity
        self.trust_callback = trust_callback
        self.server = None
        self.tls_context = self._server_context()

    def _server_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(self.identity.cert_path, self.identity.key_path)
        context.options |= ssl.OP_NO_COMPRESSION
        return context

    def _client_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.options |= ssl.OP_NO_COMPRESSION
        return context

    def start(self):
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("0.0.0.0", CHAT_PORT))
            server.listen()
            server.settimeout(1.0)
            self.server = server
        except OSError as error:
            self.error_callback(f"Cannot listen on port {CHAT_PORT}: {error}")
            close_socket(server)
            return
        while self.state.running:
            try:
                raw, address = server.accept()
                threading.Thread(target=self._accept_tls, args=(raw, address[0]), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                if self.state.running:
                    time.sleep(0.2)
                else:
                    break
        close_socket(server)

    def _accept_tls(self, raw, ip):
        try:
            connection = self.tls_context.wrap_socket(raw, server_side=True)
            self._authenticate(connection, ip)
            self.register(connection, ip)
        except Exception as error:
            self.error_callback(f"Secure connection rejected from {ip}: {error}")
            close_socket(raw)

    def connect(self, ip):
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            raw.settimeout(CONNECT_TIMEOUT)
            raw.connect((ip, CHAT_PORT))
            connection = self._client_context().wrap_socket(raw, server_hostname="pc-connect.local")
            connection.settimeout(None)
            self._authenticate(connection, ip)
        except Exception:
            close_socket(raw)
            raise
        self.register(connection, ip)

    def _authenticate(self, connection, ip):
        local = {"action": "hello", "version": PROTOCOL_VERSION, "device_id": self.identity.device_id, "name": self.state.device_name, "fingerprint": self.identity.fingerprint()}
        send_packet(connection, control(**local))
        packet = receive_packet(connection)
        remote = parse_control(packet or b"")
        if not remote or remote.get("action") != "hello":
            raise ConnectionError("Peer did not complete the secure handshake")
        if int(remote.get("version", 0)) != PROTOCOL_VERSION:
            raise ConnectionError("Incompatible PC Connect security protocol")
        cert_der = connection.getpeercert(binary_form=True)
        actual = self.identity.fingerprint(cert_der)
        advertised = str(remote.get("fingerprint", "")).upper()
        if actual != advertised:
            raise ssl.SSLError("Peer certificate fingerprint does not match its identity")
        device_id = str(remote.get("device_id", ""))
        if not device_id:
            raise ConnectionError("Peer did not provide a device identity")
        if not self.identity.is_trusted(device_id, actual):
            if not self.trust_callback(ip, remote.get("name", ip), device_id, actual):
                raise PermissionError("Device was not trusted")
            self.identity.trust(device_id, actual, remote.get("name", ip))

    def register(self, connection, ip):
        with self.state.lock:
            old = self.state.connections.get(ip)
            self.state.connections[ip] = connection
        if old is not None and old is not connection:
            close_socket(old)
        threading.Thread(target=self._receive_loop, args=(connection, ip), daemon=True).start()
        self.connected_callback(ip)

    def _receive_loop(self, connection, ip):
        try:
            while self.state.running:
                packet = receive_packet(connection)
                if packet is None:
                    break
                self.packet_handler(connection, ip, packet)
        except Exception as error:
            self.error_callback(f"Connection error: {error}")
        finally:
            with self.state.lock:
                current = self.state.connections.get(ip)
                if current is connection:
                    del self.state.connections[ip]
                    should_notify = True
                else:
                    should_notify = False
            close_socket(connection)
            if should_notify:
                self.disconnected_callback(ip)

    def close_all(self):
        self.state.running = False
        with self.state.lock:
            connections = list(self.state.connections.values())
            self.state.connections.clear()
        for connection in connections:
            close_socket(connection)
        close_socket(self.server)


def close_socket(connection):
    if connection is None:
        return
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        connection.close()
    except OSError:
        pass
