from __future__ import annotations

import customtkinter as ctk

from gui import theme


class Tooltip:

    def __init__(self, widget: ctk.CTkBaseClass, text: str, delay: int = 400) -> None:
        self._widget = widget
        self._text = text
        self._delay = delay
        self._tw: ctk.CTkToplevel | None = None
        self._job: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel, add="+")

    def _schedule(self, event=None) -> None:
        self._cancel()
        self._job = self._widget.after(self._delay, self._show)

    def _cancel(self, event=None) -> None:
        if self._job:
            self._widget.after_cancel(self._job)
            self._job = None
        self._hide()

    def _show(self) -> None:
        if not self._text:
            return
        self._tw = ctk.CTkToplevel(self._widget)
        self._tw.wm_overrideredirect(True)
        self._tw.wm_attributes("-topmost", True)
        x = self._widget.winfo_rootx() + self._widget.winfo_width() + 8
        y = self._widget.winfo_rooty()
        self._tw.wm_geometry(f"+{x}+{y}")
        lbl = ctk.CTkLabel(
            self._tw, text=self._text,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            corner_radius=6, font=theme.font_small(),
            wraplength=300,
        )
        lbl.pack(padx=6, pady=4)

    def _hide(self) -> None:
        if self._tw:
            self._tw.destroy()
            self._tw = None

    def update_text(self, text: str) -> None:
        self._text = text
