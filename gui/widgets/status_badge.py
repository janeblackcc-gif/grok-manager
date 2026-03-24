from __future__ import annotations

import customtkinter as ctk

from gui import theme
from service_manager import ServiceState


class StatusBadge(ctk.CTkFrame):
    """Pill-shaped status badge with semi-transparent background."""

    def __init__(self, master, state: ServiceState = ServiceState.STOPPED, **kw):
        super().__init__(master, fg_color=theme.state_bg(state),
                         corner_radius=8, height=26, **kw)
        self._label = ctk.CTkLabel(
            self, text=state.value.upper(), font=theme.font_badge(),
            text_color=theme.state_color(state),
        )
        self._label.pack(padx=10, pady=2)
        self._state = state
        theme.on_theme_change(self._apply_theme)

    def set_state(self, state: ServiceState) -> None:
        self._state = state
        self.configure(fg_color=theme.state_bg(state))
        self._label.configure(
            text=state.value.upper(),
            text_color=theme.state_color(state),
        )

    def _apply_theme(self) -> None:
        self.configure(fg_color=theme.state_bg(self._state))
        self._label.configure(text_color=theme.state_color(self._state))

    def destroy(self):
        theme.remove_listener(self._apply_theme)
        super().destroy()
