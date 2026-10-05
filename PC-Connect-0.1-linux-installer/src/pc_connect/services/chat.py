from pc_connect.network.protocol import send_packet, create_chat


class ChatService:
    def __init__(self, state, status_callback, message_callback, device_name_callback):
        self.state = state
        self.status_callback = status_callback
        self.message_callback = message_callback
        self.device_name_callback = device_name_callback

    def send(self, ip, message):
        connection = self.state.get_connection(ip)
        if connection is None:
            raise ConnectionError("No active connection")
        send_packet(connection, create_chat(message))
        self.message_callback("You", message)

    def handle_chat_packet(self, ip, packet):
        message = packet[len(b"CHAT|"):].decode(errors="replace")
        self.message_callback(self.device_name_callback(ip), message)
