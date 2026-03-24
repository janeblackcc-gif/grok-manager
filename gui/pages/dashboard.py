from __future__ import annotations

import datetime
import json
import threading
import urllib.request
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from config import AppConfig
from gui import theme
from gui.utils.debug_bundle import export_debug_bundle
from gui.utils.run_recorder import get_run_recorder
from gui.widgets.service_card import ServiceCard
from gui.widgets.stat_tile import StatTile
from gui.widgets.status_badge import StatusBadge
from service_manager import ServiceState


class DashboardPage(ctk.CTkFrame):

    def __init__(self, master, config: AppConfig, cards_ref: dict[str, ServiceCard]):
        super().__init__(master, fg_color=theme.get("BG_ROOT"))
        self._config = config
        self._cards_ref = cards_ref
        self._token_count = "N/A"
        self._cpu_pct = "N/A"
        self._stop_event = threading.Event()

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 12))
        self._header_label = ctk.CTkLabel(
            header, text="Dashboard", font=theme.font_heading(18), text_color=theme.get("TEXT_PRIMARY")
        )
        self._header_label.pack(side="left")

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right")

        self._start_all_btn = ctk.CTkButton(
            btn_frame,
            text="Start All",
            width=90,
            height=28,
            fg_color=theme.get("ACCENT_GREEN"),
            hover_color=theme.get("HOVER_GREEN"),
            text_color=theme.get("TEXT_WHITE"),
            corner_radius=6,
            command=self._start_all,
        )
        self._start_all_btn.pack(side="left", padx=(0, 6))
        self._stop_all_btn = ctk.CTkButton(
            btn_frame,
            text="Stop All",
            width=90,
            height=28,
            fg_color=theme.get("ACCENT_RED"),
            hover_color=theme.get("HOVER_RED"),
            text_color=theme.get("TEXT_WHITE"),
            corner_radius=6,
            command=self._stop_all,
        )
        self._stop_all_btn.pack(side="left", padx=(0, 12))

        self._action_btns: list[ctk.CTkButton] = []
        g2 = config.services.get("grok2api")
        if g2 and g2.admin_url:
            button = ctk.CTkButton(
                btn_frame,
                text="Open Admin",
                width=100,
                height=28,
                fg_color=theme.get("ACCENT_BLUE"),
                hover_color=theme.get("HOVER_BLUE"),
                text_color=theme.get("TEXT_WHITE"),
                corner_radius=6,
                command=lambda: self._open_url(g2.admin_url),
            )
            button.pack(side="left", padx=(0, 6))
            self._action_btns.append(button)
        gm = config.services.get("grok_maintainer")
        if gm and gm.token_dir:
            button = ctk.CTkButton(
                btn_frame,
                text="Token Folder",
                width=100,
                height=28,
                fg_color=theme.get("BG_INPUT"),
                hover_color=theme.get("HOVER_GENERIC"),
                text_color=theme.get("TEXT_PRIMARY"),
                corner_radius=6,
                command=lambda: self._open_folder(gm.token_dir),
            )
            button.pack(side="left", padx=(0, 6))
            self._action_btns.append(button)
        gm_cwd = gm.cwd if gm else (g2.cwd if g2 else None)
        if gm_cwd:
            import os

            config_path = os.path.join(gm_cwd, "config.json")
            if not os.path.exists(config_path):
                config_path = os.path.join(gm_cwd, "config.toml")
            button = ctk.CTkButton(
                btn_frame,
                text="Config",
                width=70,
                height=28,
                fg_color=theme.get("BG_INPUT"),
                hover_color=theme.get("HOVER_GENERIC"),
                text_color=theme.get("TEXT_PRIMARY"),
                corner_radius=6,
                command=lambda p=config_path: self._open_file(p),
            )
            button.pack(side="left", padx=(0, 6))
            self._action_btns.append(button)
        self._clean_btn = ctk.CTkButton(
            btn_frame,
            text="Clean Cache",
            width=95,
            height=28,
            fg_color=theme.get("ACCENT_RED"),
            hover_color=theme.get("HOVER_RED"),
            text_color=theme.get("TEXT_WHITE"),
            corner_radius=6,
            command=self._clean_cache,
        )
        self._clean_btn.pack(side="left")
        self._debug_btn = ctk.CTkButton(
            btn_frame,
            text="Debug Bundle",
            width=110,
            height=28,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_PRIMARY"),
            corner_radius=6,
            command=self._export_debug_bundle,
        )
        self._debug_btn.pack(side="left", padx=(8, 0))

        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.pack(fill="x", padx=24, pady=(0, 16))
        tiles.columnconfigure((0, 1, 2), weight=1)

        self._tile_uptime = StatTile(tiles, icon="\u23f1", label="Uptime", value="--")
        self._tile_uptime.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._tile_tokens = StatTile(tiles, icon="\U0001f511", label="Tokens", value="N/A")
        self._tile_tokens.grid(row=0, column=1, sticky="nsew", padx=4)
        self._tile_cpu = StatTile(tiles, icon="\u26a1", label="CPU", value="N/A")
        self._tile_cpu.grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        svc_frame = ctk.CTkFrame(self, fg_color="transparent")
        svc_frame.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        self._mini_cards: dict[str, dict] = {}
        self._mini_frames: list[ctk.CTkFrame] = []
        for key, label in [("grok2api", "Grok2API"), ("grok_maintainer", "Grok-Maintainer")]:
            card = ctk.CTkFrame(
                svc_frame,
                fg_color=theme.get("BG_CARD"),
                corner_radius=theme.CARD_CORNER_RADIUS,
                border_width=theme.CARD_BORDER_WIDTH,
                border_color=theme.get("CARD_BORDER_COLOR"),
            )
            card.pack(fill="x", pady=(0, 8))
            self._mini_frames.append(card)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=16, pady=12)
            label_widget = ctk.CTkLabel(
                inner, text=label, font=theme.font_body(), text_color=theme.get("TEXT_PRIMARY")
            )
            label_widget.pack(side="left")
            badge = StatusBadge(inner, ServiceState.STOPPED)
            badge.pack(side="right")
            self._mini_cards[key] = {"badge": badge, "label": label_widget}

        self._recent_wrap = ctk.CTkFrame(
            self,
            fg_color=theme.get("BG_CARD"),
            corner_radius=theme.CARD_CORNER_RADIUS,
            border_width=theme.CARD_BORDER_WIDTH,
            border_color=theme.get("CARD_BORDER_COLOR"),
        )
        self._recent_wrap.pack(fill="x", padx=24, pady=(0, 16))
        self._recent_title = ctk.CTkLabel(
            self._recent_wrap, text="Recent Runs", font=theme.font_body(), text_color=theme.get("TEXT_PRIMARY")
        )
        self._recent_title.pack(anchor="w", padx=16, pady=(12, 8))
        self._recent_box = ctk.CTkTextbox(
            self._recent_wrap,
            height=120,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_mono(),
            corner_radius=8,
        )
        self._recent_box.pack(fill="x", padx=16, pady=(0, 12))

        theme.on_theme_change(self._apply_theme)

    def start_polling(self) -> None:
        self._stop_event.clear()
        threading.Thread(target=self._bg_poll, daemon=True).start()
        self._refresh_ui()

    def stop_polling(self) -> None:
        self._stop_event.set()

    def _bg_poll(self) -> None:
        while not self._stop_event.is_set():
            try:
                import psutil

                self._cpu_pct = f"{psutil.cpu_percent(interval=1):.0f}%"
            except Exception:
                self._cpu_pct = "N/A"
            try:
                g2 = self._config.services.get("grok2api")
                if g2 and g2.admin_url:
                    base = g2.admin_url.rsplit("/admin", 1)[0]
                    url = f"{base}/v1/admin/tokens"
                    req = urllib.request.Request(url, method="GET")
                    app_key = g2.env.get("APP_KEY", "grok2api")
                    req.add_header("Authorization", f"Bearer {app_key}")
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        data = json.loads(resp.read())
                        total = sum(len(value) for value in data.get("tokens", {}).values())
                        self._token_count = str(total)
                else:
                    self._token_count = "N/A"
            except Exception:
                self._token_count = "N/A"
            self._stop_event.wait(5)

    def _refresh_ui(self) -> None:
        if not self.winfo_exists() or self._stop_event.is_set():
            return
        max_uptime = "--"
        max_seconds = 0
        for card in self._cards_ref.values():
            start_time = card.start_time
            if start_time:
                secs = (datetime.datetime.now() - start_time).total_seconds()
                if secs > max_seconds:
                    max_seconds = secs
                    hours, rem = divmod(int(secs), 3600)
                    minutes, _ = divmod(rem, 60)
                    max_uptime = f"{hours}h {minutes}m" if hours else f"{minutes}m"
        self._tile_uptime.set_value(max_uptime)
        self._tile_tokens.set_value(self._token_count)
        self._tile_cpu.set_value(self._cpu_pct)

        for key, widgets in self._mini_cards.items():
            card = self._cards_ref.get(key)
            if card:
                widgets["badge"].set_state(card.state)

        self._recent_box.delete("1.0", "end")
        for record in get_run_recorder().load_recent(8):
            status = "OK" if record.success else "FAIL"
            detail = record.error_type or record.error_message or "-"
            line = (
                f"{record.timestamp} | {record.feature} | {record.source} | "
                f"{status} | {record.duration_ms}ms | {detail}"
            )
            self._recent_box.insert("end", line + "\n")

        self.after(1000, self._refresh_ui)

    @staticmethod
    def _open_url(url: str) -> None:
        import webbrowser

        webbrowser.open(url)

    @staticmethod
    def _open_folder(path: str) -> None:
        import os

        os.startfile(path)

    @staticmethod
    def _open_file(path: str) -> None:
        import os

        os.startfile(path)

    def _start_all(self) -> None:
        for key in ("grok2api", "grok_maintainer"):
            card = self._cards_ref.get(key)
            if card is None:
                continue
            if card.state in (ServiceState.STOPPED, ServiceState.ERROR):
                card._on_start()

    def _stop_all(self) -> None:
        for card in self._cards_ref.values():
            if card._manager is not None and card.state not in (
                ServiceState.STOPPED,
                ServiceState.ERROR,
                ServiceState.STOPPING,
            ):
                card._on_stop()

    def _clean_cache(self) -> None:
        import shutil
        import subprocess

        cleaned = 0
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "chromedriver.exe"],
                creationflags=0x08000000,
                timeout=10,
                capture_output=True,
            )
        except Exception:
            pass
        for card in self._cards_ref.values():
            cwd = card.svc_config.cwd
            if cwd:
                import os

                for root, dirs, _ in os.walk(cwd):
                    for dirname in dirs:
                        if dirname == "__pycache__":
                            try:
                                shutil.rmtree(os.path.join(root, dirname))
                                cleaned += 1
                            except Exception:
                                pass
        from tkinter import messagebox

        messagebox.showinfo("Clean Cache", f"Chromedriver processes killed.\n{cleaned} __pycache__ dirs removed.")

    def _export_debug_bundle(self) -> None:
        root_dir = Path(__file__).resolve().parent.parent.parent
        target = filedialog.asksaveasfilename(
            title="Export Debug Bundle",
            defaultextension=".zip",
            initialfile=f"grok_manager_debug_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            filetypes=[("ZIP Archive", "*.zip")],
        )
        if not target:
            return
        path = export_debug_bundle(target, config=self._config, app_root=root_dir)
        from tkinter import messagebox

        messagebox.showinfo("Debug Bundle", f"Debug bundle exported:\n{path}")

    def _apply_theme(self) -> None:
        self.configure(fg_color=theme.get("BG_ROOT"))
        self._header_label.configure(text_color=theme.get("TEXT_PRIMARY"))
        self._start_all_btn.configure(fg_color=theme.get("ACCENT_GREEN"), hover_color=theme.get("HOVER_GREEN"))
        self._stop_all_btn.configure(fg_color=theme.get("ACCENT_RED"), hover_color=theme.get("HOVER_RED"))
        self._clean_btn.configure(fg_color=theme.get("ACCENT_RED"), hover_color=theme.get("HOVER_RED"))
        self._debug_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        for button in self._action_btns:
            if button.cget("text") == "Open Admin":
                button.configure(fg_color=theme.get("ACCENT_BLUE"), hover_color=theme.get("HOVER_BLUE"))
            else:
                button.configure(
                    fg_color=theme.get("BG_INPUT"),
                    hover_color=theme.get("HOVER_GENERIC"),
                    text_color=theme.get("TEXT_PRIMARY"),
                )
        for frame in self._mini_frames:
            frame.configure(fg_color=theme.get("BG_CARD"), border_color=theme.get("CARD_BORDER_COLOR"))
        for widgets in self._mini_cards.values():
            widgets["label"].configure(text_color=theme.get("TEXT_PRIMARY"))
        self._recent_wrap.configure(fg_color=theme.get("BG_CARD"), border_color=theme.get("CARD_BORDER_COLOR"))
        self._recent_title.configure(text_color=theme.get("TEXT_PRIMARY"))
        self._recent_box.configure(fg_color=theme.get("BG_INPUT"), text_color=theme.get("TEXT_PRIMARY"))

    def destroy(self):
        theme.remove_listener(self._apply_theme)
        super().destroy()
