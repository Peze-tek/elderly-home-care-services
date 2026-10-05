from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TransferDirection(str, Enum):
    SEND = "send"
    RECEIVE = "receive"


class TransferType(str, Enum):
    FILE = "file"
    FOLDER = "folder"


@dataclass
class Device:
    ip: str
    name: str
    last_seen: float
    device_id: str = ""
    fingerprint: str = ""
    protocol_version: int = 4


@dataclass
class TransferRequest:
    name: str
    path: str
    transfer_type: TransferType
    size: int = 0


@dataclass
class TransferProgress:
    transfer_id: str
    ip: str
    name: str
    transfer_type: TransferType
    direction: TransferDirection
    total: int
    completed: int = 0
    status: str = "queued"
    error: Optional[str] = None

    @property
    def percent(self):
        if self.total <= 0:
            return 100
        return min(100, int(self.completed * 100 / self.total))
