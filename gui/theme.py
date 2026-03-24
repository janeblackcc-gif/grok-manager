from __future__ import annotations

import tkinter.font as tkfont
from typing import Callable

from service_manager import ServiceState

# ── Theme palettes ──

_DARK = {
    "BG_ROOT": "#1A1B1E",
    "BG_SIDEBAR": "#141517",
    "BG_CARD": "#25262B",
    "BG_INPUT": "#2C2E33",
    "BG_LOG": "#1A1B1E",
    "ACCENT_GREEN": "#2D9964",
    "ACCENT_BLUE": "#339AF0",
    "ACCENT_RED": "#FA5252",
    "ACCENT_YELLOW": "#FCC419",
    "ACCENT_ORANGE": "#FF922B",
    "HOVER_GREEN": "#37B876",
    "HOVER_RED": "#E03131",
    "HOVER_BLUE": "#4DABF7",
    "TEXT_PRIMARY": "#C1C2C5",
    "TEXT_SECONDARY": "#909296",
    "TEXT_MUTED": "#5C5F66",
    "TEXT_WHITE": "#FFFFFF",
    "TEXT_LOG": "#4ADE80",
    "CARD_BORDER_COLOR": "#373A40",
    "HOVER_GENERIC": "#3A3C42",
    "HIGHLIGHT_BG": "#FCC419",
    "HIGHLIGHT_FG": "#1A1B1E",
    "STATUS_PILL_active_bg": "#1A3329",
    "STATUS_PILL_cooling_bg": "#332E1A",
    "STATUS_PILL_expired_bg": "#331A1A",
    "STATUS_PILL_disabled_bg": "#2C2E33",
    "STATE_BG_STOPPED": "#2C2E33",
    "STATE_BG_STARTING": "#1A2A42",
    "STATE_BG_RUNNING": "#1A3329",
    "STATE_BG_STOPPING": "#332E1A",
    "STATE_BG_DEGRADED": "#33261A",
    "STATE_BG_ERROR": "#331A1A",
    "MD_CODE_BG": "#2C2E33",
    "ACCENT_PURPLE": "#9775FA",
    "HOVER_PURPLE": "#B197FC",
}

_LIGHT = {
    "BG_ROOT": "#F0F1F3",
    "BG_SIDEBAR": "#E4E5E9",
    "BG_CARD": "#FFFFFF",
    "BG_INPUT": "#E9ECEF",
    "BG_LOG": "#F8F9FA",
    "ACCENT_GREEN": "#2B8A3E",
    "ACCENT_BLUE": "#1C7ED6",
    "ACCENT_RED": "#E03131",
    "ACCENT_YELLOW": "#E67700",
    "ACCENT_ORANGE": "#D9480F",
    "HOVER_GREEN": "#37B24D",
    "HOVER_RED": "#C92A2A",
    "HOVER_BLUE": "#339AF0",
    "TEXT_PRIMARY": "#212529",
    "TEXT_SECONDARY": "#495057",
    "TEXT_MUTED": "#ADB5BD",
    "TEXT_WHITE": "#FFFFFF",
    "TEXT_LOG": "#2B8A3E",
    "CARD_BORDER_COLOR": "#DEE2E6",
    "HOVER_GENERIC": "#D0D3D8",
    "HIGHLIGHT_BG": "#FFE066",
    "HIGHLIGHT_FG": "#212529",
    "STATUS_PILL_active_bg": "#D3F9D8",
    "STATUS_PILL_cooling_bg": "#FFF3BF",
    "STATUS_PILL_expired_bg": "#FFE3E3",
    "STATUS_PILL_disabled_bg": "#E9ECEF",
    "STATE_BG_STOPPED": "#E9ECEF",
    "STATE_BG_STARTING": "#D0EBFF",
    "STATE_BG_RUNNING": "#D3F9D8",
    "STATE_BG_STOPPING": "#FFF3BF",
    "STATE_BG_DEGRADED": "#FFE8CC",
    "STATE_BG_ERROR": "#FFE3E3",
    "MD_CODE_BG": "#E9ECEF",
    "ACCENT_PURPLE": "#7048E8",
    "HOVER_PURPLE": "#845EF7",
}

# ── Current theme state ──

_current_mode: str = "light"
_listeners: list[Callable[[], None]] = []


def get(key: str) -> str:
    palette = _DARK if _current_mode == "dark" else _LIGHT
    return palette[key]


def current_mode() -> str:
    return _current_mode


def set_mode(mode: str) -> None:
    global _current_mode
    if mode not in ("dark", "light"):
        return
    _current_mode = mode
    for cb in _listeners:
        try:
            cb()
        except Exception:
            pass


def on_theme_change(callback: Callable[[], None]) -> None:
    _listeners.append(callback)


def remove_listener(callback: Callable[[], None]) -> None:
    try:
        _listeners.remove(callback)
    except ValueError:
        pass


# ── Convenience accessors (backward compat + shorthand) ──

def state_color(state: ServiceState) -> str:
    _map = {
        ServiceState.STOPPED: "TEXT_MUTED",
        ServiceState.STARTING: "ACCENT_BLUE",
        ServiceState.RUNNING: "ACCENT_GREEN",
        ServiceState.STOPPING: "ACCENT_YELLOW",
        ServiceState.DEGRADED: "ACCENT_ORANGE",
        ServiceState.ERROR: "ACCENT_RED",
    }
    return get(_map.get(state, "TEXT_MUTED"))


def state_bg(state: ServiceState) -> str:
    _map = {
        ServiceState.STOPPED: "STATE_BG_STOPPED",
        ServiceState.STARTING: "STATE_BG_STARTING",
        ServiceState.RUNNING: "STATE_BG_RUNNING",
        ServiceState.STOPPING: "STATE_BG_STOPPING",
        ServiceState.DEGRADED: "STATE_BG_DEGRADED",
        ServiceState.ERROR: "STATE_BG_ERROR",
    }
    return get(_map.get(state, "STATE_BG_STOPPED"))


def status_pill(status: str) -> tuple[str, str]:
    fg_map = {
        "active": "ACCENT_GREEN", "cooling": "ACCENT_YELLOW",
        "expired": "ACCENT_RED", "disabled": "TEXT_MUTED",
    }
    bg_map = {
        "active": "STATUS_PILL_active_bg", "cooling": "STATUS_PILL_cooling_bg",
        "expired": "STATUS_PILL_expired_bg", "disabled": "STATUS_PILL_disabled_bg",
    }
    fg_key = fg_map.get(status, "TEXT_MUTED")
    bg_key = bg_map.get(status, "STATUS_PILL_disabled_bg")
    return get(fg_key), get(bg_key)


# ── Layout constants ──

CARD_CORNER_RADIUS = 12
CARD_BORDER_WIDTH = 1
SIDEBAR_WIDTH = 64

# ── Fonts ──

_mono_family = "Consolas"


def _detect_mono() -> str:
    try:
        families = tkfont.families()
        for candidate in ("JetBrains Mono", "JetBrains Mono NL", "Cascadia Code"):
            if candidate in families:
                return candidate
    except Exception:
        pass
    return "Consolas"


def init_fonts(root) -> None:
    global _mono_family
    _mono_family = _detect_mono()


def font_mono(size: int = 11):
    return (_mono_family, size)


def font_heading(size: int = 16):
    return ("Segoe UI", size, "bold")


def font_body(size: int = 13):
    return ("Segoe UI", size)


def font_small(size: int = 11):
    return ("Segoe UI", size)


def font_badge():
    return ("Segoe UI", 10, "bold")
