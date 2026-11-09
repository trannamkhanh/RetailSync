"""The demo scenario of PB-18-5. It lives in memory and starts as ONLINE."""

from enum import Enum


class Mode(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    SLOW = "SLOW"
    DROP_ACK = "DROP_ACK"


_mode = Mode.ONLINE


def get_mode() -> Mode:
    return _mode


def set_mode(mode: Mode) -> None:
    global _mode
    _mode = mode


def reset() -> None:
    set_mode(Mode.ONLINE)
