from __future__ import annotations

import json
import re
import socket
import zipfile
from datetime import datetime
from pathlib import Path

from config import AppConfig
from gui.utils.run_recorder import get_run_recorder
from gui.utils.search_history import SessionStore

_SENSITIVE_PATTERNS = [
    re.compile(r"(authorization\s*[:=]\s*)(.+)", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*)(.+)", re.IGNORECASE),
    re.compile(r"(token\s*[:=]\s*)(.+)", re.IGNORECASE),
    re.compile(r"(cookie\s*[:=]\s*)(.+)", re.IGNORECASE),
    re.compile(r"(sso[^:=]*\s*[:=]\s*)(.+)", re.IGNORECASE),
]


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def _port_summary(config: AppConfig) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for key, service in config.services.items():
        port = None
        if service.health_url:
            try:
                from urllib.parse import urlparse

                port = urlparse(service.health_url).port
            except Exception:
                port = None
        listening = False
        if port:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    listening = sock.connect_ex(("127.0.0.1", port)) == 0
            except Exception:
                listening = False
        summary[key] = {"port": port, "listening": listening}
    return summary


def export_debug_bundle(
    dest_path: str | Path,
    *,
    config: AppConfig,
    app_root: str | Path,
    recent_limit: int = 50,
) -> Path:
    app_root_path = Path(app_root)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    run_records = [record.__dict__ for record in get_run_recorder().load_recent(recent_limit)]
    sessions = [session.to_dict() for session in SessionStore().get_all()]
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "ports": _port_summary(config),
        "run_record_count": len(run_records),
        "session_count": len(sessions),
    }

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr(
            "config.json",
            json.dumps(
                {
                    "services": {key: value.__dict__ for key, value in config.services.items()},
                    "ui": config.ui.__dict__,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        zf.writestr("run_records.json", json.dumps(run_records, ensure_ascii=False, indent=2))
        zf.writestr("search_sessions.json", json.dumps(sessions, ensure_ascii=False, indent=2))

        logs_dir = app_root_path / "logs"
        if logs_dir.exists():
            for path in sorted(logs_dir.glob("*.log"))[-5:]:
                try:
                    zf.writestr(f"logs/{path.name}", _redact_text(path.read_text("utf-8", errors="ignore")))
                except Exception:
                    pass

        outputs_dir = app_root_path / "outputs"
        if outputs_dir.exists():
            for path in sorted(outputs_dir.rglob("*.json"))[-50:]:
                rel = path.relative_to(app_root_path)
                try:
                    zf.writestr(str(rel), _redact_text(path.read_text("utf-8", errors="ignore")))
                except Exception:
                    pass

    return dest
