from __future__ import annotations

from tkinter import filedialog

import customtkinter as ctk

from gui import theme


class SettingsDialog(ctk.CTkToplevel):

    def __init__(self, master, initial: dict[str, object], on_save):
        super().__init__(master)
        self._on_save = on_save
        self.title("Settings")
        self.geometry(self._center_geometry(master, 520, 420))
        self.transient(master)
        self.grab_set()
        self.configure(fg_color=theme.get("BG_ROOT"))
        self.protocol("WM_DELETE_WINDOW", self.close)

        self._global_hotkey_var = ctk.StringVar(value=str(initial.get("global_search_hotkey", "alt+s")))
        self._floating_hotkey_var = ctk.StringVar(value=str(initial.get("floating_search_hotkey", "alt+q")))
        self._output_dir_var = ctk.StringVar(value=str(initial.get("default_output_dir", "")))
        self._mode_var = ctk.StringVar(value=str(initial.get("default_search_mode", "detailed")))
        self._web_var = ctk.BooleanVar(value=bool(initial.get("default_web_enabled", True)))

        self._build_ui()
        theme.on_theme_change(self._apply_theme)

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

    def _build_ui(self) -> None:
        outer = ctk.CTkFrame(
            self,
            fg_color=theme.get("BG_CARD"),
            corner_radius=theme.CARD_CORNER_RADIUS,
            border_width=theme.CARD_BORDER_WIDTH,
            border_color=theme.get("CARD_BORDER_COLOR"),
        )
        outer.pack(fill="both", expand=True, padx=16, pady=16)
        self._outer = outer

        self._title = ctk.CTkLabel(
            outer,
            text="运行设置",
            font=theme.font_heading(18),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._title.pack(anchor="w", padx=18, pady=(16, 12))

        self._status = ctk.CTkLabel(
            outer,
            text="",
            anchor="w",
            font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._status.pack(fill="x", padx=18, pady=(0, 8))

        self._global_entry = self._add_form_row(outer, "全局搜索热键", self._global_hotkey_var)
        self._floating_entry = self._add_form_row(outer, "悬浮搜索热键", self._floating_hotkey_var)

        output_row = ctk.CTkFrame(outer, fg_color="transparent")
        output_row.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(
            output_row,
            text="默认导出目录",
            width=120,
            anchor="w",
            font=theme.font_body(),
            text_color=theme.get("TEXT_PRIMARY"),
        ).pack(side="left")
        self._output_entry = ctk.CTkEntry(
            output_row,
            textvariable=self._output_dir_var,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            corner_radius=6,
        )
        self._output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._browse_btn = ctk.CTkButton(
            output_row,
            text="浏览",
            width=68,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            corner_radius=6,
            command=self._browse_output_dir,
        )
        self._browse_btn.pack(side="right")

        mode_row = ctk.CTkFrame(outer, fg_color="transparent")
        mode_row.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(
            mode_row,
            text="默认搜索模式",
            width=120,
            anchor="w",
            font=theme.font_body(),
            text_color=theme.get("TEXT_PRIMARY"),
        ).pack(side="left")
        self._mode_menu = ctk.CTkComboBox(
            mode_row,
            values=["concise", "detailed", "expert"],
            variable=self._mode_var,
            state="readonly",
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            corner_radius=6,
        )
        self._mode_menu.pack(side="left", fill="x", expand=True)

        self._web_switch = ctk.CTkSwitch(
            outer,
            text="默认开启联网搜索",
            variable=self._web_var,
            font=theme.font_body(),
            text_color=theme.get("TEXT_PRIMARY"),
            progress_color=theme.get("ACCENT_BLUE"),
        )
        self._web_switch.pack(anchor="w", padx=18, pady=(0, 18))

        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.pack(fill="x", padx=18, pady=(0, 16))
        self._cancel_btn = ctk.CTkButton(
            footer,
            text="取消",
            width=88,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            corner_radius=6,
            command=self.close,
        )
        self._cancel_btn.pack(side="right")
        self._save_btn = ctk.CTkButton(
            footer,
            text="保存",
            width=88,
            fg_color=theme.get("ACCENT_BLUE"),
            hover_color=theme.get("HOVER_BLUE"),
            text_color=theme.get("TEXT_WHITE"),
            corner_radius=6,
            command=self._handle_save,
        )
        self._save_btn.pack(side="right", padx=(0, 8))

    def _add_form_row(self, outer, label: str, variable) -> ctk.CTkEntry:
        row = ctk.CTkFrame(outer, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(
            row,
            text=label,
            width=120,
            anchor="w",
            font=theme.font_body(),
            text_color=theme.get("TEXT_PRIMARY"),
        ).pack(side="left")
        entry = ctk.CTkEntry(
            row,
            textvariable=variable,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            corner_radius=6,
        )
        entry.pack(side="left", fill="x", expand=True)
        return entry

    def _browse_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="选择默认导出目录")
        if selected:
            self._output_dir_var.set(selected)

    def _handle_save(self) -> None:
        self._on_save(
            {
                "global_search_hotkey": self._global_hotkey_var.get().strip(),
                "floating_search_hotkey": self._floating_hotkey_var.get().strip(),
                "default_output_dir": self._output_dir_var.get().strip(),
                "default_search_mode": self._mode_var.get().strip(),
                "default_web_enabled": self._web_var.get(),
            }
        )

    def set_status(self, text: str, is_error: bool = False) -> None:
        self._status.configure(
            text=text,
            text_color=theme.get("ACCENT_RED") if is_error else theme.get("TEXT_SECONDARY"),
        )

    def close(self) -> None:
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
        self._outer.configure(fg_color=theme.get("BG_CARD"), border_color=theme.get("CARD_BORDER_COLOR"))
        self._title.configure(text_color=theme.get("TEXT_PRIMARY"))
