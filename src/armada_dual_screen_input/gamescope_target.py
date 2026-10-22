"""Shared identity and peer checks for the verified upper Gamescope instance."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import socket
import struct

from .gamescope_probe import _display_path, _socket_info, _validate_runtime


class InputUnavailable(RuntimeError):
    pass


def same_user_peer_pid(fd: int) -> int:
    """Read credentials from an already-connected Unix socket; send no data."""
    with socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        pid, uid, _ = struct.unpack('3i', connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    if pid <= 0 or uid != os.getuid():
        raise InputUnavailable('graphics socket does not belong to the current user')
    return pid


@dataclass(frozen=True)
class GamescopeTarget:
    runtime: Path
    display_name: str
    display_path: Path
    eis_path: Path
    identity: tuple[int, int, int, int]

    @classmethod
    def resolve(cls, runtime: Path, name: str = 'gamescope-primary') -> GamescopeTarget:
        # Resolve the directory once and use each freshly validated socket's
        # metadata for its identity. is_current() repeats this entire operation;
        # no path, ownership or identity result authorizes a later event.
        runtime = _validate_runtime(runtime)
        display = _display_path(runtime, name)
        eis = _display_path(runtime, display.name + '-ei')
        # Read identities after both paths resolve, so replacing the display
        # socket during the partner lookup cannot reuse its earlier metadata.
        a, b = _socket_info(display), _socket_info(eis)
        return cls(runtime, name, display, eis,
                   (a.st_dev, a.st_ino, b.st_dev, b.st_ino))

    def is_current(self) -> bool:
        try:
            return type(self).resolve(self.runtime, self.display_name) == self
        except (OSError, ValueError):
            return False
