from __future__ import annotations

import datetime
import queue
import threading
from pathlib import Path

import customtkinter as ctk

from config import ServiceConfig
from gui.health import HealthChecker
from gui import theme
from gui.widgets.status_badge import StatusBadge
from log_reader import SENTINEL
from preflight import PreflightChecker
from service_manager import ServiceManager, ServiceState

APP_DIR = Path(__file__).resolve().parent.parent.parent


class ServiceCard(ctk.CTkFrame):

    def __init__(self, master, svc_config: ServiceConfig, ui_config,
                 show_count: bool = False):
        super().__init__(
            master, fg_color=theme.get("BG_CARD"),
            corner_radius=theme.CARD_CORNER_RADIUS,
            border_width=theme.CARD_BORDER_WIDTH,
            border_color=theme.get("CARD_BORDER_COLOR"),
        )
        self.svc_config = svc_config
        self.ui_config = ui_config
        self._show_count = show_count
        self._manager: ServiceManager | None = None
        self._health_checker: HealthChecker | None = None
        self._hc_after_id: str | None = None
        self._polling = False
        self._log_lines: list[str] = []
        self._start_time: datetime.datetime | None = None
        self._build_ui()
        theme.on_theme_change(self._apply_theme)

    def _build_ui(self) -> None:
        pad = 16

        # Title row
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(fill="x", padx=pad, pady=(pad, 8))
        self._title_label = ctk.CTkLabel(
            title_frame, text=self.svc_config.name,
            font=theme.font_heading(), text_color=theme.get("TEXT_PRIMARY"),
        )
        self._title_label.pack(side="left")
        self._badge = StatusBadge(title_frame, ServiceState.STOPPED)
        self._badge.pack(side="right")

        # Control row
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=pad, pady=(0, 8))
        self._start_btn = ctk.CTkButton(
            ctrl, text="Start", width=90, height=32,
            fg_color=theme.get("ACCENT_GREEN"), hover_color=theme.get("HOVER_GREEN"),
            text_color=theme.get("TEXT_WHITE"), corner_radius=8,
            command=self._on_start,
        )
        self._start_btn.pack(side="left", padx=(0, 8))
        self._stop_btn = ctk.CTkButton(
            ctrl, text="Stop", width=90, height=32,
            fg_color=theme.get("ACCENT_RED"), hover_color=theme.get("HOVER_RED"),
            text_color=theme.get("TEXT_WHITE"), corner_radius=8,
            command=self._on_stop, state="disabled",
        )
        self._stop_btn.pack(side="left", padx=(0, 8))
        self._restart_btn = ctk.CTkButton(
            ctrl, text="Restart", width=90, height=32,
            fg_color=theme.get("ACCENT_BLUE"), hover_color=theme.get("HOVER_BLUE"),
            text_color=theme.get("TEXT_WHITE"), corner_radius=8,
            command=self._on_restart, state="disabled",
        )
        self._restart_btn.pack(side="left", padx=(0, 12))
        if self._show_count:
            self._count_label = ctk.CTkLabel(
                ctrl, text="Count:", font=theme.font_small(),
                text_color=theme.get("TEXT_SECONDARY"),
            )
            self._count_label.pack(side="left", padx=(8, 4))
            self._count_entry = ctk.CTkEntry(
                ctrl, width=60, height=28, fg_color=theme.get("BG_INPUT"),
                border_width=0, corner_radius=6,
            )
            self._count_entry.insert(0, "5")
            self._count_entry.pack(side="left")
            self._headless_var = ctk.BooleanVar(value=False)
            self._headless_label = ctk.CTkLabel(
                ctrl, text="Headless:", font=theme.font_small(),
                text_color=theme.get("TEXT_SECONDARY"),
            )
            self._headless_label.pack(side="left", padx=(12, 4))
            self._headless_switch = ctk.CTkSwitch(
                ctrl, text="", variable=self._headless_var,
                width=40, height=20,
                progress_color=theme.get("ACCENT_GREEN"),
            )
            self._headless_switch.pack(side="left")
        else:
            self._count_entry = None
            self._headless_var = None
            self._count_label = None
            self._headless_label = None
            self._headless_switch = None

        # Search row
        search = ctk.CTkFrame(self, fg_color="transparent")
        search.pack(fill="x", padx=pad, pady=(0, 8))
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._do_search())
        self._search_entry = ctk.CTkEntry(
            search, textvariable=self._search_var,
            placeholder_text="Search logs...", height=28,
            fg_color=theme.get("BG_INPUT"), border_width=0, corner_radius=6,
        )
        self._search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._match_label = ctk.CTkLabel(
            search, text="", width=70, font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._match_label.pack(side="left", padx=(0, 8))
        self._export_btn = ctk.CTkButton(
            search, text="Export", width=70, height=28,
            fg_color=theme.get("BG_INPUT"), hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_PRIMARY"), corner_radius=6,
            command=self._export_log,
        )
        self._export_btn.pack(side="right")

        # Log box
        self._log_box = ctk.CTkTextbox(
            self, font=theme.font_mono(), fg_color=theme.get("BG_LOG"),
            text_color=theme.get("TEXT_LOG"), state="disabled", wrap="word",
            corner_radius=8,
        )
        self._log_box.pack(fill="both", expand=True, padx=pad, pady=(0, pad))
        self._setup_log_tags()

    # ── State management ──

    @property
    def state(self) -> ServiceState:
        if self._manager:
            return self._manager.state
        return ServiceState.STOPPED

    @property
    def start_time(self) -> datetime.datetime | None:
        return self._start_time

    def _on_state_change(self, new_state: ServiceState) -> None:
        try:
            if self.winfo_exists():
                self.after(0, self._update_state_ui, new_state)
        except RuntimeError:
            pass

    def _update_state_ui(self, state: ServiceState) -> None:
        self._badge.set_state(state)
        can_start = state in (ServiceState.STOPPED, ServiceState.ERROR)
        can_stop = state in (ServiceState.RUNNING, ServiceState.DEGRADED, ServiceState.STARTING)
        self._start_btn.configure(state="normal" if can_start else "disabled")
        self._stop_btn.configure(state="normal" if can_stop else "disabled")
        self._restart_btn.configure(state="normal" if can_stop else "disabled")
        if state == ServiceState.RUNNING and self._start_time is None:
            self._start_time = datetime.datetime.now()
        if state in (ServiceState.STOPPED, ServiceState.ERROR):
            self._polling = False
            self._start_time = None

    # ── Commands ──

    def _get_command(self) -> list[str]:
        cmd = list(self.svc_config.command)
        if self._count_entry:
            val = self._count_entry.get().strip() or "5"
            cmd = [c.replace("{count}", val) for c in cmd]
        if self._headless_var and self._headless_var.get():
            if "--headless" not in cmd:
                cmd.append("--headless")
        return cmd

    def _on_start(self) -> None:
        if self._health_checker:
            self._health_checker.stop()
            self._health_checker = None

        port = None
        if self.svc_config.health_url:
            from urllib.parse import urlparse
            port = urlparse(self.svc_config.health_url).port
        result = PreflightChecker.run_all(self.svc_config, port=port)
        if not result.passed:
            from tkinter import messagebox
            port_blocked = port and any("already in use" in f for f in result.failures)
            if port_blocked:
                kill = messagebox.askyesno(
                    "Port Occupied",
                    f"Port {port} is occupied.\n\n"
                    + "\n".join(result.failures)
                    + "\n\nKill the process occupying this port?",
                )
                if kill:
                    self._kill_port(port)
                    r2 = PreflightChecker.run_all(self.svc_config, port=port)
                    if not r2.passed:
                        messagebox.showwarning("Still Failed", "\n".join(r2.failures))
                        return
                else:
                    return
            else:
                messagebox.showwarning("Preflight Failed", "\n".join(result.failures))
                return

        mgr = ServiceManager(
            name=self.svc_config.name, command=self._get_command(),
            cwd=self.svc_config.cwd, env_extra=self.svc_config.env,
            on_state_change=self._on_state_change,
            port=port,
        )
        self._manager = mgr
        if not mgr.start():
            return
        self._start_polling()
        if self.svc_config.health_url:
            hc = HealthChecker(
                mgr, self.svc_config.health_url,
                interval=self.ui_config.health_check_interval,
                max_failures=self.ui_config.health_check_failures,
            )
            self._health_checker = hc
            self._hc_after_id = self.after(2000, self._start_health_checker)
        else:
            self._hc_after_id = self.after(1000, self._delayed_mark_running)

    def _start_health_checker(self) -> None:
        self._hc_after_id = None
        if self._health_checker:
            self._health_checker.start()

    def _delayed_mark_running(self) -> None:
        self._hc_after_id = None
        if self._manager:
            self._manager.mark_running()

    def _on_stop(self) -> None:
        if self._hc_after_id:
            try:
                self.after_cancel(self._hc_after_id)
            except Exception:
                pass
            self._hc_after_id = None
        if self._health_checker:
            self._health_checker.stop()
            self._health_checker = None
        if self._manager:
            try:
                self._manager.log_queue.put_nowait("[SYSTEM] Stopping service...")
            except queue.Full:
                pass
            threading.Thread(target=self._do_stop, daemon=True).start()

    def _on_restart(self) -> None:
        if self._hc_after_id:
            try:
                self.after_cancel(self._hc_after_id)
            except Exception:
                pass
            self._hc_after_id = None
        if self._health_checker:
            self._health_checker.stop()
            self._health_checker = None

        def _bg():
            self._do_stop()
            import time
            time.sleep(0.5)
            if self.winfo_exists():
                try:
                    self.after(0, self._on_start)
                except RuntimeError:
                    pass

        threading.Thread(target=_bg, daemon=True).start()

    def _do_stop(self) -> None:
        mgr = self._manager
        if mgr is None:
            return
        mgr.stop()

        import time
        if self._wait_for_service_down(timeout=6.0):
            mgr.force_stopped()
            return

        if mgr is self._manager:
            port = self._get_service_port()
            if port and self._is_port_still_listening(port):
                try:
                    mgr.log_queue.put_nowait("[SYSTEM] Port still occupied, force killing...")
                except queue.Full:
                    pass
                mgr._kill_by_port(port)
                time.sleep(0.5)

        if self._wait_for_service_down(timeout=3.0):
            mgr.force_stopped()
            return

        if mgr.state not in (ServiceState.STOPPED, ServiceState.ERROR):
            try:
                mgr.log_queue.put_nowait("[SYSTEM] Graceful stop failed, force killing...")
            except queue.Full:
                pass
            mgr._fallback_kill()
            if self._wait_for_service_down(timeout=6.0):
                mgr.force_stopped()
                return

        try:
            mgr.log_queue.put_nowait("[SYSTEM] Service is still reachable after stop request")
        except queue.Full:
            pass
        mgr.force_error("Service stop verification failed")

    def _get_service_port(self) -> int | None:
        if self.svc_config.health_url:
            from urllib.parse import urlparse
            return urlparse(self.svc_config.health_url).port
        return None

    @staticmethod
    def _is_port_still_listening(port: int) -> bool:
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    def _is_service_reachable(self) -> bool:
        if self.svc_config.health_url:
            import urllib.request
            try:
                req = urllib.request.Request(self.svc_config.health_url, method="GET")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    return 200 <= resp.status < 500
            except Exception:
                pass

        port = self._get_service_port()
        if port:
            return self._is_port_still_listening(port)

        mgr = self._manager
        return bool(mgr and mgr.is_alive())

    def _wait_for_service_down(self, timeout: float) -> bool:
        import time

        deadline = time.time() + max(0.5, timeout)
        while time.time() < deadline:
            if not self._is_service_reachable():
                return True
            time.sleep(0.25)
        return not self._is_service_reachable()

    # ── Log polling ──

    def _start_polling(self) -> None:
        if self._polling:
            return
        self._polling = True
        self._poll_queue()

    def _poll_queue(self) -> None:
        if not self._polling or not self.winfo_exists():
            return
        mgr = self._manager
        if mgr is None:
            self._polling = False
            return
        batch: list[str] = []
        for _ in range(200):
            try:
                item = mgr.log_queue.get_nowait()
                if item is SENTINEL:
                    continue
                batch.append(item)
            except queue.Empty:
                break
        if batch:
            self._append_log(batch)
            if mgr.state == ServiceState.STARTING and not self.svc_config.health_url:
                mgr.mark_running()
        self.after(self.ui_config.poll_interval_ms, self._poll_queue)

    _COLOR_RULES = [
        ("error", "kw_error", "ACCENT_RED"),
        ("fail", "kw_error", "ACCENT_RED"),
        ("exception", "kw_error", "ACCENT_RED"),
        ("traceback", "kw_error", "ACCENT_RED"),
        ("success", "kw_success", "ACCENT_GREEN"),
        ("started", "kw_success", "ACCENT_GREEN"),
        ("running", "kw_success", "ACCENT_GREEN"),
        ("verification", "kw_warn", "ACCENT_YELLOW"),
        ("code", "kw_warn", "ACCENT_YELLOW"),
        ("warning", "kw_warn", "ACCENT_YELLOW"),
        ("[system]", "kw_system", "ACCENT_BLUE"),
        ("[health]", "kw_system", "ACCENT_BLUE"),
    ]

    def _setup_log_tags(self) -> None:
        seen = set()
        for _, tag, color_key in self._COLOR_RULES:
            if tag not in seen:
                self._log_box.tag_config(tag, foreground=theme.get(color_key))
                seen.add(tag)

    def _append_log(self, lines: list[str]) -> None:
        self._log_lines.extend(lines)
        mx = self.ui_config.log_max_lines
        if len(self._log_lines) > mx:
            self._log_lines = self._log_lines[-mx:]
        self._log_box.configure(state="normal")
        for line in lines:
            start_idx = self._log_box.index("end-1c")
            self._log_box.insert("end", line + "\n")
            end_idx = self._log_box.index("end-1c")
            low = line.lower()
            for pattern, tag, _ in self._COLOR_RULES:
                if pattern in low:
                    self._log_box.tag_add(tag, start_idx, end_idx)
                    break
        total = int(self._log_box.index("end-1c").split(".")[0])
        if total > mx:
            self._log_box.delete("1.0", f"{total - mx}.0")
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    # ── Search / Export ──

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
        tb.tag_config("highlight",
                      background=theme.get("HIGHLIGHT_BG"),
                      foreground=theme.get("HIGHLIGHT_FG"))
        self._match_label.configure(text=f"{count} matches")
        tb.configure(state="disabled")

    def _export_log(self) -> None:
        logs_dir = APP_DIR / "logs"
        logs_dir.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = self.svc_config.name.replace(" ", "_").replace("-", "_")
        path = logs_dir / f"{name}_{ts}.log"
        path.write_text("\n".join(self._log_lines), encoding="utf-8")
        from tkinter import messagebox
        messagebox.showinfo("Export", f"Log exported to:\n{path}")

    # ── Theme ──

    def _apply_theme(self) -> None:
        self.configure(
            fg_color=theme.get("BG_CARD"),
            border_color=theme.get("CARD_BORDER_COLOR"),
        )
        self._title_label.configure(text_color=theme.get("TEXT_PRIMARY"))
        self._start_btn.configure(
            fg_color=theme.get("ACCENT_GREEN"), hover_color=theme.get("HOVER_GREEN"),
        )
        self._stop_btn.configure(
            fg_color=theme.get("ACCENT_RED"), hover_color=theme.get("HOVER_RED"),
        )
        self._restart_btn.configure(
            fg_color=theme.get("ACCENT_BLUE"), hover_color=theme.get("HOVER_BLUE"),
        )
        self._search_entry.configure(fg_color=theme.get("BG_INPUT"))
        self._match_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._export_btn.configure(
            fg_color=theme.get("BG_INPUT"), hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._log_box.configure(
            fg_color=theme.get("BG_LOG"), text_color=theme.get("TEXT_LOG"),
        )
        self._setup_log_tags()
        if self._count_entry:
            self._count_entry.configure(fg_color=theme.get("BG_INPUT"))
        if self._count_label:
            self._count_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        if self._headless_label:
            self._headless_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        if self._headless_switch:
            self._headless_switch.configure(progress_color=theme.get("ACCENT_GREEN"))

    # ── Lifecycle ──

    def cancel_timers(self) -> None:
        self._polling = False
        if self._hc_after_id:
            try:
                self.after_cancel(self._hc_after_id)
            except Exception:
                pass
            self._hc_after_id = None

    def shutdown_services(self) -> None:
        if self._health_checker:
            self._health_checker.stop()
            self._health_checker = None
        if self._manager and self._manager.state != ServiceState.STOPPED:
            self._do_stop()

    def shutdown(self) -> None:
        self.cancel_timers()
        self.shutdown_services()

    def destroy(self):
        theme.remove_listener(self._apply_theme)
        super().destroy()
