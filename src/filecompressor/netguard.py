"""Block network access from this process.

Every library we use works offline, so any attempt to open an internet socket
is a bug. The guard makes it fail loudly instead of reaching a server.
"""

import socket


class NetworkBlockedError(RuntimeError):
    pass


_BLOCKED_FAMILIES = {-1, socket.AF_INET, socket.AF_INET6}


def _blocked(*args, **kwargs):
    raise NetworkBlockedError("network access is disabled in filecompressor")


class _GuardedSocket(socket.socket):
    # Unix-domain sockets stay allowed; they never leave the machine.
    def __init__(self, family=-1, type=-1, proto=-1, fileno=None):
        if fileno is None and family in _BLOCKED_FAMILIES:
            _blocked()
        super().__init__(family, type, proto, fileno)


def install() -> None:
    socket.socket = _GuardedSocket
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked
    socket.gethostbyname = _blocked
    socket.gethostbyname_ex = _blocked
