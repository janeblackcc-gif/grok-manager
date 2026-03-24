from __future__ import annotations

import queue
import threading

from service_manager import ServiceManager, ServiceState


class HealthChecker:

    def __init__(self, manager: ServiceManager, url: str,
                 interval: int = 5, max_failures: int = 3):
        self._manager = manager
        self._url = url
        self._interval = interval
        self._max_failures = max_failures
        self._fail_count = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._fail_count = 0
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"health-{self._manager.name}")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _check_port_ownership(self) -> bool:
        try:
            import psutil
            from urllib.parse import urlparse
            port = urlparse(self._url).port or 80
            pid = self._manager.pid
            if pid is None:
                return False
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr.port == port and conn.status == "LISTEN":
                    if conn.pid == pid:
                        return True
                    try:
                        child_pids = {c.pid for c in psutil.Process(pid).children(recursive=True)}
                        if conn.pid in child_pids:
                            return True
                    except Exception:
                        pass
            return False
        except Exception:
            return True

    def _run(self) -> None:
        import urllib.request
        while not self._stop_event.is_set():
            self._stop_event.wait(self._interval)
            if self._stop_event.is_set():
                break
            if self._manager.state not in (
                ServiceState.STARTING, ServiceState.RUNNING, ServiceState.DEGRADED
            ):
                continue
            if not self._check_port_ownership():
                self._fail_count += 1
                try:
                    self._manager.log_queue.put_nowait("[HEALTH] Port not owned by this service")
                except queue.Full:
                    pass
                if self._fail_count >= self._max_failures:
                    self._manager.mark_degraded()
                    try:
                        self._manager.log_queue.put_nowait(
                            f"[HEALTH] {self._max_failures} consecutive failures")
                    except queue.Full:
                        pass
                continue
            try:
                req = urllib.request.Request(self._url, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        self._fail_count = 0
                        if self._manager.state == ServiceState.STARTING:
                            self._manager.mark_running()
                        else:
                            self._manager.mark_recovered()
                    else:
                        self._fail_count += 1
            except Exception:
                self._fail_count += 1
            if self._fail_count >= self._max_failures:
                self._manager.mark_degraded()
                try:
                    self._manager.log_queue.put_nowait(
                        f"[HEALTH] {self._max_failures} consecutive failures")
                except queue.Full:
                    pass
