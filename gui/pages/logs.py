from __future__ import annotations

import datetime
from pathlib import Path

import customtkinter as ctk

from gui.theme import (
    BG_INPUT, BG_LOG, BG_ROOT,
    TEXT_LOG, TEXT_PRIMARY, TEXT_SECONDARY,
    font_heading, font_mono, font_small,
)
from gui.widgets.service_card import ServiceCard

APP_DIR = Path(__file__).resolve().parent.parent.parent


class LogsPage(ctk.CTkFrame):

    def __init__(self, master, cards_ref: dict[str, ServiceCard]):
        super().__init__(master, fg_color=BG_ROOT)
        self._cards_ref = cards_ref
        self._active_key: str | None = None

        ctk.CTkLabel(
            self, text="Detailed Logs", font=font_heading(18),
            text_color=TEXT_PRIMARY, anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 12))

        # Service selector
        svc_names = list(cards_ref.keys())
        if svc_names:
            self._seg = ctk.CTkSegmentedButton(
                self, values=svc_names, command=self._switch_service,
                font=font_small(), corner_radius=8,
            )
            self._seg.pack(padx=24, pady=(0, 8), anchor="w")
            self._seg.set(svc_names[0])
            self._active_key = svc_names[0]

        # Search row
        search = ctk.CTkFrame(self, fg_color="transparent")
        search.pack(fill="x", padx=24, pady=(0, 8))
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._do_search())
        ctk.CTkEntry(
            search, textvariable=self._search_var,
            placeholder_text="Search logs...", height=28,
            fg_color=BG_INPUT, border_width=0, corner_radius=6,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._match_label = ctk.CTkLabel(
            search, text="", width=70, font=font_small(),
            text_color=TEXT_SECONDARY,
        )
        self._match_label.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            search, text="Export", width=70, height=28,
            fg_color=BG_INPUT, hover_color="#3A3C42",
            text_color=TEXT_PRIMARY, corner_radius=6,
            command=self._export,
        ).pack(side="right")

        # Log textbox
        self._log_box = ctk.CTkTextbox(
            self, font=font_mono(), fg_color=BG_LOG,
            text_color=TEXT_LOG, state="disabled", wrap="word",
            corner_radius=8,
        )
        self._log_box.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        self._refresh_id: str | None = None
        self._stopped = False
        self._start_refresh()

    def _switch_service(self, key: str) -> None:
        self._active_key = key
        self._reload_log()

    def stop(self) -> None:
        self._stopped = True
        if self._refresh_id:
            try:
                self.after_cancel(self._refresh_id)
            except Exception:
                pass
            self._refresh_id = None

    def _reload_log(self) -> None:
        card = self._cards_ref.get(self._active_key or "")
        lines = card._log_lines if card else []
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        if lines:
            self._log_box.insert("end", "\n".join(lines[-2000:]) + "\n")
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    def _start_refresh(self) -> None:
        self._tick()

    def _tick(self) -> None:
        if not self.winfo_exists() or self._stopped:
            return
        card = self._cards_ref.get(self._active_key or "")
        if card and card._log_lines:
            self._log_box.configure(state="normal")
            current = int(self._log_box.index("end-1c").split(".")[0]) - 1
            total = len(card._log_lines)
            if total > current:
                new_lines = card._log_lines[current:]
                self._log_box.insert("end", "\n".join(new_lines) + "\n")
            self._log_box.configure(state="disabled")
            self._log_box.see("end")
        self._refresh_id = self.after(500, self._tick)

    def _do_search(self) -> None:
        keyword = self._search_var.get().strip()
        tb = self._log_box
        tb.configure(state="normal")
        tb.tag_remove("highlight", "1.0", "end")
        if not keyword:
            self._match_label.configure(text="")
            tb.configure(state="disabled")
            return
        count = 0
        start = "1.0"
        while True:
            pos = tb.search(keyword, start, stopindex="end", nocase=True)
            if not pos:
                break
            end_pos = f"{pos}+{len(keyword)}c"
            tb.tag_add("highlight", pos, end_pos)
            start = end_pos
            count += 1
        tb.tag_config("highlight", background="#FCC419", foreground="#1A1B1E")
        self._match_label.configure(text=f"{count} matches")
        tb.configure(state="disabled")

    def _export(self) -> None:
        card = self._cards_ref.get(self._active_key or "")
        if not card or not card._log_lines:
            return
        logs_dir = APP_DIR / "logs"
        logs_dir.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = (self._active_key or "unknown").replace(" ", "_")
        path = logs_dir / f"{name}_{ts}.log"
        path.write_text("\n".join(card._log_lines), encoding="utf-8")
        from tkinter import messagebox
        messagebox.showinfo("Export", f"Log exported to:\n{path}")
