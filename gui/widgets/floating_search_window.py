from __future__ import annotations

import webbrowser
from urllib.parse import urlparse

import customtkinter as ctk

from gui import theme
from gui.utils.grok_search_client import GrokSearchClient
from gui.widgets.markdown_renderer import MarkdownRenderer


def _domain_icon(domain: str) -> str:
    d = domain.lower()
    if any(k in d for k in ("news", "bbc", "cnn", "reuters", "xinhua", "sina")):
        return "\U0001f4f0"
    if any(k in d for k in ("github", "stackoverflow", "dev.to", "medium", "csdn")):
        return "\U0001f4bb"
    if any(k in d for k in ("docs", "wiki", "documentation", "readthedocs")):
        return "\U0001f4da"
    if any(k in d for k in ("arxiv", "scholar", "paper", "research")):
        return "\U0001f52c"
    return "\U0001f517"


class FloatingSearchWindow(ctk.CTkToplevel):

    def __init__(self, master, query: str, x: int, y: int, on_result_saved=None):
        super().__init__(master)
        self._query = query
        self._client = GrokSearchClient()
        self._full_result = ""
        self._source_cards: list[ctk.CTkFrame] = []
        self._closed = False
        self._history_saved = False
        self._on_result_saved = on_result_saved
        self._drag_start: tuple[int, int] | None = None
        self._window_start: tuple[int, int] | None = None

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.96)
        except Exception:
            pass
        self.geometry(f"520x420+{x}+{y}")
        self.configure(fg_color=theme.get("BG_CARD"))

        self.bind("<Escape>", lambda e: self.close())

        self._build_ui()
        theme.on_theme_change(self._apply_theme)
        self.after(50, self.focus_force)
        self.after(80, self._start_search)

    def _build_ui(self) -> None:
        self._frame = ctk.CTkFrame(self, fg_color=theme.get("BG_CARD"), corner_radius=12)
        self._frame.pack(fill="both", expand=True, padx=1, pady=1)

        header = ctk.CTkFrame(self._frame, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 6))
        self._header = header

        self._title = ctk.CTkLabel(
            header,
            text="\u60ac\u6d6e\u641c\u7d22",
            font=theme.font_heading(16),
            text_color=theme.get("ACCENT_BLUE"),
        )
        self._title.pack(side="left")

        self._close_btn = ctk.CTkButton(
            header,
            text="\u00d7",
            width=28,
            height=28,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_heading(16),
            corner_radius=14,
            command=self.close,
        )
        self._close_btn.pack(side="right")

        self._bind_drag(header)
        self._bind_drag(self._title)

        self._query_label = ctk.CTkLabel(
            self._frame,
            text=self._query,
            anchor="w",
            wraplength=480,
            justify="left",
            font=theme.font_small(),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._query_label.pack(fill="x", padx=12)

        self._status = ctk.CTkLabel(
            self._frame,
            text="\u6b63\u5728\u641c\u7d22...",
            anchor="w",
            font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._status.pack(fill="x", padx=12, pady=(4, 6))

        self._result = MarkdownRenderer(self._frame, height=230)
        self._result.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self._source_frame = ctk.CTkScrollableFrame(
            self._frame, height=88, fg_color=theme.get("BG_CARD")
        )
        self._source_frame.pack(fill="x", padx=12, pady=(0, 12))

    def _bind_drag(self, widget) -> None:
        widget.bind("<ButtonPress-1>", self._on_drag_start, add="+")
        widget.bind("<B1-Motion>", self._on_drag_move, add="+")
        widget.bind("<ButtonRelease-1>", self._on_drag_end, add="+")

    def _on_drag_start(self, event) -> None:
        self._drag_start = (event.x_root, event.y_root)
        self._window_start = (self.winfo_x(), self.winfo_y())

    def _on_drag_move(self, event) -> None:
        if not self._drag_start or not self._window_start or self._closed:
            return
        dx = event.x_root - self._drag_start[0]
        dy = event.y_root - self._drag_start[1]
        self.geometry(
            f"{self.winfo_width()}x{self.winfo_height()}+{self._window_start[0] + dx}+{self._window_start[1] + dy}"
        )

    def _on_drag_end(self, _event) -> None:
        self._drag_start = None
        self._window_start = None

    def _start_search(self) -> None:
        if self._closed:
            return
        self._client.search(
            query=self._query,
            mode="detailed",
            web_enabled=True,
            history=[],
            on_chunk=lambda c: self._safe_after(self._on_chunk, c),
            on_done=lambda r: self._safe_after(self._on_done, r),
            on_error=lambda e: self._safe_after(self._on_error, e),
        )

    def _safe_after(self, func, *args) -> None:
        try:
            if not self._closed and self.winfo_exists():
                self.after(0, func, *args)
        except RuntimeError:
            pass

    def _on_chunk(self, content: str) -> None:
        self._full_result += content
        self._result.append_chunk(content)

    def _on_done(self, full_reply: str) -> None:
        self._result.flush_stream()
        self._status.configure(text="")
        if full_reply:
            self._full_result = full_reply
        self._show_sources()
        if (
            not self._history_saved
            and self._on_result_saved
            and self._full_result.strip()
        ):
            self._history_saved = True
            try:
                self._on_result_saved(self._query, self._full_result)
            except Exception:
                self._history_saved = False

    def _on_error(self, msg: str) -> None:
        self._result.flush_stream()
        self._status.configure(text=f"\u26a0 {msg}", text_color=theme.get("ACCENT_RED"))

    def _clear_sources(self) -> None:
        for card in self._source_cards:
            card.destroy()
        self._source_cards.clear()

    def _show_sources(self) -> None:
        self._clear_sources()
        urls = self._result.get_urls()
        for url in urls:
            try:
                parsed = urlparse(url)
                display = parsed.netloc + parsed.path
                if len(display) > 54:
                    display = display[:51] + "..."
                icon = _domain_icon(parsed.netloc)
            except Exception:
                display = url[:54]
                icon = "\U0001f517"
            card = ctk.CTkFrame(
                self._source_frame,
                fg_color=theme.get("BG_INPUT"),
                corner_radius=6,
                height=28,
            )
            card.pack(fill="x", pady=2)
            card.pack_propagate(False)
            label = ctk.CTkLabel(
                card,
                text=f"{icon} {display}",
                anchor="w",
                cursor="hand2",
                font=theme.font_small(),
                text_color=theme.get("ACCENT_BLUE"),
            )
            label.pack(fill="x", padx=10, pady=4)
            label.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
            self._source_cards.append(card)

    def _apply_theme(self) -> None:
        self.configure(fg_color=theme.get("BG_CARD"))
        self._frame.configure(fg_color=theme.get("BG_CARD"))
        self._title.configure(text_color=theme.get("ACCENT_BLUE"))
        self._close_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._query_label.configure(text_color=theme.get("TEXT_PRIMARY"))
        self._status.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._source_frame.configure(fg_color=theme.get("BG_CARD"))
        for card in self._source_cards:
            card.configure(fg_color=theme.get("BG_INPUT"))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._client.cancel()
        theme.remove_listener(self._apply_theme)
        try:
            self.destroy()
        except Exception:
            pass
