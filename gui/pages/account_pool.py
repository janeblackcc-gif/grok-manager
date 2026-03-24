from __future__ import annotations

import json
import threading
import urllib.request

import customtkinter as ctk

from config import AppConfig
from gui import theme


class AccountPoolPage(ctk.CTkFrame):

    def __init__(self, master, config: AppConfig):
        super().__init__(master, fg_color=theme.get("BG_ROOT"))
        self._config = config
        self._stop_event = threading.Event()

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 12))
        self._header_label = ctk.CTkLabel(
            header, text="Account Pool", font=theme.font_heading(18),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._header_label.pack(side="left")
        self._refresh_btn = ctk.CTkButton(
            header, text="Refresh", width=80, height=28,
            fg_color=theme.get("ACCENT_BLUE"), hover_color=theme.get("HOVER_BLUE"),
            text_color=theme.get("TEXT_WHITE"), corner_radius=6,
            command=self._manual_refresh,
        )
        self._refresh_btn.pack(side="right")

        self._summary = ctk.CTkLabel(
            self, text="Loading...", font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"), anchor="w",
        )
        self._summary.pack(fill="x", padx=24, pady=(0, 8))

        self._table = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
        )
        self._table.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self._hdr_frame = ctk.CTkFrame(self._table, fg_color=theme.get("BG_INPUT"),
                                        corner_radius=6)
        self._hdr_frame.pack(fill="x", pady=(0, 4))
        self._hdr_labels: list[ctk.CTkLabel] = []
        for col, w in [("Token", 200), ("Status", 80), ("Quota", 80), ("Uses", 60)]:
            lbl = ctk.CTkLabel(
                self._hdr_frame, text=col, font=theme.font_small(),
                text_color=theme.get("TEXT_MUTED"), width=w, anchor="w",
            )
            lbl.pack(side="left", padx=8, pady=4)
            self._hdr_labels.append(lbl)

        self._rows_frame = ctk.CTkFrame(self._table, fg_color="transparent")
        self._rows_frame.pack(fill="both", expand=True)

        theme.on_theme_change(self._apply_theme)

    def start_polling(self) -> None:
        self._stop_event.clear()
        threading.Thread(target=self._bg_fetch, daemon=True).start()

    def stop_polling(self) -> None:
        self._stop_event.set()

    def _manual_refresh(self) -> None:
        threading.Thread(target=self._fetch_once, daemon=True).start()

    def _bg_fetch(self) -> None:
        while not self._stop_event.is_set():
            self._fetch_once()
            self._stop_event.wait(30)

    def _fetch_once(self) -> None:
        try:
            g2 = self._config.services.get("grok2api")
            if not g2 or not g2.admin_url:
                self._safe_update_summary("No grok2api service configured")
                return
            base = g2.admin_url.rsplit("/admin", 1)[0]
            url = f"{base}/v1/admin/tokens"
            req = urllib.request.Request(url, method="GET")
            app_key = g2.env.get("APP_KEY", "grok2api")
            req.add_header("Authorization", f"Bearer {app_key}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            tokens = []
            for pool_name, pool_list in data.get("tokens", {}).items():
                for t in pool_list:
                    t["_pool"] = pool_name
                    tokens.append(t)
            if self.winfo_exists():
                try:
                    self.after(0, self._render_tokens, tokens)
                except RuntimeError:
                    pass
        except urllib.error.URLError:
            self._safe_update_summary("Grok2API not running — start the service first")
        except Exception as e:
            self._safe_update_summary(f"Failed to fetch: {type(e).__name__}")

    def _safe_update_summary(self, text: str) -> None:
        if self.winfo_exists():
            try:
                self.after(0, self._summary.configure, {"text": text})
            except RuntimeError:
                pass

    def _render_tokens(self, tokens: list[dict]) -> None:
        for w in self._rows_frame.winfo_children():
            w.destroy()

        total = len(tokens)
        active = sum(1 for t in tokens if t.get("status") == "active")
        self._summary.configure(
            text=f"Total: {total}  |  Active: {active}  |  Other: {total - active}"
        )

        for t in tokens:
            row = ctk.CTkFrame(
                self._rows_frame, fg_color=theme.get("BG_CARD"),
                corner_radius=8, height=36,
            )
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)

            tok = t.get("token", "")
            masked = f"{tok[:8]}...{tok[-8:]}" if len(tok) > 20 else tok
            ctk.CTkLabel(
                row, text=masked, font=theme.font_small(),
                text_color=theme.get("TEXT_PRIMARY"), width=200, anchor="w",
            ).pack(side="left", padx=8)

            status = t.get("status", "unknown")
            fg, bg = theme.status_pill(status)
            pill = ctk.CTkFrame(row, fg_color=bg, corner_radius=6, width=70, height=22)
            pill.pack(side="left", padx=8)
            pill.pack_propagate(False)
            ctk.CTkLabel(
                pill, text=status, font=("Segoe UI", 9, "bold"),
                text_color=fg,
            ).pack(expand=True)

            quota = t.get("quota", "?")
            ctk.CTkLabel(
                row, text=str(quota), font=theme.font_small(),
                text_color=theme.get("TEXT_SECONDARY"), width=80, anchor="w",
            ).pack(side="left", padx=8)

            uses = t.get("use_count", 0)
            ctk.CTkLabel(
                row, text=str(uses), font=theme.font_small(),
                text_color=theme.get("TEXT_SECONDARY"), width=60, anchor="w",
            ).pack(side="left", padx=8)

            full_token = tok
            ctk.CTkButton(
                row, text="Copy", width=50, height=22,
                fg_color=theme.get("BG_INPUT"), hover_color=theme.get("HOVER_GENERIC"),
                text_color=theme.get("TEXT_PRIMARY"), corner_radius=4,
                font=("Segoe UI", 9),
                command=lambda t=full_token: self._copy_token(t),
            ).pack(side="right", padx=8)

    def _copy_token(self, token: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(token)
        old_text = self._summary.cget("text")
        self._summary.configure(text="Copied to clipboard!",
                                text_color=theme.get("ACCENT_GREEN"))
        self.after(1500, lambda: self._summary.configure(
            text=old_text, text_color=theme.get("TEXT_SECONDARY")))

    def _apply_theme(self) -> None:
        self.configure(fg_color=theme.get("BG_ROOT"))
        self._header_label.configure(text_color=theme.get("TEXT_PRIMARY"))
        self._refresh_btn.configure(
            fg_color=theme.get("ACCENT_BLUE"), hover_color=theme.get("HOVER_BLUE"),
        )
        self._summary.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._hdr_frame.configure(fg_color=theme.get("BG_INPUT"))
        for lbl in self._hdr_labels:
            lbl.configure(text_color=theme.get("TEXT_MUTED"))

    def destroy(self):
        theme.remove_listener(self._apply_theme)
        super().destroy()
