from __future__ import annotations

import customtkinter as ctk

from gui import theme


class StatTile(ctk.CTkFrame):
    """Compact statistic card: icon + value + label."""

    def __init__(self, master, icon: str, label: str, value: str = "--", **kw):
        super().__init__(
            master, fg_color=theme.get("BG_CARD"),
            corner_radius=theme.CARD_CORNER_RADIUS,
            border_width=theme.CARD_BORDER_WIDTH,
            border_color=theme.get("CARD_BORDER_COLOR"),
            **kw,
        )
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=12)

        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        self._icon_label = ctk.CTkLabel(
            top, text=icon, font=("Segoe UI", 22),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._icon_label.pack(side="left")
        self._value_label = ctk.CTkLabel(
            top, text=value, font=theme.font_heading(20),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._value_label.pack(side="right")

        self._name_label = ctk.CTkLabel(
            inner, text=label, font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"), anchor="w",
        )
        self._name_label.pack(fill="x", pady=(4, 0))

        theme.on_theme_change(self._apply_theme)

    def set_value(self, value: str) -> None:
        self._value_label.configure(text=value)

    def _apply_theme(self) -> None:
        self.configure(
            fg_color=theme.get("BG_CARD"),
            border_color=theme.get("CARD_BORDER_COLOR"),
        )
        self._icon_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._value_label.configure(text_color=theme.get("TEXT_PRIMARY"))
        self._name_label.configure(text_color=theme.get("TEXT_SECONDARY"))

    def destroy(self):
        theme.remove_listener(self._apply_theme)
        super().destroy()
