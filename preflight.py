from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

import psutil

from config import ServiceConfig


@dataclass
class CheckResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


class PreflightChecker:

    @staticmethod
    def check_executable(name: str) -> str | None:
        if shutil.which(name) is None:
            return f"Executable '{name}' not found in PATH"
        return None

    @staticmethod
    def check_directory(path: str) -> str | None:
        if not os.path.isdir(path):
            return f"Directory not found: {path}"
        return None

    @staticmethod
    def check_port(port: int) -> str | None:
        import socket
        # Actual bind test — immune to ghost LISTEN entries from dead processes
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return None  # Port is free
        except OSError:
            s.close()
        # Port truly occupied — find who owns it
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr.port == port and conn.status == "LISTEN" and conn.pid:
                    return f"Port {port} already in use (PID {conn.pid})"
        except (psutil.AccessDenied, psutil.Error):
            pass
        return f"Port {port} already in use"

    @staticmethod
    def check_file(path: str) -> str | None:
        if not os.path.isfile(path):
            return f"File not found: {path}"
        return None

    @classmethod
    def run_all(cls, svc: ServiceConfig, port: int | None = None) -> CheckResult:
        failures: list[str] = []

        if svc.command:
            exe = svc.command[0]
            err = cls.check_executable(exe)
            if err:
                failures.append(err)

        err = cls.check_directory(svc.cwd)
        if err:
            failures.append(err)

        if port is not None:
            err = cls.check_port(port)
            if err:
                failures.append(err)

        return CheckResult(passed=len(failures) == 0, failures=failures)
