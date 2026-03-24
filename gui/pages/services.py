from __future__ import annotations

import customtkinter as ctk

from config import AppConfig
from gui import theme
from gui.widgets.service_card import ServiceCard


class ServicesPage(ctk.CTkFrame):

    def __init__(self, master, config: AppConfig):
        super().__init__(master, fg_color=theme.get("BG_ROOT"))
        self._cards: dict[str, ServiceCard] = {}

        self._title_label = ctk.CTkLabel(
            self, text="Service Management", font=theme.font_heading(18),
            text_color=theme.get("TEXT_PRIMARY"), anchor="w",
        )
        self._title_label.pack(fill="x", padx=24, pady=(20, 12))

        container = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
        )
        container.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        g2 = config.services.get("grok2api")
        if g2:
            card = ServiceCard(container, g2, config.ui, show_count=False)
            card.pack(fill="x", pady=(0, 12))
            self._cards["grok2api"] = card

        gm = config.services.get("grok_maintainer")
        if gm:
            card = ServiceCard(container, gm, config.ui, show_count=True)
            card.pack(fill="x", pady=(0, 12))
            self._cards["grok_maintainer"] = card

        theme.on_theme_change(self._apply_theme)

    @property
    def cards(self) -> dict[str, ServiceCard]:
        return self._cards

    def _apply_theme(self) -> None:
        self.configure(fg_color=theme.get("BG_ROOT"))
        self._title_label.configure(text_color=theme.get("TEXT_PRIMARY"))

    def destroy(self):
        theme.remove_listener(self._apply_theme)
        super().destroy()
