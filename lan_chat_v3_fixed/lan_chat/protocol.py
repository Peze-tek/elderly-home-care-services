import json
import socket
import struct

MAX_FRAME_SIZE = 256 * 1024 * 1024
MAX_HEADER_SIZE = 64 * 1024


def recv_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data.extend(chunk)
    return bytes(data)


def send_packet(sock, message_type, transfer_id="", meta=None, payload=b""):
    if meta is None:
        meta = {}
    header = {
        "type": message_type,
        "id": transfer_id,
        "meta": meta,
        "size": len(payload),
    }
    raw_header = json.dumps(header, separators=(",", ":")).encode("utf-8")
    if len(raw_header) > MAX_HEADER_SIZE:
        raise ValueError("Header is too large")
    frame_size = 4 + len(raw_header) + len(payload)
    if frame_size > MAX_FRAME_SIZE:
        raise ValueError("Frame is too large")
    sock.sendall(struct.pack("!I", len(raw_header)))
    sock.sendall(raw_header)
    if payload:
        sock.sendall(payload)


def receive_packet(sock):
    raw = recv_exact(sock, 4)
    header_size = struct.unpack("!I", raw)[0]
    if header_size <= 0 or header_size > MAX_HEADER_SIZE:
        raise ValueError("Invalid header size")
    header = json.loads(recv_exact(sock, header_size).decode("utf-8"))
    payload_size = int(header.get("size", 0))
    if payload_size < 0 or payload_size > MAX_FRAME_SIZE:
        raise ValueError("Invalid payload size")
    payload = recv_exact(sock, payload_size) if payload_size else b""
    return header, payload
