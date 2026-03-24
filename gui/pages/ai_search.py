from __future__ import annotations

import logging
import re
import webbrowser
from pathlib import Path
from tkinter import filedialog
from urllib.parse import urlparse

import customtkinter as ctk

from gui import theme
from gui.utils.grok_search_client import GrokSearchClient
from gui.utils.prompt_enhancer_client import PromptEnhancerClient
from gui.utils.search_history import Session, SessionStore
from gui.utils.task_registry import get_task_registry
from gui.widgets.markdown_renderer import MarkdownRenderer
from gui.widgets.prompt_enhance_dialog import PromptEnhanceDialog
from gui.widgets.tooltip import Tooltip

logger = logging.getLogger(__name__)

_MODE_LABELS = ["简练", "详细", "专家报告"]
_MODE_KEYS = ["concise", "detailed", "expert"]
_STATUS_PHASES = [
    "正在连接 Grok...",
    "正在检索信息...",
    "正在汇总答案...",
]

_PLACEHOLDER = "输入你的问题，按 Enter 搜索，Shift+Enter 换行..."

_QUICK_TAGS = ["今日新闻", "技术趋势", "AI 最新进展", "Python 教程", "科学发现"]


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


class AISearchPage(ctk.CTkFrame):

    def __init__(self, master, config=None):
        super().__init__(master, fg_color=theme.get("BG_ROOT"))

        self._config = config
        self._client = GrokSearchClient()
        self._store = SessionStore()
        self._current_session: Session | None = None
        self._searching = False
        self._full_result = ""
        self._status_phase = 0
        self._status_job = None
        self._has_result = False
        self._placeholder_active = True
        self._enhancing = False
        self._enhancer = PromptEnhancerClient()
        self._pending_query = ""
        self._latest_result_text = ""
        self._external_status_job = None
        self._enhance_original_text = ""
        self._enhance_candidate = ""
        self._enhance_dialog: PromptEnhanceDialog | None = None
        self._active_task_id = ""

        self._build_ui()
        theme.on_theme_change(self._apply_theme)
        if self._config:
            self._apply_default_settings()

    def _build_ui(self) -> None:
        # ── Left: session panel ──
        self._session_panel = ctk.CTkFrame(
            self, width=252, fg_color=theme.get("BG_CARD"), corner_radius=0,
        )
        self._session_panel.pack(side="left", fill="y")
        self._session_panel.pack_propagate(False)

        # New session button at top
        self._new_btn = ctk.CTkButton(
            self._session_panel, text="\u2795 新对话", height=36,
            fg_color=theme.get("ACCENT_BLUE"),
            hover_color=theme.get("HOVER_BLUE"),
            text_color=theme.get("TEXT_WHITE"),
            font=theme.font_body(),
            corner_radius=8,
            command=self._new_session,
        )
        self._new_btn.pack(fill="x", padx=12, pady=(12, 8))

        self._session_scroll = ctk.CTkScrollableFrame(
            self._session_panel, fg_color=theme.get("BG_CARD"),
        )
        self._session_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._current_section_label = ctk.CTkLabel(
            self._session_scroll, text="当前对话",
            anchor="w", font=theme.font_small(), text_color=theme.get("TEXT_MUTED"),
        )
        self._current_sessions_box = ctk.CTkFrame(self._session_scroll, fg_color="transparent")
        self._history_section_label = ctk.CTkLabel(
            self._session_scroll, text="历史记录",
            anchor="w", font=theme.font_small(), text_color=theme.get("TEXT_MUTED"),
        )
        self._history_sessions_box = ctk.CTkFrame(self._session_scroll, fg_color="transparent")
        self._history_empty_label: ctk.CTkLabel | None = None
        self._session_buttons: list[ctk.CTkFrame] = []
        self._session_tooltips: list[Tooltip] = []

        clear_btn = ctk.CTkButton(
            self._session_panel, text="清空全部", height=28,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(),
            corner_radius=6,
            command=self._clear_all,
        )
        clear_btn.pack(pady=(0, 12), padx=16)
        self._clear_btn = clear_btn

        # ── Right: main content ──
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(side="right", fill="both", expand=True)
        self._main = main

        self._center_wrapper = ctk.CTkFrame(main, fg_color="transparent")
        self._center_wrapper.pack(fill="both", expand=True)

        self._spacer_top = ctk.CTkFrame(self._center_wrapper, fg_color="transparent")
        self._spacer_top.pack(fill="both", expand=True)

        # Logo area
        self._logo_frame = ctk.CTkFrame(self._center_wrapper, fg_color="transparent")
        self._logo_frame.pack(fill="x", padx=48)
        self._logo_label = ctk.CTkLabel(
            self._logo_frame, text="Grok Search",
            font=ctk.CTkFont(family="Segoe UI", size=32, weight="bold"),
            text_color=theme.get("ACCENT_BLUE"),
        )
        self._logo_label.pack(pady=(0, 2))
        self._logo_sub = ctk.CTkLabel(
            self._logo_frame, text="AI 驱动的智能搜索引擎",
            font=theme.font_body(),
            text_color=theme.get("TEXT_MUTED"),
        )
        self._logo_sub.pack(pady=(0, 16))

        # Search area
        search_area = ctk.CTkFrame(self._center_wrapper, fg_color="transparent")
        search_area.pack(fill="x", padx=48)
        self._search_area = search_area

        # Controls row
        controls = ctk.CTkFrame(search_area, fg_color="transparent", height=40)
        controls.pack(fill="x", pady=(0, 8))
        controls.pack_propagate(False)

        self._web_var = ctk.BooleanVar(value=True)
        self._web_switch = ctk.CTkSwitch(
            controls, text="\U0001f310 实时联网",
            variable=self._web_var,
            font=theme.font_body(),
            text_color=theme.get("TEXT_PRIMARY"),
            progress_color=theme.get("ACCENT_BLUE"),
        )
        self._web_switch.pack(side="left")

        self._mode_var = ctk.StringVar(value="详细")
        self._mode_menu = ctk.CTkOptionMenu(
            controls, values=_MODE_LABELS,
            variable=self._mode_var,
            font=theme.font_body(),
            fg_color=theme.get("BG_INPUT"),
            button_color=theme.get("BG_INPUT"),
            button_hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_PRIMARY"),
            dropdown_fg_color=theme.get("BG_CARD"),
            dropdown_text_color=theme.get("TEXT_PRIMARY"),
            dropdown_hover_color=theme.get("HOVER_GENERIC"),
            width=130, height=32, corner_radius=6,
        )
        self._mode_menu.pack(side="right")

        mode_label = ctk.CTkLabel(
            controls, text="搜索模式：",
            font=theme.font_body(),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        mode_label.pack(side="right", padx=(0, 6))
        self._mode_label = mode_label

        # Input row
        input_frame = ctk.CTkFrame(search_area, fg_color="transparent")
        input_frame.pack(fill="x", pady=(0, 4))

        self._input = ctk.CTkTextbox(
            input_frame, height=72,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_MUTED"),
            font=theme.font_body(), corner_radius=8,
        )
        self._input.pack(side="left", fill="x", expand=True)
        self._input.insert("1.0", _PLACEHOLDER)
        self._input.bind("<Return>", self._on_enter)
        self._input.bind("<Shift-Return>", self._on_shift_enter)
        self._input.bind("<FocusIn>", self._on_focus_in)
        self._input.bind("<FocusOut>", self._on_focus_out)

        self._enhance_btn = ctk.CTkButton(
            input_frame, text="\u2728 \u6da6\u8272", width=72, height=72,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=8,
            command=self._do_enhance_prompt,
        )
        self._enhance_btn.pack(side="right", padx=(8, 0))

        self._send_btn = ctk.CTkButton(
            input_frame, text="搜索", width=64, height=72,
            fg_color=theme.get("ACCENT_BLUE"),
            hover_color=theme.get("HOVER_BLUE"),
            text_color=theme.get("TEXT_WHITE"),
            font=theme.font_body(), corner_radius=8,
            command=self._do_search,
        )
        self._send_btn.pack(side="right", padx=(8, 0))

        self._stop_btn = ctk.CTkButton(
            input_frame, text="停止", width=64, height=72,
            fg_color=theme.get("ACCENT_RED"),
            hover_color=theme.get("HOVER_RED"),
            text_color=theme.get("TEXT_WHITE"),
            font=theme.font_body(), corner_radius=8,
            command=self._do_cancel,
        )

        # Status
        self._status_label = ctk.CTkLabel(
            search_area, text="", font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"), anchor="w",
        )
        self._status_label.pack(fill="x", pady=(0, 4))

        # Quick tags (center layout only)
        self._tags_frame = ctk.CTkFrame(search_area, fg_color="transparent")
        self._tags_frame.pack(fill="x", pady=(8, 0))
        self._tag_buttons: list[ctk.CTkButton] = []
        for tag_text in _QUICK_TAGS:
            tag_btn = ctk.CTkButton(
                self._tags_frame, text=tag_text, height=28,
                fg_color=theme.get("BG_INPUT"),
                hover_color=theme.get("HOVER_GENERIC"),
                text_color=theme.get("TEXT_SECONDARY"),
                font=theme.font_small(), corner_radius=14, width=0,
                command=lambda t=tag_text: self._quick_search(t),
            )
            tag_btn.pack(side="left", padx=4)
            self._tag_buttons.append(tag_btn)

        # Shortcut hint
        self._shortcut_hint = ctk.CTkLabel(
            search_area, text="Ctrl+K 快速聚焦 \u00b7 Alt+S 全局唤起",
            font=theme.font_small(),
            text_color=theme.get("TEXT_MUTED"), anchor="e",
        )
        self._shortcut_hint.pack(fill="x", pady=(4, 0))
        self._shortcut_hint.configure(
            text="Ctrl+K \u5feb\u901f\u805a\u7126 \u00b7 Alt+S \u5168\u5c40\u5524\u8d77 \u00b7 Alt+Q \u60ac\u6d6e\u641c\u7d22"
        )

        self._hotkey_warn: ctk.CTkLabel | None = None

        self._spacer_bottom = ctk.CTkFrame(self._center_wrapper, fg_color="transparent")
        self._spacer_bottom.pack(fill="both", expand=True)

        # Result toolbar
        self._result_toolbar = ctk.CTkFrame(self._center_wrapper, fg_color="transparent", height=32)
        self._copy_btn = ctk.CTkButton(
            self._result_toolbar, text="\U0001f4cb 复制全文", height=28, width=100,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=self._copy_result,
        )
        self._copy_btn.pack(side="right", padx=8)
        self._export_json_btn = ctk.CTkButton(
            self._result_toolbar, text="导出 JSON", height=28, width=90,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=lambda: self._export_session("json"),
        )
        self._export_json_btn.pack(side="right", padx=8)
        self._export_md_btn = ctk.CTkButton(
            self._result_toolbar, text="导出 Markdown", height=28, width=116,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=lambda: self._export_session("md"),
        )
        self._export_md_btn.pack(side="right", padx=8)

        self._turn_label = ctk.CTkLabel(
            self._result_toolbar, text="",
            font=theme.font_small(),
            text_color=theme.get("TEXT_MUTED"),
        )
        self._turn_label.pack(side="left", padx=8)
        self._turn_jump_var = ctk.StringVar(value="")
        self._turn_jump_menu = ctk.CTkOptionMenu(
            self._result_toolbar,
            values=["第 1 轮"],
            variable=self._turn_jump_var,
            width=108,
            height=28,
            fg_color=theme.get("BG_INPUT"),
            button_color=theme.get("BG_INPUT"),
            button_hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            dropdown_fg_color=theme.get("BG_CARD"),
            dropdown_text_color=theme.get("TEXT_PRIMARY"),
            dropdown_hover_color=theme.get("HOVER_GENERIC"),
            font=theme.font_small(),
            corner_radius=6,
            command=self._on_turn_selected,
        )

        # Result area
        self._result_region = ctk.CTkFrame(self._center_wrapper, fg_color="transparent")
        self._result = MarkdownRenderer(self._result_region)
        self._result.pack(side="left", fill="both", expand=True)
        self._turn_marks: list[str] = []
        self._active_turn_index = 0
        self._result_visible = False

        # Source cards
        self._source_frame = ctk.CTkScrollableFrame(
            self._center_wrapper, height=0, fg_color=theme.get("BG_ROOT"),
        )
        self._source_cards: list[ctk.CTkFrame] = []

        self._refresh_sessions()

    # ── Placeholder ──

    def _on_focus_in(self, event=None) -> None:
        if self._placeholder_active:
            self._input.delete("1.0", "end")
            self._input.configure(text_color=theme.get("TEXT_PRIMARY"))
            self._placeholder_active = False

    def _on_focus_out(self, event=None) -> None:
        content = self._input.get("1.0", "end").strip()
        if not content:
            self._placeholder_active = True
            self._input.insert("1.0", _PLACEHOLDER)
            self._input.configure(text_color=theme.get("TEXT_MUTED"))

    # ── Input events ──

    def _on_enter(self, event) -> str | None:
        if not (event.state & 0x1):
            self._do_search()
            return "break"
        return None

    def _on_shift_enter(self, event) -> None:
        return

    def _get_mode_key(self) -> str:
        label = self._mode_var.get()
        idx = _MODE_LABELS.index(label) if label in _MODE_LABELS else 1
        return _MODE_KEYS[idx]

    def _apply_default_settings(self) -> None:
        default_mode = getattr(self._config.ui, "default_search_mode", "detailed")
        if default_mode in _MODE_KEYS:
            self._mode_var.set(_MODE_LABELS[_MODE_KEYS.index(default_mode)])
        self._web_var.set(bool(getattr(self._config.ui, "default_web_enabled", True)))
        self.refresh_shortcut_hint(
            getattr(self._config.ui, "global_search_hotkey", "alt+s"),
            getattr(self._config.ui, "floating_search_hotkey", "alt+q"),
        )

    def refresh_shortcut_hint(self, global_hotkey: str, floating_hotkey: str) -> None:
        self._shortcut_hint.configure(
            text=f"Ctrl+K 快速聚焦 · {global_hotkey.upper()} 全局唤起 · {floating_hotkey.upper()} 悬浮搜索"
        )

    # ── Layout transition ──

    def _switch_to_result_layout(self) -> None:
        if self._has_result:
            return
        self._has_result = True
        self._spacer_top.pack_forget()
        self._spacer_bottom.pack_forget()
        self._logo_frame.pack_forget()
        self._tags_frame.pack_forget()
        self._shortcut_hint.pack_forget()
        if self._hotkey_warn:
            self._hotkey_warn.pack_forget()
        self._search_area.pack_configure(pady=(16, 0))
        self._result_toolbar.pack(fill="x", padx=48, pady=(4, 0))
        if not self._result_visible:
            self._result_region.pack(fill="both", expand=True, padx=48, pady=(0, 8))
            self._result_visible = True

    def _switch_to_center_layout(self) -> None:
        if not self._has_result:
            return
        self._has_result = False
        self._result_toolbar.pack_forget()
        self._result_region.pack_forget()
        self._result_visible = False
        self._source_frame.pack_forget()
        self._search_area.pack_forget()
        self._logo_frame.pack_forget()
        self._spacer_top.pack(in_=self._center_wrapper, fill="both", expand=True)
        self._logo_frame.pack(in_=self._center_wrapper, fill="x", padx=48)
        self._search_area.pack(in_=self._center_wrapper, fill="x", padx=48)
        self._tags_frame.pack(in_=self._search_area, fill="x", pady=(8, 0))
        self._shortcut_hint.pack(in_=self._search_area, fill="x", pady=(4, 0))
        if self._hotkey_warn:
            self._hotkey_warn.pack(in_=self._search_area, fill="x", pady=(2, 0))
        self._spacer_bottom.pack(in_=self._center_wrapper, fill="both", expand=True)

    # ── Search flow ──

    def _do_search(self) -> None:
        if self._placeholder_active:
            return
        query = self._input.get("1.0", "end").strip()
        if not query or self._searching:
            return
        self._searching = True
        self._active_task_id = get_task_registry().start_task(
            label="AI Search",
            feature="search",
            source="manual",
            cancel=self._do_cancel,
        )
        self._pending_query = query
        self._full_result = ""
        self._latest_result_text = ""
        self._input.configure(state="disabled")
        self._enhance_btn.configure(state="disabled")
        self._send_btn.pack_forget()
        self._stop_btn.pack(side="right", padx=(8, 0))
        self._clear_sources()
        self._switch_to_result_layout()
        self._start_status_animation()

        # Auto-create session if none active
        if not self._current_session:
            mode = self._get_mode_key()
            web = self._web_var.get()
            self._current_session = self._store.create_session(
                mode,
                web,
                feature="search",
                model=self._client.model_name,
                tags=["safe"],
            )
            self._refresh_sessions()

        session = self._current_session
        history = [m for m in session.messages if m.get("role") in ("user", "assistant")]
        self._render_session_history(session, pending_user=query)

        self._client.search(
            query=query,
            mode=session.mode,
            web_enabled=session.web_enabled,
            history=history,
            source="manual",
            feature="search",
            on_chunk=lambda c: self._safe_after(self._on_chunk, c),
            on_done=lambda r: self._safe_after(self._on_done, query, r),
            on_error=lambda e: self._safe_after(self._on_error, e),
        )

    def _do_cancel(self) -> None:
        self._client.cancel()
        self._result.flush_stream()
        self._finish_search()
        self._pending_query = ""
        self._render_current_session()
        self._full_result = ""
        if not self._full_result:
            self._switch_to_center_layout()
        self._status_label.configure(
            text="已取消", text_color=theme.get("TEXT_SECONDARY"),
        )

        if self._active_task_id:
            get_task_registry().finish_task(self._active_task_id, status="cancelled", message="已取消")
            self._active_task_id = ""

    def _safe_after(self, func, *args) -> None:
        try:
            if self.winfo_exists():
                self.after(0, func, *args)
        except RuntimeError:
            pass

    def _on_chunk(self, content: str) -> None:
        self._full_result += content
        self._result.append_chunk(content)
        if self._active_task_id:
            get_task_registry().update_task(self._active_task_id, "正在接收回答")
        if self._status_phase < 2:
            self._status_phase = 2
            self._status_label.configure(text=_STATUS_PHASES[2])

    def _on_done(self, query: str, full_reply: str) -> None:
        self._result.flush_stream()
        self._finish_search()
        self._status_label.configure(text="")
        final_reply = full_reply or self._full_result
        self._pending_query = ""
        self._latest_result_text = final_reply
        if self._active_task_id:
            get_task_registry().finish_task(self._active_task_id, status="success", message="完成")
            self._active_task_id = ""

        if self._current_session and final_reply:
            self._current_session.add_turn(query, final_reply)
            self._current_session.model = self._client.model_name
            self._current_session.feature = "search"
            self._store.update_session(self._current_session)
            self._refresh_sessions()
            self._render_current_session()
            self._update_turn_label()
            self._show_sources_from_text(final_reply)
            if self._current_session.turn_count > 0:
                self._jump_to_turn(self._current_session.turn_count)
        elif not self._full_result:
            self._render_current_session()
            self._switch_to_center_layout()

        # Clear input for next turn
        self._input.delete("1.0", "end")
        self._placeholder_active = False

    def _on_error(self, msg: str) -> None:
        self._result.flush_stream()
        self._finish_search()
        self._pending_query = ""
        self._render_current_session()
        self._full_result = ""
        if not self._full_result:
            self._switch_to_center_layout()
        self._status_label.configure(
            text=f"\u26a0 {msg}", text_color=theme.get("ACCENT_RED"),
        )
        if self._active_task_id:
            get_task_registry().finish_task(self._active_task_id, status="error", message=msg)
            self._active_task_id = ""

    def _finish_search(self) -> None:
        self._stop_status_animation()
        self._searching = False
        self._input.configure(state="normal")
        self._enhance_btn.configure(
            state="disabled" if self._enhancing else "normal"
        )
        self._stop_btn.pack_forget()
        self._send_btn.pack(side="right", padx=(8, 0))

    # ── Status animation ──

    def _start_status_animation(self) -> None:
        self._status_phase = 0
        self._status_label.configure(
            text=_STATUS_PHASES[0], text_color=theme.get("TEXT_SECONDARY"),
        )
        self._animate_status()

    def _animate_status(self) -> None:
        if not self._searching:
            return
        current = self._status_label.cget("text")
        base = current.rstrip(".")
        dots = len(current) - len(base)
        next_dots = (dots % 3) + 1
        self._status_label.configure(text=base + "." * next_dots)
        if self._status_phase < 1 and not self._full_result:
            self._status_phase = 1
            self._status_label.configure(text=_STATUS_PHASES[1])
        self._status_job = self.after(500, self._animate_status)

    def _stop_status_animation(self) -> None:
        if self._status_job:
            self.after_cancel(self._status_job)
            self._status_job = None

    # ── Session panel ──

    @staticmethod
    def _format_session_time(session: Session) -> str:
        stamp = session.updated_at or session.created_at or ""
        if "T" in stamp:
            time_part = stamp.split("T", 1)[1]
            return time_part[:5]
        return stamp[:5] if stamp else "--:--"

    @staticmethod
    def _source_label(session: Session) -> str:
        if session.source == "manual":
            return "手动"
        if session.source == "floating":
            return "划词"
        return session.source or "其他"

    @staticmethod
    def _truncate_session_title(text: str, line_len: int = 16, max_lines: int = 2) -> str:
        clean = (text or "").strip()
        if not clean:
            return "新对话"
        chunks: list[str] = []
        while clean:
            chunks.append(clean[:line_len])
            clean = clean[line_len:]
        if len(chunks) <= max_lines:
            return "\n".join(chunks)
        visible = chunks[:max_lines]
        visible[-1] = visible[-1][:-1] + "…"
        return "\n".join(visible)

    @staticmethod
    def _bind_session_click(widget, callback) -> None:
        widget.bind("<Button-1>", lambda _e: callback(), add="+")

    def _build_session_card(self, parent, session: Session, *, current: bool) -> ctk.CTkFrame:
        active_bg = theme.get("ACCENT_BLUE") if current else theme.get("BG_INPUT")
        active_text = theme.get("TEXT_WHITE") if current else theme.get("TEXT_PRIMARY")
        meta_text = theme.get("TEXT_WHITE") if current else theme.get("TEXT_SECONDARY")
        border = theme.get("ACCENT_BLUE") if current else theme.get("CARD_BORDER_COLOR")
        card = ctk.CTkFrame(
            parent,
            fg_color=active_bg,
            border_width=1,
            border_color=border,
            corner_radius=10,
        )
        title_text = self._truncate_session_title(session.display_title)
        title = ctk.CTkLabel(
            card,
            text=title_text,
            anchor="w",
            justify="left",
            wraplength=196,
            font=theme.font_small(),
            text_color=active_text,
        )
        title.pack(fill="x", padx=10, pady=(8, 4))
        meta = ctk.CTkLabel(
            card,
            text=f"{session.turn_count}轮 · {self._format_session_time(session)} · {self._source_label(session)}",
            anchor="w",
            justify="left",
            font=theme.font_small(10),
            text_color=meta_text,
        )
        meta.pack(fill="x", padx=10, pady=(0, 8))
        callback = lambda sid=session.id: self._switch_session(sid)
        for widget in (card, title, meta):
            self._bind_session_click(widget, callback)
        full_title = session.first_query or session.display_title
        if len(full_title) > 30:
            self._session_tooltips.append(Tooltip(title, full_title))
        return card

    def _refresh_sessions(self) -> None:
        for btn in self._session_buttons:
            btn.destroy()
        self._session_buttons.clear()
        self._session_tooltips.clear()
        for child in self._current_sessions_box.winfo_children():
            child.destroy()
        for child in self._history_sessions_box.winfo_children():
            child.destroy()

        current_session = None
        sessions = self._store.get_all()
        history_sessions: list[Session] = []
        for session in sessions:
            if self._current_session and session.id == self._current_session.id:
                current_session = session
            else:
                history_sessions.append(session)

        self._current_section_label.pack_forget()
        self._current_sessions_box.pack_forget()
        self._history_section_label.pack_forget()
        self._history_sessions_box.pack_forget()

        if current_session:
            self._current_section_label.pack(fill="x", padx=4, pady=(4, 6))
            self._current_sessions_box.pack(fill="x", pady=(0, 10))
            card = self._build_session_card(self._current_sessions_box, current_session, current=True)
            card.pack(fill="x", pady=(0, 2))
            self._session_buttons.append(card)

        self._history_section_label.pack(fill="x", padx=4, pady=(0, 6))
        self._history_sessions_box.pack(fill="x", pady=(0, 2))
        if history_sessions:
            for session in history_sessions:
                card = self._build_session_card(self._history_sessions_box, session, current=False)
                card.pack(fill="x", pady=(0, 6))
                self._session_buttons.append(card)
        else:
            self._history_empty_label = ctk.CTkLabel(
                self._history_sessions_box,
                text="还没有历史记录",
                anchor="center",
                justify="center",
                wraplength=208,
                font=theme.font_small(),
                text_color=theme.get("TEXT_MUTED"),
            )
            self._history_empty_label.pack(fill="x", padx=6, pady=(8, 12))

    def _switch_session(self, session_id: str) -> None:
        if self._searching:
            return
        session = self._store.get_session(session_id)
        if not session:
            return
        self._current_session = session
        self._web_var.set(session.web_enabled)
        idx = _MODE_KEYS.index(session.mode) if session.mode in _MODE_KEYS else 1
        self._mode_var.set(_MODE_LABELS[idx])
        self._refresh_sessions()

        if session.messages:
            self._switch_to_result_layout()
            self._render_current_session()
            self._update_turn_label()
            self._show_sources_from_text(session.last_result)
        else:
            self._switch_to_center_layout()

        self._input.configure(state="normal")
        self._on_focus_in()
        self._input.delete("1.0", "end")

    def _render_current_session(self) -> None:
        self._render_session_history(self._current_session, pending_user=self._pending_query)
        if self._current_session and self._current_session.messages and not self._pending_query:
            self._show_sources_from_text(self._current_session.last_result)
        elif not self._pending_query:
            self._clear_sources()

    def _render_session_history(self, session: Session | None, pending_user: str = "") -> None:
        self._result.clear()
        self._full_result = ""
        self._latest_result_text = ""
        self._turn_marks = []
        if not session:
            self._refresh_turn_rail(0)
            return
        turn_count = 0
        textbox = self._result._textbox
        for msg in session.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                turn_count += 1
                mark_name = f"turn_{turn_count}"
                textbox.mark_set(mark_name, textbox.index("end-1c"))
                textbox.mark_gravity(mark_name, "left")
                self._turn_marks.append(mark_name)
                self._result.configure(state="normal")
                textbox.insert("end", f"\U0001f464 {content}\n\n", "heading3")
                self._result.configure(state="disabled")
            elif role == "assistant":
                self._result.render_append(content)
                self._result.configure(state="normal")
                textbox.insert("end", "\n\u2500" * 40 + "\n\n")
                self._result.configure(state="disabled")
                self._latest_result_text = content
        if pending_user:
            turn_count += 1
            mark_name = f"turn_{turn_count}"
            textbox.mark_set(mark_name, textbox.index("end-1c"))
            textbox.mark_gravity(mark_name, "left")
            self._turn_marks.append(mark_name)
            self._result.configure(state="normal")
            textbox.insert("end", f"\U0001f464 {pending_user}\n\n", "heading3")
            self._result.configure(state="disabled")
        self._refresh_turn_rail(turn_count)

    def _refresh_turn_rail(self, turn_count: int) -> None:
        if turn_count <= 1:
            self._active_turn_index = 0
            self._turn_jump_menu.pack_forget()
            self._turn_jump_var.set("")
            return
        if not self._turn_jump_menu.winfo_manager():
            self._turn_jump_menu.pack(side="left", padx=(0, 8))
        active_turn = min(turn_count, turn_count if self._pending_query else max(1, self._current_session.turn_count if self._current_session else turn_count))
        self._active_turn_index = active_turn
        values = [f"第 {idx} 轮" for idx in range(1, turn_count + 1)]
        self._turn_jump_menu.configure(values=values)
        self._turn_jump_var.set(f"第 {self._active_turn_index} 轮")

    def _on_turn_selected(self, value: str) -> None:
        try:
            turn_number = int(value.replace("第", "").replace("轮", "").strip())
        except Exception:
            return
        self._jump_to_turn(turn_number)

    def _jump_to_turn(self, turn_number: int) -> None:
        if turn_number < 1 or turn_number > len(self._turn_marks):
            return
        mark_name = self._turn_marks[turn_number - 1]
        textbox = self._result._textbox
        try:
            target_index = textbox.index(f"{mark_name} linestart")
            textbox.mark_set("insert", target_index)
            textbox.see(target_index)
            textbox.yview(target_index)
            self._active_turn_index = turn_number
            if self._turn_jump_menu.winfo_exists():
                self._turn_jump_var.set(f"第 {turn_number} 轮")
        except Exception:
            return

    def _new_session(self) -> None:
        self._current_session = None
        self._result.clear()
        self._clear_sources()
        self._full_result = ""
        self._latest_result_text = ""
        self._pending_query = ""
        self._switch_to_center_layout()
        self._update_turn_label()
        self._refresh_sessions()
        self._input.configure(state="normal")
        self._on_focus_in()
        self._input.delete("1.0", "end")
        self._input.focus_set()

    def _clear_all(self) -> None:
        self._store.clear()
        self._current_session = None
        self._new_session()

    def _update_turn_label(self) -> None:
        if self._current_session:
            n = self._current_session.turn_count
            if n > 0:
                self._turn_label.configure(text=f"对话轮次: {n}")
                return
        self._turn_label.configure(text="")

    # ── Copy result ──

    def _copy_result(self) -> None:
        content = self._full_result or self._latest_result_text
        if not content:
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        old = self._copy_btn.cget("text")
        self._copy_btn.configure(text="\u2713 已复制", text_color=theme.get("ACCENT_GREEN"))
        self.after(1500, lambda: self._copy_btn.configure(
            text=old, text_color=theme.get("TEXT_SECONDARY")))

    # ── Quick search ──

    def _quick_search(self, text: str) -> None:
        self._on_focus_in()
        self._input.delete("1.0", "end")
        self._input.insert("1.0", text)
        self._do_search()

    # ── Hotkey status ──

    def _do_enhance_prompt(self) -> None:
        if self._searching or self._enhancing or self._placeholder_active:
            return
        text = self._input.get("1.0", "end").strip()
        if not text:
            return

        self._close_enhance_dialog()
        self._enhance_original_text = text
        self._enhance_candidate = ""
        self._enhancing = True
        self._enhance_btn.configure(state="disabled", text="\u6da6\u8272\u4e2d...")
        self._status_label.configure(
            text="\u6b63\u5728\u6da6\u8272\u641c\u7d22\u63d0\u793a\u8bcd...",
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._enhancer.enhance(
            mode="search",
            text=text,
            locked_keywords=self._enhance_dialog.get_locked_keywords() if self._enhance_dialog else [],
            source="manual",
            feature="prompt_enhance",
            on_done=lambda value: self._safe_after(self._on_enhance_done, value),
            on_error=lambda msg: self._safe_after(self._on_enhance_error, msg),
        )

    def _on_enhance_done(self, value: str) -> None:
        self._enhancing = False
        self._enhance_candidate = value
        self._enhance_btn.configure(
            state="disabled" if self._searching else "normal",
            text="\u2728 \u6da6\u8272",
        )
        self._status_label.configure(
            text="\u5df2\u751f\u6210\u6da6\u8272\u9884\u89c8",
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._show_enhance_dialog()

    def _on_enhance_error(self, msg: str) -> None:
        self._enhancing = False
        self._enhance_btn.configure(
            state="disabled" if self._searching else "normal",
            text="\u2728 \u6da6\u8272",
        )
        if self._enhance_dialog and self._enhance_dialog.winfo_exists():
            self._enhance_dialog.set_busy(False)
            self._enhance_dialog.set_status(msg, is_error=True)
        self._status_label.configure(
            text=f"\u26a0 {msg}", text_color=theme.get("ACCENT_RED"),
        )

    def _show_enhance_dialog(self) -> None:
        if self._enhance_dialog and self._enhance_dialog.winfo_exists():
            self._enhance_dialog.set_busy(False)
            self._enhance_dialog.set_enhanced_text(self._enhance_candidate)
            self._enhance_dialog.set_status("")
            self._enhance_dialog.lift()
            return
        self._enhance_dialog = PromptEnhanceDialog(
            self,
            original_text=self._enhance_original_text,
            enhanced_text=self._enhance_candidate,
            title="\u6da6\u8272\u9884\u89c8",
            on_confirm=self._confirm_enhancement,
            on_regenerate=self._regenerate_enhancement,
            on_cancel=self._cancel_enhancement,
            locked_keywords=self._enhance_dialog.get_locked_keywords() if self._enhance_dialog else [],
        )

    def _confirm_enhancement(self) -> None:
        if not self._enhance_candidate:
            return
        self._on_focus_in()
        self._input.delete("1.0", "end")
        self._input.insert("1.0", self._enhance_candidate)
        self._status_label.configure(
            text="\u5df2\u4f7f\u7528\u6da6\u8272\u7ed3\u679c",
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._close_enhance_dialog()

    def _regenerate_enhancement(self) -> None:
        if self._enhancing or not self._enhance_original_text:
            return
        self._enhancing = True
        self._enhance_btn.configure(state="disabled", text="\u6da6\u8272\u4e2d...")
        if self._enhance_dialog and self._enhance_dialog.winfo_exists():
            self._enhance_dialog.set_busy(True, "\u6b63\u5728\u751f\u6210\u65b0\u7684\u6da6\u8272\u65b9\u6848...")
        self._status_label.configure(
            text="\u6b63\u5728\u751f\u6210\u65b0\u7684\u6da6\u8272\u65b9\u6848...",
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._enhancer.enhance(
            mode="search",
            text=self._enhance_original_text,
            previous_candidate=self._enhance_candidate,
            variation=True,
            locked_keywords=self._enhance_dialog.get_locked_keywords() if self._enhance_dialog else [],
            source="manual",
            feature="prompt_enhance",
            on_done=lambda value: self._safe_after(self._on_enhance_done, value),
            on_error=lambda msg: self._safe_after(self._on_enhance_error, msg),
        )

    def _cancel_enhancement(self) -> None:
        if self._enhancing:
            self._enhancer.cancel()
            self._enhancing = False
            self._enhance_btn.configure(
                state="disabled" if self._searching else "normal",
                text="\u2728 \u6da6\u8272",
            )
        self._status_label.configure(
            text="\u5df2\u53d6\u6d88\u6da6\u8272",
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._close_enhance_dialog()

    def _close_enhance_dialog(self) -> None:
        if self._enhance_dialog and self._enhance_dialog.winfo_exists():
            self._enhance_dialog.close()
        self._enhance_dialog = None

    def set_hotkey_status(self, active: bool) -> None:
        if not active and not self._hotkey_warn:
            self._hotkey_warn = ctk.CTkLabel(
                self._search_area,
                text="\u26a0 全局热键不可用，请以管理员身份运行",
                font=theme.font_small(),
                text_color=theme.get("ACCENT_YELLOW"), anchor="w",
            )
            self._hotkey_warn.pack(fill="x", pady=(2, 0))

    def show_external_status(
        self,
        text: str,
        is_error: bool = False,
        timeout_ms: int = 2500,
    ) -> None:
        if self._external_status_job:
            self.after_cancel(self._external_status_job)
            self._external_status_job = None
        self._status_label.configure(
            text=text,
            text_color=theme.get("ACCENT_RED") if is_error else theme.get("TEXT_SECONDARY"),
        )
        if timeout_ms > 0:
            self._external_status_job = self.after(timeout_ms, self._clear_external_status)

    def _clear_external_status(self) -> None:
        self._external_status_job = None
        if self._searching or self._enhancing:
            return
        self._status_label.configure(text="", text_color=theme.get("TEXT_SECONDARY"))

    def save_external_search_session(self, query: str, result: str) -> None:
        self._store.create_session_from_turn(
            query=query,
            result=result,
            mode="detailed",
            web=True,
            source="floating",
            feature="floating_search",
            model=self._client.model_name,
            tags=["safe"],
        )
        self._refresh_sessions()

    def _export_session(self, kind: str) -> None:
        if not self._current_session or not self._current_session.messages:
            return
        ext = ".json" if kind == "json" else ".md"
        path = filedialog.asksaveasfilename(
            title="导出会话",
            defaultextension=ext,
            initialfile=f"search_session_{self._current_session.id}{ext}",
            filetypes=[("JSON", "*.json")] if kind == "json" else [("Markdown", "*.md")],
        )
        if not path:
            return
        target = Path(path)
        if kind == "json":
            import json

            target.write_text(json.dumps(self._current_session.to_dict(), ensure_ascii=False, indent=2), "utf-8")
        else:
            lines = [f"# {self._current_session.display_title}", ""]
            for msg in self._current_session.messages:
                role = "User" if msg.get("role") == "user" else "Assistant"
                lines.append(f"## {role}")
                lines.append(msg.get("content", ""))
                lines.append("")
            target.write_text("\n".join(lines), "utf-8")
        self._status_label.configure(
            text=f"已导出会话: {target}",
            text_color=theme.get("TEXT_SECONDARY"),
        )

    # ── Focus helper ──

    def focus_input(self) -> None:
        if self._searching:
            return
        self._input.configure(state="normal")
        self._on_focus_in()
        self._input.focus_set()

    # ── Source cards ──

    def _clear_sources(self) -> None:
        for card in self._source_cards:
            card.destroy()
        self._source_cards.clear()
        self._source_frame.pack_forget()

    def _show_sources_from_text(self, text: str) -> None:
        self._clear_sources()
        urls = list(dict.fromkeys(re.findall(r"https?://[^\s\)\]>\"']+", text or "")))
        if not urls:
            return
        self._source_frame.configure(height=min(len(urls) * 40 + 16, 160))
        self._source_frame.pack(fill="x", padx=48, pady=(0, 12))

        for url in urls:
            try:
                parsed = urlparse(url)
                path_display = parsed.netloc + parsed.path
                if len(path_display) > 60:
                    path_display = path_display[:57] + "..."
                icon = _domain_icon(parsed.netloc)
            except Exception:
                path_display = url[:60]
                icon = "\U0001f517"
            card = ctk.CTkFrame(
                self._source_frame,
                fg_color=theme.get("BG_INPUT"), corner_radius=6, height=32,
            )
            card.pack(fill="x", pady=2)
            card.pack_propagate(False)
            lbl = ctk.CTkLabel(
                card, text=f"{icon} {path_display}",
                font=theme.font_small(),
                text_color=theme.get("ACCENT_BLUE"),
                anchor="w", cursor="hand2",
            )
            lbl.pack(fill="x", padx=12, pady=4)
            lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
            self._source_cards.append(card)

    # ── Theme ──

    def _apply_theme(self) -> None:
        self.configure(fg_color=theme.get("BG_ROOT"))
        self._session_panel.configure(fg_color=theme.get("BG_CARD"))
        self._session_scroll.configure(fg_color=theme.get("BG_CARD"))
        self._current_section_label.configure(text_color=theme.get("TEXT_MUTED"))
        self._history_section_label.configure(text_color=theme.get("TEXT_MUTED"))
        if self._history_empty_label and self._history_empty_label.winfo_exists():
            self._history_empty_label.configure(text_color=theme.get("TEXT_MUTED"))
        self._new_btn.configure(
            fg_color=theme.get("ACCENT_BLUE"),
            hover_color=theme.get("HOVER_BLUE"),
        )
        self._clear_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._logo_label.configure(text_color=theme.get("ACCENT_BLUE"))
        self._logo_sub.configure(text_color=theme.get("TEXT_MUTED"))
        self._web_switch.configure(
            text_color=theme.get("TEXT_PRIMARY"),
            progress_color=theme.get("ACCENT_BLUE"),
        )
        self._mode_menu.configure(
            fg_color=theme.get("BG_INPUT"),
            button_color=theme.get("BG_INPUT"),
            button_hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_PRIMARY"),
            dropdown_fg_color=theme.get("BG_CARD"),
            dropdown_text_color=theme.get("TEXT_PRIMARY"),
            dropdown_hover_color=theme.get("HOVER_GENERIC"),
        )
        self._mode_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        txt_color = theme.get("TEXT_MUTED") if self._placeholder_active else theme.get("TEXT_PRIMARY")
        self._input.configure(fg_color=theme.get("BG_INPUT"), text_color=txt_color)
        self._enhance_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._send_btn.configure(
            fg_color=theme.get("ACCENT_BLUE"), hover_color=theme.get("HOVER_BLUE"),
        )
        self._stop_btn.configure(
            fg_color=theme.get("ACCENT_RED"), hover_color=theme.get("HOVER_RED"),
        )
        self._status_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._source_frame.configure(fg_color=theme.get("BG_ROOT"))
        self._copy_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._export_json_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._export_md_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._turn_label.configure(text_color=theme.get("TEXT_MUTED"))
        self._shortcut_hint.configure(text_color=theme.get("TEXT_MUTED"))
        for tb in self._tag_buttons:
            tb.configure(
                fg_color=theme.get("BG_INPUT"),
                hover_color=theme.get("HOVER_GENERIC"),
                text_color=theme.get("TEXT_SECONDARY"),
            )
        if self._hotkey_warn:
            self._hotkey_warn.configure(text_color=theme.get("ACCENT_YELLOW"))
        self._refresh_sessions()
        for card in self._source_cards:
            card.configure(fg_color=theme.get("BG_INPUT"))
            for child in card.winfo_children():
                if isinstance(child, ctk.CTkLabel):
                    child.configure(text_color=theme.get("ACCENT_BLUE"))

    def destroy(self):
        self._client.cancel()
        self._enhancer.cancel()
        self._stop_status_animation()
        if self._external_status_job:
            self.after_cancel(self._external_status_job)
            self._external_status_job = None
        self._close_enhance_dialog()
        theme.remove_listener(self._apply_theme)
        super().destroy()
