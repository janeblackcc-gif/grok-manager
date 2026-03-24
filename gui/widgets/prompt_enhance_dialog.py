from __future__ import annotations

import difflib

import customtkinter as ctk

from gui import theme


def _parse_keywords(value: str) -> list[str]:
    parts = [item.strip() for item in value.replace("\n", ",").split(",")]
    return [item for item in parts if item]


class PromptEnhanceDialog(ctk.CTkToplevel):

    def __init__(
        self,
        master,
        original_text: str,
        enhanced_text: str,
        title: str,
        on_confirm,
        on_regenerate,
        on_cancel,
        locked_keywords: list[str] | None = None,
    ):
        super().__init__(master)
        self._on_confirm_cb = on_confirm
        self._on_regenerate_cb = on_regenerate
        self._on_cancel_cb = on_cancel
        self._closed = False

        self.title(title)
        self.geometry(self._center_geometry(master, 860, 760))
        self.minsize(760, 620)
        self.transient(master)
        self.grab_set()
        self.configure(fg_color=theme.get("BG_ROOT"))
        self.protocol("WM_DELETE_WINDOW", self._handle_cancel)

        self._locked_keywords_var = ctk.StringVar(value=", ".join(locked_keywords or []))

        self._build_ui(title, original_text, enhanced_text)
        theme.on_theme_change(self._apply_theme)
        self.after(50, self.focus_force)

    @staticmethod
    def _center_geometry(master, width: int, height: int) -> str:
        try:
            master.update_idletasks()
            x = master.winfo_rootx() + max(0, (master.winfo_width() - width) // 2)
            y = master.winfo_rooty() + max(0, (master.winfo_height() - height) // 2)
        except Exception:
            x = 200
            y = 120
        return f"{width}x{height}+{x}+{y}"

    def _build_ui(self, title: str, original_text: str, enhanced_text: str) -> None:
        outer = ctk.CTkFrame(
            self,
            fg_color=theme.get("BG_CARD"),
            corner_radius=theme.CARD_CORNER_RADIUS,
            border_width=theme.CARD_BORDER_WIDTH,
            border_color=theme.get("CARD_BORDER_COLOR"),
        )
        outer.pack(fill="both", expand=True, padx=16, pady=16)
        self._outer = outer
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(7, weight=1)

        header = ctk.CTkFrame(outer, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))

        self._title_label = ctk.CTkLabel(
            header,
            text=title,
            font=theme.font_heading(17),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._title_label.pack(side="left")

        self._status_label = ctk.CTkLabel(
            outer,
            text="",
            anchor="w",
            font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._status_label.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))

        self._original_label = ctk.CTkLabel(
            outer,
            text="原始内容",
            anchor="w",
            font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._original_label.grid(row=2, column=0, sticky="ew", padx=18)

        self._original_box = ctk.CTkTextbox(
            outer,
            height=110,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_body(),
            corner_radius=8,
        )
        self._original_box.grid(row=3, column=0, sticky="ew", padx=18, pady=(4, 12))
        self._set_box_text(self._original_box, original_text)

        keyword_row = ctk.CTkFrame(outer, fg_color="transparent")
        keyword_row.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 10))
        keyword_row.grid_columnconfigure(1, weight=1)
        self._keyword_label = ctk.CTkLabel(
            keyword_row,
            text="关键词锁定",
            anchor="w",
            font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._keyword_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._keyword_entry = ctk.CTkEntry(
            keyword_row,
            textvariable=self._locked_keywords_var,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            corner_radius=6,
            placeholder_text="用逗号分隔，例如：磷化氢, 砷化氢, 毒气",
        )
        self._keyword_entry.grid(row=0, column=1, sticky="ew")
        self._keyword_hint = ctk.CTkLabel(
            outer,
            text="填写你不希望被改写的术语、实体名或风格词，然后点击“重新润色”。",
            anchor="w",
            justify="left",
            wraplength=760,
            font=theme.font_small(),
            text_color=theme.get("TEXT_MUTED"),
        )
        self._keyword_hint.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 10))

        self._diff_label = ctk.CTkLabel(
            outer,
            text="差异预览",
            anchor="w",
            font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._diff_label.grid(row=6, column=0, sticky="ew", padx=18)

        self._diff_box = ctk.CTkTextbox(
            outer,
            height=120,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_mono(),
            corner_radius=8,
        )
        self._diff_box.grid(row=7, column=0, sticky="ew", padx=18, pady=(4, 12))
        self._diff_box.tag_config("diff_remove", foreground=theme.get("ACCENT_RED"))
        self._diff_box.tag_config("diff_add", foreground=theme.get("ACCENT_GREEN"))
        self._diff_box.tag_config("diff_hint", foreground=theme.get("TEXT_MUTED"))

        self._enhanced_label = ctk.CTkLabel(
            outer,
            text="润色结果",
            anchor="w",
            font=theme.font_small(),
            text_color=theme.get("ACCENT_BLUE"),
        )
        self._enhanced_label.grid(row=8, column=0, sticky="ew", padx=18)

        self._enhanced_box = ctk.CTkTextbox(
            outer,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_body(),
            corner_radius=8,
        )
        self._enhanced_box.grid(row=9, column=0, sticky="nsew", padx=18, pady=(4, 12))
        outer.grid_rowconfigure(9, weight=1)

        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.grid(row=10, column=0, sticky="ew", padx=18, pady=(0, 16))

        self._cancel_btn = ctk.CTkButton(
            footer,
            text="取消",
            width=88,
            height=32,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            corner_radius=8,
            command=self._handle_cancel,
        )
        self._cancel_btn.pack(side="right")

        self._confirm_btn = ctk.CTkButton(
            footer,
            text="确认替换",
            width=108,
            height=32,
            fg_color=theme.get("ACCENT_BLUE"),
            hover_color=theme.get("HOVER_BLUE"),
            text_color=theme.get("TEXT_WHITE"),
            corner_radius=8,
            command=self._handle_confirm,
        )
        self._confirm_btn.pack(side="right", padx=(0, 8))

        self._regen_btn = ctk.CTkButton(
            footer,
            text="重新润色",
            width=116,
            height=32,
            fg_color=theme.get("ACCENT_PURPLE"),
            hover_color=theme.get("HOVER_PURPLE"),
            text_color=theme.get("TEXT_WHITE"),
            corner_radius=8,
            command=self._handle_regenerate,
        )
        self._regen_btn.pack(side="left")

        self.set_enhanced_text(enhanced_text)

    @staticmethod
    def _set_box_text(widget: ctk.CTkTextbox, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    @staticmethod
    def _build_diff_text(original_text: str, enhanced_text: str) -> str:
        original_words = original_text.split()
        enhanced_words = enhanced_text.split()
        diff = []
        for part in difflib.ndiff(original_words, enhanced_words):
            if part.startswith("- "):
                diff.append(f"- {part[2:]}")
            elif part.startswith("+ "):
                diff.append(f"+ {part[2:]}")
        if not diff:
            return "未检测到明显文字差异。"
        return "\n".join(diff[:120])

    def set_enhanced_text(self, text: str) -> None:
        self._set_box_text(self._enhanced_box, text)
        self._set_diff_text(self._build_diff_text(self._original_box.get("1.0", "end").strip(), text))

    def _set_diff_text(self, text: str) -> None:
        self._diff_box.configure(state="normal")
        self._diff_box.delete("1.0", "end")
        for line in text.splitlines() or [""]:
            tag = None
            if line.startswith("+ "):
                tag = "diff_add"
            elif line.startswith("- "):
                tag = "diff_remove"
            else:
                tag = "diff_hint"
            self._diff_box.insert("end", line + "\n", tag)
        self._diff_box.configure(state="disabled")

    def get_locked_keywords(self) -> list[str]:
        return _parse_keywords(self._locked_keywords_var.get())

    def set_busy(self, busy: bool, status: str = "") -> None:
        state = "disabled" if busy else "normal"
        self._confirm_btn.configure(state=state)
        self._cancel_btn.configure(state=state)
        self._keyword_entry.configure(state=state)
        self._regen_btn.configure(
            state=state,
            text="处理中..." if busy else "重新润色",
        )
        self.set_status(status)

    def set_status(self, text: str, is_error: bool = False) -> None:
        self._status_label.configure(
            text=text,
            text_color=theme.get("ACCENT_RED") if is_error else theme.get("TEXT_SECONDARY"),
        )

    def _handle_confirm(self) -> None:
        if self._closed:
            return
        self._on_confirm_cb()

    def _handle_regenerate(self) -> None:
        if self._closed:
            return
        self._on_regenerate_cb()

    def _handle_cancel(self) -> None:
        if self._closed:
            return
        self._on_cancel_cb()
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        theme.remove_listener(self._apply_theme)
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def _apply_theme(self) -> None:
        self.configure(fg_color=theme.get("BG_ROOT"))
        self._outer.configure(
            fg_color=theme.get("BG_CARD"),
            border_color=theme.get("CARD_BORDER_COLOR"),
        )
        self._title_label.configure(text_color=theme.get("TEXT_PRIMARY"))
        self._status_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._original_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._enhanced_label.configure(text_color=theme.get("ACCENT_BLUE"))
        self._diff_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._keyword_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._keyword_hint.configure(text_color=theme.get("TEXT_MUTED"))
        self._original_box.configure(
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._diff_box.configure(
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._diff_box.tag_config("diff_remove", foreground=theme.get("ACCENT_RED"))
        self._diff_box.tag_config("diff_add", foreground=theme.get("ACCENT_GREEN"))
        self._diff_box.tag_config("diff_hint", foreground=theme.get("TEXT_MUTED"))
        self._enhanced_box.configure(
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._keyword_entry.configure(
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._cancel_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._confirm_btn.configure(
            fg_color=theme.get("ACCENT_BLUE"),
            hover_color=theme.get("HOVER_BLUE"),
        )
        self._regen_btn.configure(
            fg_color=theme.get("ACCENT_PURPLE"),
            hover_color=theme.get("HOVER_PURPLE"),
        )
