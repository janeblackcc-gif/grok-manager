from __future__ import annotations

import logging
import os
import queue
import re
import subprocess
import threading
from enum import Enum
from typing import Callable

from log_reader import LogReaderThread

logger = logging.getLogger(__name__)

try:
    import win32api
    import win32con
    import win32job
    import win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class ServiceState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    DEGRADED = "degraded"
    ERROR = "error"


_LEGAL_TRANSITIONS: dict[ServiceState, set[ServiceState]] = {
    ServiceState.STOPPED: {ServiceState.STARTING},
    ServiceState.STARTING: {ServiceState.RUNNING, ServiceState.STOPPING, ServiceState.ERROR},
    ServiceState.RUNNING: {ServiceState.DEGRADED, ServiceState.STOPPING, ServiceState.ERROR},
    ServiceState.DEGRADED: {ServiceState.RUNNING, ServiceState.STOPPING, ServiceState.ERROR},
    ServiceState.STOPPING: {ServiceState.STOPPED},
    ServiceState.ERROR: {ServiceState.STARTING},
}

CREATE_NO_WINDOW = 0x08000000


class ServiceManager:

    def __init__(
        self,
        name: str,
        command: list[str],
        cwd: str,
        env_extra: dict[str, str] | None = None,
        on_state_change: Callable[[ServiceState], None] | None = None,
        port: int | None = None,
    ):
        self.name = name
        self.command = command
        self.cwd = cwd
        self.env_extra = env_extra or {}
        self.on_state_change = on_state_change
        self.port = port

        self._state = ServiceState.STOPPED
        self._process: subprocess.Popen | None = None
        self._root_pid: int | None = None
        self._job_handle = None
        self._log_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._readers: list[LogReaderThread] = []
        self._exit_monitor: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> ServiceState:
        return self._state

    @property
    def log_queue(self) -> queue.Queue:
        return self._log_queue

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    def _set_state(self, new: ServiceState) -> bool:
        allowed = _LEGAL_TRANSITIONS.get(self._state, set())
        if new not in allowed:
            logger.warning(
                "[%s] Illegal transition %s -> %s", self.name, self._state, new
            )
            return False
        self._state = new
        if self.on_state_change:
            try:
                self.on_state_change(new)
            except Exception:
                logger.exception("[%s] on_state_change callback error", self.name)
        return True

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env.update(self.env_extra)
        return env

    def _create_job_object(self) -> object | None:
        if not HAS_WIN32:
            logger.warning("[%s] pywin32 unavailable, Job Objects disabled", self.name)
            return None
        try:
            job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation
            )
            info["BasicLimitInformation"]["LimitFlags"] |= (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation, info
            )
            return job
        except Exception:
            logger.exception("[%s] Failed to create Job Object", self.name)
            return None

    def _assign_to_job(self, proc: subprocess.Popen, job) -> None:
        if not HAS_WIN32 or job is None:
            return
        handle = None
        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, proc.pid
            )
            win32job.AssignProcessToJobObject(job, handle)
        except Exception:
            logger.exception("[%s] Failed to assign process to Job Object", self.name)
        finally:
            if handle:
                try:
                    win32api.CloseHandle(handle)
                except Exception:
                    pass

    def start(self) -> bool:
        with self._lock:
            if self._state not in (ServiceState.STOPPED, ServiceState.ERROR):
                logger.warning("[%s] Cannot start in state %s", self.name, self._state)
                return False
            self._set_state(ServiceState.STARTING)

        job = None
        try:
            job = self._create_job_object()
            proc = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._build_env(),
                creationflags=CREATE_NO_WINDOW,
            )
            if job:
                self._assign_to_job(proc, job)

            with self._lock:
                self._process = proc
                self._root_pid = proc.pid
                self._job_handle = job

            self._readers = []
            for stream, label in [(proc.stdout, "stdout"), (proc.stderr, "stderr")]:
                if stream:
                    reader = LogReaderThread(stream, self._log_queue, f"{self.name}-{label}")
                    reader.start()
                    self._readers.append(reader)

            self._exit_monitor = threading.Thread(
                target=self._monitor_exit, daemon=True, name=f"exit-mon-{self.name}"
            )
            self._exit_monitor.start()
            return True

        except Exception:
            logger.exception("[%s] Failed to start", self.name)
            if job and HAS_WIN32:
                try:
                    win32api.CloseHandle(job)
                except Exception:
                    pass
            with self._lock:
                self._set_state(ServiceState.ERROR)
            return False

    def _monitor_exit(self) -> None:
        proc = self._process
        if proc is None:
            return
        proc.wait()
        with self._lock:
            if self._process is not proc:
                return
            if self._state == ServiceState.STOPPING:
                self._set_state(ServiceState.STOPPED)
            elif self._state in (ServiceState.RUNNING, ServiceState.STARTING, ServiceState.DEGRADED):
                self._cleanup_handles()
                if proc.returncode == 0:
                    self._set_state(ServiceState.STOPPING)
                    self._set_state(ServiceState.STOPPED)
                    try:
                        self._log_queue.put_nowait("[SYSTEM] Service exited normally")
                    except queue.Full:
                        pass
                else:
                    self._set_state(ServiceState.ERROR)
                    try:
                        self._log_queue.put_nowait(
                            f"[SYSTEM] Service exited unexpectedly (code: {proc.returncode})"
                        )
                    except queue.Full:
                        pass

    def mark_running(self) -> None:
        with self._lock:
            if self._state == ServiceState.STARTING:
                self._set_state(ServiceState.RUNNING)

    def mark_degraded(self) -> None:
        with self._lock:
            if self._state == ServiceState.RUNNING:
                self._set_state(ServiceState.DEGRADED)

    def mark_recovered(self) -> None:
        with self._lock:
            if self._state == ServiceState.DEGRADED:
                self._set_state(ServiceState.RUNNING)

    def force_stopped(self) -> None:
        """Force state to STOPPED via STOPPING intermediate. Use as last resort."""
        with self._lock:
            if self._state == ServiceState.STOPPED:
                return
            if self._state != ServiceState.STOPPING:
                self._set_state(ServiceState.STOPPING)
            self._set_state(ServiceState.STOPPED)

    def force_error(self, message: str | None = None) -> None:
        with self._lock:
            if self._state == ServiceState.ERROR:
                return
            self._set_state(ServiceState.ERROR)
        if message:
            try:
                self._log_queue.put_nowait(f"[SYSTEM] {message}")
            except queue.Full:
                pass

    def stop(self) -> None:
        with self._lock:
            if self._state not in (ServiceState.RUNNING, ServiceState.DEGRADED, ServiceState.STARTING):
                return
            self._set_state(ServiceState.STOPPING)

        self._terminate_process_group()

        for reader in self._readers:
            reader.join(timeout=3)
        self._readers.clear()

        if self._exit_monitor:
            self._exit_monitor.join(timeout=5)
            self._exit_monitor = None

        with self._lock:
            if self._state == ServiceState.STOPPING:
                self._set_state(ServiceState.STOPPED)

    def _cleanup_handles(self) -> None:
        if self._job_handle and HAS_WIN32:
            try:
                win32api.CloseHandle(self._job_handle)
            except Exception:
                pass
            self._job_handle = None
        self._process = None

    def _kill_orphan_descendants(self, root_pid: int | None) -> None:
        if not (HAS_PSUTIL and root_pid):
            return
        try:
            children_by_parent: dict[int, list[psutil.Process]] = {}
            for proc in psutil.process_iter(["pid", "ppid"]):
                ppid = proc.info.get("ppid")
                pid = proc.info.get("pid")
                if ppid is None or pid is None:
                    continue
                children_by_parent.setdefault(ppid, []).append(proc)

            descendants: list[psutil.Process] = []
            stack = [root_pid]
            seen = {root_pid}
            while stack:
                parent_pid = stack.pop()
                for child in children_by_parent.get(parent_pid, []):
                    child_pid = child.info.get("pid")
                    if child_pid in seen:
                        continue
                    seen.add(child_pid)
                    descendants.append(child)
                    stack.append(child_pid)

            if not descendants:
                return

            logger.info(
                "[%s] Killing %d orphan descendants for root PID %s",
                self.name,
                len(descendants),
                root_pid,
            )
            for child in reversed(descendants):
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            gone, alive = psutil.wait_procs(descendants, timeout=5)
            for child in alive:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            logger.exception(
                "[%s] Failed to kill orphan descendants for root PID %s",
                self.name,
                root_pid,
            )

    def _terminate_process_group(self) -> None:
        root_pid = self._root_pid or (self._process.pid if self._process else None)
        if self._job_handle and HAS_WIN32:
            try:
                win32job.TerminateJobObject(self._job_handle, 1)
                win32api.CloseHandle(self._job_handle)
            except Exception:
                logger.exception("[%s] TerminateJobObject failed, using fallback", self.name)
                self._fallback_kill()
            finally:
                self._job_handle = None
        else:
            self._fallback_kill()

        if self._process:
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        self._kill_orphan_descendants(root_pid)

        # Last resort: kill by port if process tree cleanup missed orphans
        if self.port and HAS_PSUTIL:
            self._kill_by_port(self.port)

    def _kill_by_port(self, port: int) -> None:
        """Find and kill any process still listening on the given port."""
        pids = self._listening_pids_by_port(port)
        if not pids:
            return

        logger.info(
            "[%s] Found %d listener(s) on port %d: %s",
            self.name,
            len(pids),
            port,
            sorted(pids),
        )

        for pid in sorted(pids):
            self._kill_pid_tree(pid, port)

    def _listening_pids_by_port(self, port: int) -> set[int]:
        pids: set[int] = set()
        if HAS_PSUTIL:
            try:
                for conn in psutil.net_connections(kind="inet"):
                    if conn.laddr.port == port and conn.status == "LISTEN" and conn.pid:
                        pids.add(int(conn.pid))
            except Exception:
                logger.exception("[%s] psutil port scan failed for port %d", self.name, port)

        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                creationflags=CREATE_NO_WINDOW,
                timeout=10,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                pattern = re.compile(rf"^\s*TCP\s+\S+:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$")
                for line in result.stdout.splitlines():
                    match = pattern.match(line)
                    if match:
                        pids.add(int(match.group(1)))
        except Exception:
            logger.exception("[%s] netstat port scan failed for port %d", self.name, port)

        return pids

    def _kill_pid_tree(self, pid: int, port: int) -> None:
        try:
            if HAS_PSUTIL:
                try:
                    p = psutil.Process(pid)
                    for child in p.children(recursive=True):
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            pass
                    p.kill()
                    p.wait(timeout=5)
                    logger.info("[%s] Killed orphan PID %d on port %d", self.name, pid, port)
                    return
                except psutil.NoSuchProcess:
                    self._kill_orphan_descendants(pid)
                    return
                except psutil.AccessDenied:
                    pass

            r = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=CREATE_NO_WINDOW,
                timeout=10,
                capture_output=True,
            )
            if r.returncode == 0:
                logger.info("[%s] taskkill killed PID %d on port %d", self.name, pid, port)
                return

            if "not found" in (r.stdout or "").lower() or "not found" in (r.stderr or "").lower():
                self._kill_orphan_descendants(pid)
                return

            logger.warning("[%s] Normal kill failed for PID %d, trying elevated", self.name, pid)
            try:
                self._log_queue.put_nowait(
                    f"[SYSTEM] Port {port} held by protected process (PID {pid}), requesting admin kill..."
                )
            except queue.Full:
                pass
            subprocess.run(
                ["powershell", "-Command",
                 "Start-Process", "taskkill",
                 "-ArgumentList", f'"/F /T /PID {pid}"',
                 "-Verb", "RunAs", "-Wait"],
                creationflags=CREATE_NO_WINDOW, timeout=30,
            )
            self._kill_orphan_descendants(pid)
        except Exception:
            logger.exception("[%s] _kill_pid_tree failed for PID %d on port %d", self.name, pid, port)

    def _fallback_kill(self) -> None:
        proc = self._process
        if proc is None:
            return
        logger.info("[%s] Using fallback kill (psutil+taskkill)", self.name)
        try:
            self._log_queue.put_nowait("[SYSTEM] Job Objects unavailable, using fallback")
        except queue.Full:
            pass

        if HAS_PSUTIL:
            try:
                parent = psutil.Process(proc.pid)
                # Collect ALL descendants before killing anything
                descendants = parent.children(recursive=True)
                for child in reversed(descendants):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                parent.kill()
                parent.wait(timeout=5)
            except psutil.NoSuchProcess:
                self._kill_orphan_descendants(proc.pid)
            except Exception:
                logger.exception("[%s] psutil fallback failed, trying taskkill", self.name)
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        creationflags=CREATE_NO_WINDOW, timeout=10,
                    )
                except Exception:
                    logger.exception("[%s] taskkill fallback failed", self.name)
                self._kill_orphan_descendants(proc.pid)
        else:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    creationflags=CREATE_NO_WINDOW, timeout=10,
                )
            except Exception:
                logger.exception("[%s] taskkill fallback failed", self.name)

    def is_alive(self) -> bool:
        proc = self._process
        return proc is not None and proc.poll() is None
