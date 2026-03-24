from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from gui import theme
from gui.widgets.tooltip import Tooltip

NAV_ITEMS = [
    ("dashboard", "\u2302", "Dashboard"),
    ("services", "\u25B6", "Services"),
    ("pool", "\U0001F511", "Accounts"),
    ("ai_search", "\U0001F50D", "AI Search"),
    ("creation", "\U0001F3A8", "Creation Center"),
    ("test_lab", "\U0001F9EA", "Test Lab"),
]

_SHORTCUTS = {"ai_search": "Ctrl+K / Alt+S"}


class Sidebar(ctk.CTkFrame):

    def __init__(self, master, on_navigate: Callable[[str], None],
                 on_toggle_theme: Callable[[], None] | None = None,
                 on_open_settings: Callable[[], None] | None = None):
        super().__init__(master, width=theme.SIDEBAR_WIDTH,
                         fg_color=theme.get("BG_SIDEBAR"), corner_radius=0)
        self.pack_propagate(False)
        self._on_navigate = on_navigate
        self._on_toggle_theme = on_toggle_theme
        self._on_open_settings = on_open_settings
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._indicators: dict[str, ctk.CTkFrame] = {}
        self._tooltips: dict[str, Tooltip] = {}
        self._active: str | None = None

        # Logo
        self._logo = ctk.CTkLabel(
            self, text="G", font=("Segoe UI", 22, "bold"),
            text_color=theme.get("ACCENT_BLUE"),
            width=theme.SIDEBAR_WIDTH, height=48,
        )
        self._logo.pack(pady=(12, 16))

        # Nav buttons
        for key, icon, tooltip in NAV_ITEMS:
            row = ctk.CTkFrame(self, fg_color="transparent", height=48)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)

            indicator = ctk.CTkFrame(
                row, width=3, fg_color="transparent", corner_radius=2,
            )
            indicator.place(x=0, rely=0.15, relheight=0.7)
            self._indicators[key] = indicator

            btn = ctk.CTkButton(
                row, text=icon, width=theme.SIDEBAR_WIDTH - 6, height=42,
                fg_color="transparent", hover_color=theme.get("BG_CARD"),
                text_color=theme.get("TEXT_MUTED"), font=("Segoe UI", 18),
                corner_radius=8,
                command=lambda k=key: self._navigate(k),
            )
            btn.pack(padx=3)
            self._buttons[key] = btn
            shortcut = _SHORTCUTS.get(key)
            tip_text = f"{tooltip}  ({shortcut})" if shortcut else tooltip
            self._tooltips[key] = Tooltip(btn, tip_text)

        self._settings_btn = ctk.CTkButton(
            self, text="\u2699", width=theme.SIDEBAR_WIDTH - 6, height=42,
            fg_color="transparent", hover_color=theme.get("BG_CARD"),
            text_color=theme.get("TEXT_MUTED"), font=("Segoe UI", 18),
            corner_radius=8, command=self._open_settings,
        )
        self._settings_btn.pack(side="bottom", padx=3, pady=(0, 8))

        self._theme_btn = ctk.CTkButton(
            self, text="\u263E", width=theme.SIDEBAR_WIDTH - 6, height=42,
            fg_color="transparent", hover_color=theme.get("BG_CARD"),
            text_color=theme.get("TEXT_MUTED"), font=("Segoe UI", 18),
            corner_radius=8,
            command=self._toggle_theme,
        )
        self._theme_btn.pack(side="bottom", padx=3, pady=(0, 12))

        theme.on_theme_change(self._apply_theme)

    def _navigate(self, key: str) -> None:
        self.set_active(key)
        self._on_navigate(key)

    def _toggle_theme(self) -> None:
        if self._on_toggle_theme:
            self._on_toggle_theme()

    def _open_settings(self) -> None:
        if self._on_open_settings:
            self._on_open_settings()

    def set_active(self, key: str) -> None:
        if self._active == key:
            return
        if self._active and self._active in self._buttons:
            self._buttons[self._active].configure(
                fg_color="transparent", text_color=theme.get("TEXT_MUTED"),
            )
            self._indicators[self._active].configure(fg_color="transparent")
        self._active = key
        if key in self._buttons:
            self._buttons[key].configure(
                fg_color=theme.get("BG_CARD"),
                text_color=theme.get("TEXT_PRIMARY"),
            )
            self._indicators[key].configure(fg_color=theme.get("ACCENT_BLUE"))

    def _apply_theme(self) -> None:
        self.configure(fg_color=theme.get("BG_SIDEBAR"))
        self._logo.configure(text_color=theme.get("ACCENT_BLUE"))
        icon = "\u2600" if theme.current_mode() == "light" else "\u263E"
        self._theme_btn.configure(
            text=icon, hover_color=theme.get("BG_CARD"),
            text_color=theme.get("TEXT_MUTED"),
        )
        self._settings_btn.configure(
            hover_color=theme.get("BG_CARD"),
            text_color=theme.get("TEXT_MUTED"),
        )
        for key, btn in self._buttons.items():
            is_active = key == self._active
            btn.configure(
                fg_color=theme.get("BG_CARD") if is_active else "transparent",
                hover_color=theme.get("BG_CARD"),
                text_color=theme.get("TEXT_PRIMARY") if is_active else theme.get("TEXT_MUTED"),
            )
            self._indicators[key].configure(
                fg_color=theme.get("ACCENT_BLUE") if is_active else "transparent",
            )

    def destroy(self):
        theme.remove_listener(self._apply_theme)
        super().destroy()
