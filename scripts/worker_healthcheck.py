"""Worker container healthcheck: healthy while the key Arq refreshes every ``health_check_interval`` exists.

``arq --check`` reads the same key, but imports the whole worker to find its settings: about 4 s of CPU every
10 s on the host the API shares. This speaks the Redis protocol over a socket and imports nothing else.
"""

from __future__ import annotations

import os
import socket
import sys
from urllib.parse import unquote, urlsplit

HEALTH_KEY = "arq:queue:health-check"  # arq.constants: default_queue_name + health_check_key_suffix


def _command(*parts: str) -> bytes:
    out = [f"*{len(parts)}\r\n".encode()]
    for part in parts:
        data = part.encode()
        out.append(b"$%d\r\n%s\r\n" % (len(data), data))
    return b"".join(out)


def check(redis_url: str) -> bool:
    url = urlsplit(redis_url)
    commands = []
    if url.password:
        user = [unquote(url.username)] if url.username else []
        commands.append(_command("AUTH", *user, unquote(url.password)))
    commands.append(_command("SELECT", url.path.lstrip("/") or "0"))
    commands.append(_command("EXISTS", HEALTH_KEY))
    with socket.create_connection((url.hostname or "localhost", url.port or 6379), timeout=2) as conn:
        conn.sendall(b"".join(commands))
        replies = b""
        while replies.count(b"\r\n") < len(commands):  # every reply here is one line: +OK, -ERR or :<n>
            chunk = conn.recv(4096)
            if not chunk:
                return False
            replies += chunk
    lines = replies.split(b"\r\n")[: len(commands)]
    return all(not line.startswith(b"-") for line in lines) and lines[-1] == b":1"


def main() -> int:
    try:
        return 0 if check(os.environ.get("CRAG_REDIS_URL", "redis://localhost:8630/0")) else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
