from __future__ import annotations

import logging
import threading
import time

import customtkinter as ctk

from config import AppConfig, save_config
from gui import theme
from gui.pages.account_pool import AccountPoolPage
from gui.pages.ai_search import AISearchPage
from gui.pages.creation_center import CreationCenterPage
from gui.pages.dashboard import DashboardPage
from gui.pages.services import ServicesPage
from gui.pages.test_lab import TestLabPage
from gui.sidebar import Sidebar
from gui.utils.hotkey_manager import HotkeyManager
from gui.utils.task_registry import get_task_registry
from gui.widgets.floating_search_window import FloatingSearchWindow
from gui.widgets.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)


class GrokManagerApp(ctk.CTk):

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self._tray_icon = None
        self._tray_available = False
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._current_page: str | None = None
        self._floating_window: FloatingSearchWindow | None = None
        self._restore_after_id: str | None = None
        self._restore_cover: ctk.CTkFrame | None = None
        self._settings_dialog: SettingsDialog | None = None
        self._hotkeys = HotkeyManager()

        self.title("Grok Manager")
        self.geometry("1200x750")
        self.minsize(960, 550)
        self.configure(fg_color=theme.get("BG_ROOT"))
        ctk.set_appearance_mode("light")

        # Window icon
        from pathlib import Path
        ico_path = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
        if ico_path.exists():
            self.iconbitmap(str(ico_path))

        theme.init_fonts(self)
        theme.on_theme_change(self._on_theme_change)
        self._build_ui()
        self._setup_tray()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _safe_after(self, func, *args) -> None:
        try:
            if self.winfo_exists():
                self.after(0, func, *args)
        except RuntimeError:
            pass

    def _build_ui(self) -> None:
        self._sidebar = Sidebar(self, on_navigate=self._switch_page,
                                on_toggle_theme=self._toggle_theme,
                                on_open_settings=self._open_settings_dialog)
        self._sidebar.pack(side="left", fill="y")

        self._shell = ctk.CTkFrame(self, fg_color=theme.get("BG_ROOT"), corner_radius=0)
        self._shell.pack(side="right", fill="both", expand=True)
        self._content = ctk.CTkFrame(self._shell, fg_color=theme.get("BG_ROOT"),
                                      corner_radius=0)
        self._content.pack(side="right", fill="both", expand=True)

        svc_page = ServicesPage(self._content, self.config)
        self._pages["services"] = svc_page
        self._service_cards = svc_page.cards

        dash_page = DashboardPage(self._content, self.config, self._service_cards)
        self._pages["dashboard"] = dash_page

        pool_page = AccountPoolPage(self._content, self.config)
        self._pages["pool"] = pool_page

        ai_page = AISearchPage(self._content, self.config)
        self._pages["ai_search"] = ai_page

        creation_page = CreationCenterPage(self._content, self.config)
        self._pages["creation"] = creation_page
        self._pages["test_lab"] = TestLabPage(self._content, self.config)

        self._task_bar = ctk.CTkFrame(self._shell, fg_color=theme.get("BG_CARD"), height=34, corner_radius=0)
        self._task_bar_visible = False
        self._task_label = ctk.CTkLabel(
            self._task_bar,
            text="就绪",
            anchor="w",
            font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._task_label.pack(side="left", fill="x", expand=True, padx=12)
        self._task_label.configure(text="")
        self._task_cancel_btn = ctk.CTkButton(
            self._task_bar,
            text="取消任务",
            width=88,
            height=24,
            fg_color=theme.get("ACCENT_RED"),
            hover_color=theme.get("HOVER_RED"),
            text_color=theme.get("TEXT_WHITE"),
            corner_radius=6,
            state="disabled",
            command=self._cancel_active_task,
        )
        self._task_cancel_btn.pack(side="right", padx=8, pady=5)
        self._task_cancel_btn.configure(text="Cancel Task")

        self._switch_page("dashboard")
        dash_page.start_polling()
        pool_page.start_polling()
        self._setup_hotkey()
        get_task_registry().on_change(self._on_tasks_changed)
        ai_page = self._pages.get("ai_search")
        if ai_page and hasattr(ai_page, "set_hotkey_status"):
            ai_page.set_hotkey_status(self._global_hotkey_active)

    def _switch_page(self, key: str) -> None:
        if self._current_page == key:
            return
        if self._current_page and self._current_page in self._pages:
            self._pages[self._current_page].pack_forget()
        page = self._pages.get(key)
        if page:
            page.pack(in_=self._content, fill="both", expand=True)
        self._current_page = key
        self._sidebar.set_active(key)

    def _toggle_theme(self) -> None:
        new_mode = "light" if theme.current_mode() == "dark" else "dark"
        ctk.set_appearance_mode(new_mode)
        theme.set_mode(new_mode)

    def _setup_hotkey(self) -> None:
        # In-app shortcut (Ctrl+K)
        self.bind("<Control-k>", self._on_search_hotkey)
        self._apply_hotkeys()

    def _apply_hotkeys(self) -> None:
        result = self._hotkeys.register(
            {
                "global_search": self.config.ui.global_search_hotkey,
                "floating_search": self.config.ui.floating_search_hotkey,
            },
            {
                "global_search": self._on_global_search_hotkey,
                "floating_search": self._on_floating_search_hotkey,
            },
        )
        self._global_hotkey_active = result.active
        if not result.active:
            logger.warning("Failed to register global hotkeys: %s", "; ".join(result.errors))

    def _on_search_hotkey(self, event=None) -> None:
        self._switch_page("ai_search")
        page = self._pages.get("ai_search")
        if page and hasattr(page, "focus_input"):
            self.after(50, page.focus_input)

    def _on_global_search_hotkey(self) -> None:
        self._safe_after(self._activate_search)

    def _on_floating_search_hotkey(self) -> None:
        threading.Thread(target=self._capture_and_open_floating_search, daemon=True).start()

    def _capture_and_open_floating_search(self) -> None:
        x, y = self._get_cursor_pos()
        query = self._capture_selected_text()
        if not query:
            self._safe_after(
                self._show_ai_search_status,
                "\u672a\u68c0\u6d4b\u5230\u65b0\u7684\u5212\u8bcd\u5185\u5bb9",
                True,
            )
            return
        self._safe_after(self._open_floating_search_window, query, x, y)

    def _capture_selected_text(self) -> str:
        try:
            import keyboard
        except Exception:
            return ""

        before_seq = self._get_clipboard_sequence_number()
        try:
            keyboard.send("ctrl+c")
        except Exception:
            return ""

        if before_seq is not None:
            deadline = time.time() + 1.5
            while time.time() < deadline:
                time.sleep(0.04)
                current_seq = self._get_clipboard_sequence_number()
                if current_seq is not None and current_seq != before_seq:
                    text = self._read_clipboard_text()
                    if text:
                        return text
            return ""

        time.sleep(0.18)
        return self._read_clipboard_text()

    def _read_clipboard_text(self) -> str:
        try:
            return self.clipboard_get().strip()
        except Exception:
            return ""

    @staticmethod
    def _get_clipboard_sequence_number() -> int | None:
        try:
            import ctypes

            return int(ctypes.windll.user32.GetClipboardSequenceNumber())
        except Exception:
            return None

    def _show_ai_search_status(self, text: str, is_error: bool = False) -> None:
        page = self._pages.get("ai_search")
        if page and hasattr(page, "show_external_status"):
            page.show_external_status(text, is_error=is_error)

    def _open_floating_search_window(self, query: str, x: int, y: int) -> None:
        x = max(16, x + 12)
        y = max(16, y + 12)

        if self._floating_window and self._floating_window.winfo_exists():
            self._floating_window.close()

        self._floating_window = FloatingSearchWindow(
            self,
            query,
            x,
            y,
            on_result_saved=self._save_floating_search_session,
        )

    def _save_floating_search_session(self, query: str, result: str) -> None:
        page = self._pages.get("ai_search")
        if page and hasattr(page, "save_external_search_session"):
            self._safe_after(page.save_external_search_session, query, result)

    def _activate_search(self) -> None:
        self._restore_window()
        self._switch_page("ai_search")
        page = self._pages.get("ai_search")
        if page and hasattr(page, "focus_input"):
            self.after(50, page.focus_input)

    @staticmethod
    def _get_cursor_pos() -> tuple[int, int]:
        try:
            import win32api

            return win32api.GetCursorPos()
        except Exception:
            return 200, 200

    def _on_theme_change(self) -> None:
        self.configure(fg_color=theme.get("BG_ROOT"))
        self._shell.configure(fg_color=theme.get("BG_ROOT"))
        self._content.configure(fg_color=theme.get("BG_ROOT"))
        self._task_bar.configure(fg_color=theme.get("BG_CARD"))
        self._task_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        if self._restore_cover and self._restore_cover.winfo_exists():
            self._restore_cover.configure(fg_color=theme.get("BG_ROOT"))

    def _show_restore_cover(self) -> None:
        if self._restore_cover and self._restore_cover.winfo_exists():
            self._restore_cover.lift()
            return
        self._restore_cover = ctk.CTkFrame(
            self,
            fg_color=theme.get("BG_ROOT"),
            corner_radius=0,
            border_width=0,
        )
        self._restore_cover.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._restore_cover.lift()

    def _hide_restore_cover(self) -> None:
        if not self._restore_cover:
            return
        try:
            if self._restore_cover.winfo_exists():
                self._restore_cover.place_forget()
                self._restore_cover.destroy()
        except Exception:
            pass
        self._restore_cover = None

    # ── Tray icon ──

    def _setup_tray(self) -> None:
        try:
            import pystray
            from PIL import Image
            from pathlib import Path
            tray_png = Path(__file__).resolve().parent.parent / "assets" / "icon_tray.png"
            if tray_png.exists():
                img = Image.open(tray_png)
            else:
                from PIL import ImageDraw
                img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                draw.rounded_rectangle([4, 4, 60, 60], radius=12, fill="#1A6DFF")
                draw.text((18, 12), "G", fill="white")
            menu = pystray.Menu(
                pystray.MenuItem("Show Window",
                                 lambda: self._safe_after(self._show_window),
                                 default=True),
                pystray.MenuItem("Exit",
                                 lambda: self._safe_after(self._shutdown_all)),
            )
            self._tray_icon = pystray.Icon("grok-manager", img,
                                            "Grok Manager", menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
            self._tray_available = True
        except Exception:
            logger.warning("Tray init failed, close will exit directly")
            self._tray_available = False

    def _on_close(self) -> None:
        if self._tray_available:
            self.withdraw()
        else:
            self._shutdown_all()

    def _restore_window(self) -> None:
        if self._restore_after_id:
            try:
                self.after_cancel(self._restore_after_id)
            except Exception:
                pass
            self._restore_after_id = None

        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            pass

        self._show_restore_cover()
        self.deiconify()
        self.lift()
        self.update_idletasks()

        current_page = self._pages.get(self._current_page) if self._current_page else None
        if current_page:
            try:
                current_page.update_idletasks()
            except Exception:
                pass

        self._restore_after_id = self.after(30, self._finish_restore_window)

    def _finish_restore_window(self) -> None:
        self._restore_after_id = None
        self.lift()
        try:
            self.attributes("-alpha", 1.0)
        except Exception:
            pass
        self.update_idletasks()
        self.after(80, self._hide_restore_cover)
        try:
            self.focus_force()
        except Exception:
            pass

    def _show_window(self) -> None:
        self._restore_window()

    def _on_tasks_changed(self) -> None:
        self._safe_after(self._refresh_task_bar_ui)

    def _refresh_task_bar(self) -> None:
        tasks = get_task_registry().active_tasks()
        if not tasks:
            self._task_label.configure(text="就绪")
            self._task_cancel_btn.configure(state="disabled")
            return
        task = tasks[-1]
        message = f"{task.label}"
        if task.message:
            message += f" · {task.message}"
        self._task_label.configure(text=message)
        self._task_cancel_btn.configure(state="normal" if task.cancel else "disabled")

    def _refresh_task_bar_ui(self) -> None:
        self._task_label.configure(text="")
        self._task_cancel_btn.configure(state="disabled")
        if self._task_bar_visible:
            self._task_bar.pack_forget()
            self._task_bar_visible = False

    def _cancel_active_task(self) -> None:
        tasks = get_task_registry().active_tasks()
        if not tasks:
            return
        task = tasks[-1]
        if task.cancel:
            try:
                task.cancel()
            except Exception:
                pass

    def _open_settings_dialog(self) -> None:
        if self._settings_dialog and self._settings_dialog.winfo_exists():
            self._settings_dialog.lift()
            return
        self._settings_dialog = SettingsDialog(
            self,
            initial={
                "global_search_hotkey": self.config.ui.global_search_hotkey,
                "floating_search_hotkey": self.config.ui.floating_search_hotkey,
                "default_output_dir": self.config.ui.default_output_dir,
                "default_search_mode": self.config.ui.default_search_mode,
                "default_web_enabled": self.config.ui.default_web_enabled,
            },
            on_save=self._save_settings,
        )

    def _save_settings(self, values: dict[str, object]) -> None:
        global_hotkey = str(values.get("global_search_hotkey", "")).strip().lower()
        floating_hotkey = str(values.get("floating_search_hotkey", "")).strip().lower()
        if not global_hotkey or not floating_hotkey:
            self._settings_dialog.set_status("热键不能为空", is_error=True)
            return
        if global_hotkey == floating_hotkey:
            self._settings_dialog.set_status("两个热键不能相同", is_error=True)
            return

        self.config.ui.global_search_hotkey = global_hotkey
        self.config.ui.floating_search_hotkey = floating_hotkey
        self.config.ui.default_output_dir = str(values.get("default_output_dir", "")).strip()
        self.config.ui.default_search_mode = str(values.get("default_search_mode", "detailed")).strip()
        self.config.ui.default_web_enabled = bool(values.get("default_web_enabled", True))

        result = self._hotkeys.register(
            {
                "global_search": self.config.ui.global_search_hotkey,
                "floating_search": self.config.ui.floating_search_hotkey,
            },
            {
                "global_search": self._on_global_search_hotkey,
                "floating_search": self._on_floating_search_hotkey,
            },
        )
        self._global_hotkey_active = result.active
        if not result.active:
            self._settings_dialog.set_status("; ".join(result.errors), is_error=True)
            return

        save_config(self.config)
        ai_page = self._pages.get("ai_search")
        if ai_page and hasattr(ai_page, "set_hotkey_status"):
            ai_page.set_hotkey_status(self._global_hotkey_active)
        if ai_page and hasattr(ai_page, "refresh_shortcut_hint"):
            ai_page.refresh_shortcut_hint(
                self.config.ui.global_search_hotkey,
                self.config.ui.floating_search_hotkey,
            )
        creation_page = self._pages.get("creation")
        if creation_page and hasattr(creation_page, "reload_settings"):
            creation_page.reload_settings()
        test_lab = self._pages.get("test_lab")
        if test_lab and hasattr(test_lab, "reload_settings"):
            test_lab.reload_settings()
        self._settings_dialog.close()
        self._settings_dialog = None

    def _shutdown_all(self) -> None:
        svc_page = self._pages.get("services")
        if isinstance(svc_page, ServicesPage):
            for card in svc_page.cards.values():
                card.cancel_timers()

        dash = self._pages.get("dashboard")
        if isinstance(dash, DashboardPage):
            dash.stop_polling()
        pool = self._pages.get("pool")
        if isinstance(pool, AccountPoolPage):
            pool.stop_polling()

        creation = self._pages.get("creation")
        if isinstance(creation, CreationCenterPage):
            creation._client.shutdown()

        self.withdraw()

        def _bg():
            if isinstance(svc_page, ServicesPage):
                for card in svc_page.cards.values():
                    card.shutdown_services()
            self._safe_after(self._finish_shutdown)

        threading.Thread(target=_bg, daemon=True).start()

    def _finish_shutdown(self) -> None:
        if self._floating_window and self._floating_window.winfo_exists():
            self._floating_window.close()
        if self._global_hotkey_active:
            self._hotkeys.clear()
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        import sys
        entry = sys.modules.get("__main__") or sys.modules.get("main_gui")
        if entry and hasattr(entry, "release_instance_lock"):
            entry.release_instance_lock()
        self.destroy()
