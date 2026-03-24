from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ServiceConfig:
    name: str
    cwd: str
    command: list[str]
    health_url: str | None = None
    admin_url: str | None = None
    token_dir: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class UIConfig:
    log_max_lines: int = 5000
    health_check_interval: int = 5
    health_check_failures: int = 3
    poll_interval_ms: int = 100
    global_search_hotkey: str = "alt+s"
    floating_search_hotkey: str = "alt+q"
    default_output_dir: str = ""
    default_search_mode: str = "detailed"
    default_web_enabled: bool = True


@dataclass
class AppConfig:
    services: dict[str, ServiceConfig] = field(default_factory=dict)
    ui: UIConfig = field(default_factory=UIConfig)
    config_path: str = ""


_DEFAULT_SERVICES = {
    "grok2api": {
        "name": "Grok2API",
        "cwd": r"C:\Users\12695\grok2api",
        "command": [
            "uv", "run", "granian",
            "--interface", "asgi",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--workers", "1",
            "main:app",
        ],
        "health_url": "http://127.0.0.1:8000/health",
        "admin_url": "http://127.0.0.1:8000/admin",
    },
    "grok_maintainer": {
        "name": "Grok-Maintainer",
        "cwd": r"C:\Users\12695\grok-maintainer",
        "command": ["python", "DrissionPage_example.py", "--count", "{count}"],
        "token_dir": r"C:\Users\12695\grok-maintainer\sso",
    },
}

_DEFAULT_UI = {
    "log_max_lines": 5000,
    "health_check_interval": 5,
    "health_check_failures": 3,
    "poll_interval_ms": 100,
    "global_search_hotkey": "alt+s",
    "floating_search_hotkey": "alt+q",
    "default_output_dir": "",
    "default_search_mode": "detailed",
    "default_web_enabled": True,
}


def _parse_service(key: str, raw: dict) -> ServiceConfig:
    return ServiceConfig(
        name=raw.get("name", key),
        cwd=raw.get("cwd", ""),
        command=raw.get("command", []),
        health_url=raw.get("health_url"),
        admin_url=raw.get("admin_url"),
        token_dir=raw.get("token_dir"),
        env=raw.get("env", {}),
    )


def save_default_config(path: str | Path) -> None:
    data = {
        "services": _DEFAULT_SERVICES,
        "ui": _DEFAULT_UI,
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _service_to_dict(service: ServiceConfig) -> dict:
    return {
        "name": service.name,
        "cwd": service.cwd,
        "command": service.command,
        "health_url": service.health_url,
        "admin_url": service.admin_url,
        "token_dir": service.token_dir,
        "env": service.env,
    }


def save_config(config: AppConfig, path: str | Path | None = None) -> None:
    p = Path(path or config.config_path or "config.yaml")
    data = {
        "services": {key: _service_to_dict(value) for key, value in config.services.items()},
        "ui": {
            "log_max_lines": config.ui.log_max_lines,
            "health_check_interval": config.ui.health_check_interval,
            "health_check_failures": config.ui.health_check_failures,
            "poll_interval_ms": config.ui.poll_interval_ms,
            "global_search_hotkey": config.ui.global_search_hotkey,
            "floating_search_hotkey": config.ui.floating_search_hotkey,
            "default_output_dir": config.ui.default_output_dir,
            "default_search_mode": config.ui.default_search_mode,
            "default_web_enabled": config.ui.default_web_enabled,
        },
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.exists():
        save_default_config(p)

    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        raw = {}

    if not isinstance(raw, dict):
        raw = {}

    services = {}
    raw_services = raw.get("services", {})
    if isinstance(raw_services, dict):
        for key, svc_raw in raw_services.items():
            if isinstance(svc_raw, dict):
                services[key] = _parse_service(key, svc_raw)

    ui_raw = raw.get("ui", {})
    ui = UIConfig(
        log_max_lines=ui_raw.get("log_max_lines", 5000),
        health_check_interval=ui_raw.get("health_check_interval", 5),
        health_check_failures=ui_raw.get("health_check_failures", 3),
        poll_interval_ms=ui_raw.get("poll_interval_ms", 100),
        global_search_hotkey=ui_raw.get("global_search_hotkey", "alt+s"),
        floating_search_hotkey=ui_raw.get("floating_search_hotkey", "alt+q"),
        default_output_dir=ui_raw.get("default_output_dir", ""),
        default_search_mode=ui_raw.get("default_search_mode", "detailed"),
        default_web_enabled=ui_raw.get("default_web_enabled", True),
    )

    return AppConfig(services=services, ui=ui, config_path=str(p))
