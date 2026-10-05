import os
import threading
import time
import uuid
from pathlib import Path

from pc_connect.core.models import TransferDirection, TransferProgress, TransferType
from pc_connect.network.protocol import control, data_packet, parse_data, receive_packet, send_packet, parse_control
from pc_connect.utils.files import safe_name, unique_path, create_folder_zip, safe_extract_zip


class TransferCancelled(Exception):
    pass


class TransferService:
    def __init__(self, state, history, config, progress_callback, finished_callback, error_callback, side_packet_handler):
        self.state = state
        self.history = history
        self.config = config
        self.progress_callback = progress_callback
        self.finished_callback = finished_callback
        self.error_callback = error_callback
        self.side_packet_handler = side_packet_handler

    def _new_id(self):
        return uuid.uuid4().hex[:12]

    def _control_for(self, transfer_id):
        with self.state.lock:
            return self.state.transfer_controls.setdefault(transfer_id, {"cancel": threading.Event(), "pause": threading.Event()})

    def _emit(self, progress):
        self.state.active_transfers[progress.transfer_id] = progress
        self.progress_callback(progress)

    def send_path(self, connection, ip, path, transfer_type):
        source = Path(path)
        if transfer_type is TransferType.FOLDER:
            zip_path = None
            try:
                zip_path, name = create_folder_zip(source)
                self._send_payload(connection, ip, name, zip_path, TransferType.FOLDER)
            finally:
                if zip_path:
                    zip_path.unlink(missing_ok=True)
        else:
            self._send_payload(connection, ip, source.name, source, TransferType.FILE)

    def _send_payload(self, connection, ip, name, path, transfer_type):
        transfer_id = self._new_id()
        size = Path(path).stat().st_size
        controls = self._control_for(transfer_id)
        progress = TransferProgress(transfer_id, ip, name, transfer_type, TransferDirection.SEND, size, 0, "sending")
        self._emit(progress)
        try:
            send_packet(connection, control("transfer_start", id=transfer_id, kind=transfer_type.value, name=name, size=size))
            sent = 0
            with Path(path).open("rb") as file:
                while True:
                    if controls["cancel"].is_set():
                        send_packet(connection, control("cancel", id=transfer_id))
                        raise TransferCancelled()
                    while controls["pause"].is_set() and not controls["cancel"].is_set():
                        progress.status = "paused"
                        self._emit(progress)
                        time.sleep(0.1)
                    if controls["cancel"].is_set():
                        send_packet(connection, control("cancel", id=transfer_id))
                        raise TransferCancelled()
                    chunk = file.read(self.config.BUFFER_SIZE)
                    if not chunk:
                        break
                    send_packet(connection, data_packet(transfer_id, chunk))
                    sent += len(chunk)
                    progress.completed = sent
                    progress.status = "paused" if controls["pause"].is_set() else "sending"
                    self._emit(progress)
            send_packet(connection, control("transfer_end", id=transfer_id))
            progress.completed = size
            progress.status = "completed"
            self._emit(progress)
            self.history.add("Sent", transfer_type.value.capitalize(), name, size)
            self.finished_callback(progress)
        except TransferCancelled:
            progress.status = "cancelled"
            self._emit(progress)
            self.finished_callback(progress)
        except Exception as error:
            progress.status = "failed"
            progress.error = str(error)
            self._emit(progress)
            self.error_callback(progress, error)
        finally:
            with self.state.lock:
                self.state.active_transfers.pop(transfer_id, None)
                self.state.transfer_controls.pop(transfer_id, None)

    def receive_payload(self, connection, ip, transfer_id, name, size, transfer_type):
        if transfer_type is TransferType.FILE:
            self.config.RECEIVED_FILES_DIR.mkdir(parents=True, exist_ok=True)
            destination = unique_path(self.config.RECEIVED_FILES_DIR, safe_name(name))
        else:
            import tempfile
            self.config.RECEIVED_FOLDERS_DIR.mkdir(parents=True, exist_ok=True)
            destination = Path(tempfile.mkstemp(suffix=".zip", dir=self.config.DATA_DIR)[1])
        controls = self._control_for(transfer_id)
        progress = TransferProgress(transfer_id, ip, name, transfer_type, TransferDirection.RECEIVE, size, 0, "receiving")
        self._emit(progress)
        completed = False
        try:
            with Path(destination).open("wb") as file:
                while True:
                    packet = receive_packet(connection)
                    if packet is None:
                        raise ConnectionError("Connection closed during transfer")
                    action = parse_control(packet)
                    if action and action.get("id") == transfer_id:
                        if action.get("action") == "transfer_end":
                            completed = True
                            break
                        if action.get("action") == "cancel":
                            raise TransferCancelled()
                        if action.get("action") == "pause":
                            progress.status = "paused"
                            self._emit(progress)
                            continue
                        if action.get("action") == "resume":
                            progress.status = "receiving"
                            self._emit(progress)
                            continue
                    packet_id, chunk = parse_data(packet)
                    if packet_id == transfer_id:
                        if controls["cancel"].is_set():
                            send_packet(connection, control("cancel", id=transfer_id))
                            raise TransferCancelled()
                        file.write(chunk)
                        progress.completed += len(chunk)
                        self._emit(progress)
                        continue
                    self.side_packet_handler(connection, ip, packet)
            if not completed or progress.completed != size:
                raise TransferCancelled()
            if transfer_type is TransferType.FOLDER:
                safe_extract_zip(destination, self.config.RECEIVED_FOLDERS_DIR)
                destination.unlink(missing_ok=True)
            progress.status = "completed"
            self._emit(progress)
            self.history.add("Received", transfer_type.value.capitalize(), safe_name(name), size)
            self.finished_callback(progress)
        except TransferCancelled:
            Path(destination).unlink(missing_ok=True)
            progress.status = "cancelled"
            self._emit(progress)
            self.finished_callback(progress)
        except Exception as error:
            Path(destination).unlink(missing_ok=True)
            progress.status = "failed"
            progress.error = str(error)
            self._emit(progress)
            self.error_callback(progress, error)
        finally:
            with self.state.lock:
                self.state.active_transfers.pop(transfer_id, None)
                self.state.transfer_controls.pop(transfer_id, None)

    def cancel(self, transfer_id, connection):
        controls = self._control_for(transfer_id)
        controls["cancel"].set()
        try:
            send_packet(connection, control("cancel", id=transfer_id))
        except OSError:
            pass

    def pause(self, transfer_id, connection):
        controls = self._control_for(transfer_id)
        if controls["pause"].is_set():
            controls["pause"].clear()
            send_packet(connection, control("resume", id=transfer_id))
        else:
            controls["pause"].set()
            send_packet(connection, control("pause", id=transfer_id))

    def retry(self, request, connection, ip):
        threading.Thread(target=self.send_path, args=(connection, ip, request.path, request.transfer_type), daemon=True).start()
