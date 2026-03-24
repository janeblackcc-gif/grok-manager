from __future__ import annotations

import queue
import threading
from typing import IO

SENTINEL = None


def _decode_line(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("latin-1", errors="replace")


class LogReaderThread:

    def __init__(self, stream: IO[bytes], log_queue: queue.Queue, name: str = ""):
        self._stream = stream
        self._queue = log_queue
        self._name = name
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"log-reader-{name}"
        )

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        try:
            for raw_line in iter(self._stream.readline, b""):
                if not raw_line:
                    break
                text = _decode_line(raw_line).rstrip("\r\n")
                try:
                    self._queue.put_nowait(text)
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._queue.put_nowait(text)
                    except queue.Full:
                        pass
        except (OSError, ValueError):
            pass
        finally:
            try:
                self._queue.put_nowait(SENTINEL)
            except queue.Full:
                pass
