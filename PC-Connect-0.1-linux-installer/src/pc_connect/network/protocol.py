import json
import threading
import weakref

from pc_connect.config import MAX_PACKET_SIZE

HEADER_SIZE = 8
_send_locks = weakref.WeakKeyDictionary()
_guard = threading.Lock()


def _lock_for(connection):
    with _guard:
        lock = _send_locks.get(connection)
        if lock is None:
            lock = threading.Lock()
            _send_locks[connection] = lock
        return lock


def send_packet(connection, data):
    if len(data) > MAX_PACKET_SIZE:
        raise ValueError("Packet too large")
    frame = len(data).to_bytes(HEADER_SIZE, "big") + data
    with _lock_for(connection):
        connection.sendall(frame)


def receive_exact(connection, size):
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(min(65536, size - len(data)))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def receive_packet(connection):
    header = receive_exact(connection, HEADER_SIZE)
    if header is None:
        return None
    size = int.from_bytes(header, "big")
    if size > MAX_PACKET_SIZE:
        raise ValueError("Incoming packet too large")
    return receive_exact(connection, size)


def control(action, **payload):
    data = {"action": action, **payload}
    return b"CTRL|" + json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def parse_control(packet):
    if not packet.startswith(b"CTRL|"):
        return None
    try:
        value = json.loads(packet[5:].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def data_packet(transfer_id, chunk):
    return b"DATA|" + transfer_id.encode("ascii") + b"|" + chunk


def parse_data(packet):
    if not packet.startswith(b"DATA|"):
        return None, None
    rest = packet[5:]
    transfer_id, separator, chunk = rest.partition(b"|")
    if not separator:
        return None, None
    return transfer_id.decode("ascii", errors="ignore"), chunk


def create_chat(message):
    """Create a chat packet containing a UTF-8 encoded message."""
    return b"CHAT|" + str(message).encode("utf-8")
