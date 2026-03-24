from __future__ import annotations

import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from config import AppConfig
from gui import theme
from gui.utils.grok_search_client import GrokSearchClient
from gui.utils.media_gen_client import MediaGenClient
from gui.utils.media_storage import MediaStorage
from gui.utils.prompt_enhancer_client import PromptEnhancerClient
from gui.utils.run_recorder import get_run_recorder
from gui.utils.test_lab_presets import PRESETS, FeaturePreset


class TestLabPage(ctk.CTkFrame):

    def __init__(self, master, config: AppConfig):
        super().__init__(master, fg_color=theme.get("BG_ROOT"))
        self._config = config
        self._root_dir = Path(__file__).resolve().parent.parent.parent
        self._storage = MediaStorage(base_dir=config.ui.default_output_dir or str(self._root_dir))
        self._search = GrokSearchClient()
        self._enhancer = PromptEnhancerClient()
        self._media = MediaGenClient(master=self)
        self._selected: FeaturePreset = PRESETS[0]

        self._build_ui()
        theme.on_theme_change(self._apply_theme)
        self._render_preset()
        self._refresh_recent_runs()

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 12))
        self._title = ctk.CTkLabel(
            header, text="Test Lab", font=theme.font_heading(18), text_color=theme.get("TEXT_PRIMARY")
        )
        self._title.pack(side="left")
        self._refresh_btn = ctk.CTkButton(
            header,
            text="Refresh",
            width=86,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            corner_radius=6,
            command=self._refresh_recent_runs,
        )
        self._refresh_btn.pack(side="right")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._preset_list = ctk.CTkScrollableFrame(body, width=240, fg_color=theme.get("BG_CARD"))
        self._preset_list.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self._preset_buttons: list[ctk.CTkButton] = []
        for preset in PRESETS:
            btn = ctk.CTkButton(
                self._preset_list,
                text=preset.title,
                anchor="w",
                fg_color="transparent",
                hover_color=theme.get("HOVER_GENERIC"),
                text_color=theme.get("TEXT_SECONDARY"),
                corner_radius=6,
                command=lambda value=preset: self._select_preset(value),
            )
            btn.pack(fill="x", pady=2)
            self._preset_buttons.append(btn)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(5, weight=1)

        self._preset_title = ctk.CTkLabel(right, text="", font=theme.font_heading(16), text_color=theme.get("TEXT_PRIMARY"))
        self._preset_title.grid(row=0, column=0, sticky="w")
        self._preset_meta = ctk.CTkLabel(right, text="", font=theme.font_small(), text_color=theme.get("TEXT_SECONDARY"))
        self._preset_meta.grid(row=1, column=0, sticky="ew", pady=(4, 10))

        self._prompt_box = ctk.CTkTextbox(
            right,
            height=120,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_body(),
            corner_radius=8,
        )
        self._prompt_box.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew")
        self._run_btn = ctk.CTkButton(
            actions,
            text="Run Preset",
            fg_color=theme.get("ACCENT_PURPLE"),
            hover_color=theme.get("HOVER_PURPLE"),
            text_color=theme.get("TEXT_WHITE"),
            corner_radius=6,
            command=self._run_selected,
        )
        self._run_btn.pack(side="left")

        self._status = ctk.CTkLabel(right, text="", font=theme.font_small(), text_color=theme.get("TEXT_SECONDARY"))
        self._status.grid(row=4, column=0, sticky="ew", pady=(12, 6))

        self._result_box = ctk.CTkTextbox(
            right,
            fg_color=theme.get("BG_CARD"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_body(),
            corner_radius=8,
        )
        self._result_box.grid(row=5, column=0, sticky="nsew")

        self._recent_label = ctk.CTkLabel(
            right, text="Recent Runs", font=theme.font_small(), text_color=theme.get("TEXT_SECONDARY")
        )
        self._recent_label.grid(row=6, column=0, sticky="w", pady=(12, 4))
        self._recent_box = ctk.CTkTextbox(
            right,
            height=110,
            fg_color=theme.get("BG_CARD"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_mono(),
            corner_radius=8,
        )
        self._recent_box.grid(row=7, column=0, sticky="ew")

    def reload_settings(self) -> None:
        base_dir = self._config.ui.default_output_dir or str(self._root_dir)
        self._storage = MediaStorage(base_dir=base_dir)

    def _select_preset(self, preset: FeaturePreset) -> None:
        self._selected = preset
        self._render_preset()

    def _render_preset(self) -> None:
        self._preset_title.configure(text=self._selected.title)
        self._preset_meta.configure(
            text=(
                f"Feature: {self._selected.feature} | Model: {self._selected.model} | "
                f"Web: {'on' if self._selected.web_enabled else 'off'} | Tags: {', '.join(self._selected.tags)}"
            )
        )
        self._prompt_box.delete("1.0", "end")
        self._prompt_box.insert("1.0", self._selected.prompt)
        for button, preset in zip(self._preset_buttons, PRESETS):
            active = preset.preset_id == self._selected.preset_id
            button.configure(
                fg_color=theme.get("ACCENT_BLUE") if active else "transparent",
                text_color=theme.get("TEXT_WHITE") if active else theme.get("TEXT_SECONDARY"),
                hover_color=theme.get("HOVER_BLUE") if active else theme.get("HOVER_GENERIC"),
            )

    def _run_selected(self) -> None:
        prompt = self._prompt_box.get("1.0", "end").strip()
        if not prompt:
            return
        self._status.configure(text="Running preset...", text_color=theme.get("TEXT_SECONDARY"))
        self._result_box.delete("1.0", "end")
        feature = self._selected.feature

        if feature == "search":
            self._search.search(
                query=prompt,
                mode=self._selected.mode,
                web_enabled=self._selected.web_enabled,
                history=[],
                source="test_lab",
                feature="search",
                on_chunk=lambda chunk: self.after(0, self._append_result, chunk),
                on_done=lambda result: self.after(0, self._finish_result, result),
                on_error=lambda msg: self.after(0, self._show_error, msg),
            )
            return

        if feature == "prompt_enhance_image":
            self._enhancer.enhance(
                mode="image",
                text=prompt,
                source="test_lab",
                feature="prompt_enhance",
                on_done=lambda result: self.after(0, self._finish_result, result),
                on_error=lambda msg: self.after(0, self._show_error, msg),
            )
            return

        if feature == "image_generation":
            self._media.generate_image(
                prompt=prompt,
                on_status=lambda msg: self.after(0, self._set_status, msg),
                on_success=lambda url, kind: self.after(0, self._save_media_result, url, kind, prompt),
                on_error=lambda msg: self.after(0, self._show_error, msg),
            )
            return

        if feature == "image_edit":
            source_entry = next((item for item in self._storage.get_history() if item.get("type") == "image"), None)
            if not source_entry:
                messagebox.showwarning("Test Lab", "Please generate at least one image before running the image edit preset.")
                return
            self._media.edit_image(
                prompt=prompt,
                image_url=source_entry.get("url", ""),
                on_status=lambda msg: self.after(0, self._set_status, msg),
                on_success=lambda url, kind: self.after(0, self._save_media_result, url, kind, prompt, source_entry),
                on_error=lambda msg: self.after(0, self._show_error, msg),
            )
            return

        if feature == "video_generation":
            source_entry = next((item for item in self._storage.get_history() if item.get("type") == "image"), None)
            ref = source_entry.get("url", "") if source_entry else None
            self._media.generate_video(
                prompt=prompt,
                image_ref=ref,
                on_status=lambda msg: self.after(0, self._set_status, msg),
                on_success=lambda url, kind: self.after(0, self._save_media_result, url, kind, prompt),
                on_error=lambda msg: self.after(0, self._show_error, msg),
            )

    def _set_status(self, text: str) -> None:
        self._status.configure(text=text, text_color=theme.get("TEXT_SECONDARY"))

    def _append_result(self, text: str) -> None:
        self._result_box.insert("end", text)
        self._result_box.see("end")

    def _finish_result(self, result: str) -> None:
        self._status.configure(text="Completed", text_color=theme.get("TEXT_SECONDARY"))
        self._result_box.delete("1.0", "end")
        self._result_box.insert("1.0", result)
        self._refresh_recent_runs()

    def _show_error(self, message: str) -> None:
        self._status.configure(text=f"Error: {message}", text_color=theme.get("ACCENT_RED"))
        self._refresh_recent_runs()

    def _save_media_result(self, url: str, kind: str, prompt: str, parent_entry: dict | None = None) -> None:
        self._status.configure(text="Saving output...", text_color=theme.get("TEXT_SECONDARY"))

        def _bg() -> None:
            if kind == "video":
                entry = self._storage.save_video(
                    url,
                    prompt,
                    model="grok-imagine-1.0-video",
                    feature="video_generation",
                    source="test_lab",
                    tags=list(self._selected.tags),
                )
            else:
                entry = self._storage.save_image(
                    url,
                    prompt,
                    mode="image_edit" if parent_entry else "image",
                    parent_url=parent_entry.get("url", "") if parent_entry else "",
                    parent_path=parent_entry.get("path", "") if parent_entry else "",
                    model="grok-imagine-1.0-edit" if parent_entry else "grok-imagine-1.0",
                    feature="image_edit" if parent_entry else "image_generation",
                    source="test_lab",
                    tags=list(self._selected.tags),
                )
            if entry and self._media.current_run_id:
                get_run_recorder().annotate_run(
                    self._media.current_run_id,
                    output_path=entry.get("path"),
                    metadata={"preset_id": self._selected.preset_id},
                )
            self.after(0, self._finish_saved_media, entry)

        threading.Thread(target=_bg, daemon=True).start()

    def _finish_saved_media(self, entry: dict | None) -> None:
        if not entry:
            self._show_error("Failed to save output")
            return
        self._status.configure(text=f"Saved: {entry['path']}", text_color=theme.get("TEXT_SECONDARY"))
        self._result_box.delete("1.0", "end")
        self._result_box.insert("1.0", str(entry["path"]))
        self._refresh_recent_runs()

    def _refresh_recent_runs(self) -> None:
        records = get_run_recorder().load_recent(8)
        self._recent_box.delete("1.0", "end")
        for record in records:
            line = (
                f"{record.timestamp} | {record.feature} | {record.source} | "
                f"{'OK' if record.success else 'FAIL'} | {record.duration_ms}ms"
            )
            self._recent_box.insert("end", line + "\n")

    def _apply_theme(self) -> None:
        self.configure(fg_color=theme.get("BG_ROOT"))
        self._title.configure(text_color=theme.get("TEXT_PRIMARY"))
        self._preset_meta.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._status.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._recent_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._prompt_box.configure(fg_color=theme.get("BG_INPUT"), text_color=theme.get("TEXT_PRIMARY"))
        self._result_box.configure(fg_color=theme.get("BG_CARD"), text_color=theme.get("TEXT_PRIMARY"))
        self._recent_box.configure(fg_color=theme.get("BG_CARD"), text_color=theme.get("TEXT_PRIMARY"))
        self._refresh_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._run_btn.configure(
            fg_color=theme.get("ACCENT_PURPLE"),
            hover_color=theme.get("HOVER_PURPLE"),
            text_color=theme.get("TEXT_WHITE"),
        )
        self._preset_list.configure(fg_color=theme.get("BG_CARD"))
        self._render_preset()

    def destroy(self) -> None:
        theme.remove_listener(self._apply_theme)
        self._search.cancel()
        self._enhancer.cancel()
        self._media.shutdown()
        super().destroy()
