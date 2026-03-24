from __future__ import annotations

import logging
import os
import sys
import threading
import zipfile
from pathlib import Path
from tkinter import filedialog
from typing import Any, Optional

import customtkinter as ctk
from PIL import Image as PILImage

from gui import theme
from gui.utils.clipboard_image import copy_image_to_clipboard
from gui.utils.media_gen_client import MediaGenClient
from gui.utils.media_storage import MediaStorage
from gui.utils.platform import open_path
from gui.utils.prompt_enhancer_client import PromptEnhancerClient
from gui.utils.run_recorder import get_run_recorder
from gui.utils.task_registry import get_task_registry
from gui.widgets.prompt_enhance_dialog import PromptEnhanceDialog

logger = logging.getLogger(__name__)

_SIZES = ["1280x720", "720x1280", "1792x1024", "1024x1792", "1024x1024"]
_QUALITIES = ["standard", "high"]
_PREVIEW_MAX_W = 600
_PREVIEW_MAX_H = 400
_HIST_COLS = 4
_HIST_THUMB = 120


class CreationCenterPage(ctk.CTkFrame):

    def __init__(self, master, config=None):
        super().__init__(master, fg_color=theme.get("BG_ROOT"))

        self._config = config
        self._root_dir = Path(__file__).resolve().parent.parent.parent
        self._client = MediaGenClient(master=self)
        base_dir = config.ui.default_output_dir if config and config.ui.default_output_dir else str(self._root_dir)
        self._storage = MediaStorage(base_dir=base_dir)

        self._page_mode = "image"
        self._run_mode = "image"
        self._generating = False
        self._enhancing = False
        self._current_entry: Optional[dict] = None
        self._edit_source_entry: Optional[dict] = None
        self._hist_widgets: list[ctk.CTkFrame] = []
        self._hist_images: list[Any] = []
        self._preview_image: Any = None
        self._enhancer = PromptEnhancerClient()
        self._enhance_original_text = ""
        self._enhance_candidate = ""
        self._enhance_dialog: PromptEnhanceDialog | None = None
        self._applied_original_prompt = ""
        self._applied_enhanced_prompt = ""
        self._active_task_id = ""

        self._build_ui()
        theme.on_theme_change(self._apply_theme)

    # ── UI construction ──

    def _build_ui(self) -> None:
        self._left = ctk.CTkFrame(
            self, width=320, fg_color=theme.get("BG_CARD"), corner_radius=0,
        )
        self._left.pack(side="left", fill="y")
        self._left.pack_propagate(False)

        self._right = ctk.CTkFrame(
            self, fg_color=theme.get("BG_ROOT"), corner_radius=0,
        )
        self._right.pack(side="right", fill="both", expand=True)

        self._build_left()
        self._build_right()

    def _build_left(self) -> None:
        left = self._left
        px = 16

        # Mode switch
        self._mode_seg = ctk.CTkSegmentedButton(
            left, values=["图片", "视频"],
            command=self._on_mode_change,
            selected_color=theme.get("ACCENT_PURPLE"),
            selected_hover_color=theme.get("HOVER_PURPLE"),
            font=theme.font_body(),
        )
        self._mode_seg.set("图片")
        self._mode_seg.pack(fill="x", padx=px, pady=(16, 12))

        # Prompt
        prompt_header = ctk.CTkFrame(left, fg_color="transparent")
        prompt_header.pack(fill="x", padx=px)
        self._prompt_label = ctk.CTkLabel(
            prompt_header, text="Prompt",
            font=theme.font_small(), text_color=theme.get("TEXT_SECONDARY"),
            anchor="w",
        )
        self._prompt_label.pack(side="left")
        self._enhance_btn = ctk.CTkButton(
            prompt_header, text="✨ 智能润色", width=90, height=28,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=self._do_enhance_prompt,
        )
        self._enhance_btn.pack(side="right")
        self._enhance_btn.configure(text="\u2728 \u667a\u80fd\u6da6\u8272")

        self._prompt = ctk.CTkTextbox(
            left, height=100,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_body(), corner_radius=8,
        )
        self._prompt.pack(fill="x", padx=px, pady=(4, 12))
        self._prompt.bind("<KeyPress>", self._on_key)

        # Size
        sf = ctk.CTkFrame(left, fg_color="transparent")
        sf.pack(fill="x", padx=px, pady=(0, 8))
        ctk.CTkLabel(
            sf, text="Size", font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        ).pack(side="left")
        self._size_var = ctk.StringVar(value="1024x1024")
        self._size_dd = ctk.CTkComboBox(
            sf, values=_SIZES, variable=self._size_var,
            width=160, height=28,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_small(), corner_radius=6, state="readonly",
        )
        self._size_dd.pack(side="right")

        self._mode_hint = ctk.CTkLabel(
            left, text="", anchor="w", wraplength=288, justify="left",
            font=theme.font_small(), text_color=theme.get("ACCENT_YELLOW"),
        )
        self._mode_hint.pack(fill="x", padx=px, pady=(0, 8))

        # ── Mode-specific container (grid_remove / grid) ──
        self._mode_ctr = ctk.CTkFrame(left, fg_color="transparent")
        self._mode_ctr.pack(fill="x", padx=px, pady=(0, 8))
        self._mode_ctr.columnconfigure(0, weight=1)

        self._build_image_controls()
        self._build_video_controls()
        self._video_ctr.grid_remove()

        # NSFW
        nf = ctk.CTkFrame(left, fg_color="transparent")
        nf.pack(fill="x", padx=px, pady=(0, 12))
        self._nsfw_var = ctk.BooleanVar(value=False)
        self._nsfw_sw = ctk.CTkSwitch(
            nf, text="NSFW", variable=self._nsfw_var,
            font=theme.font_small(), text_color=theme.get("TEXT_SECONDARY"),
        )
        self._nsfw_sw.pack(side="left")

        # Action buttons
        bf = ctk.CTkFrame(left, fg_color="transparent")
        bf.pack(fill="x", padx=px, pady=(0, 8))

        self._gen_btn = ctk.CTkButton(
            bf, text="生成", height=36,
            fg_color=theme.get("ACCENT_PURPLE"),
            hover_color=theme.get("HOVER_PURPLE"),
            text_color=theme.get("TEXT_WHITE"),
            font=theme.font_body(), corner_radius=8,
            command=self._do_generate,
        )
        self._gen_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self._stop_btn = ctk.CTkButton(
            bf, text="停止", height=36,
            fg_color=theme.get("ACCENT_RED"),
            hover_color=theme.get("HOVER_RED"),
            text_color=theme.get("TEXT_WHITE"),
            font=theme.font_body(), corner_radius=8,
            command=self._do_stop, state="disabled",
        )
        self._stop_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # Spacer
        ctk.CTkFrame(left, fg_color="transparent", height=1).pack(
            fill="both", expand=True,
        )

        self._open_outputs_btn = ctk.CTkButton(
            left, text="📂 打开输出目录", height=30,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=self._open_outputs_dir,
        )
        self._open_outputs_btn.pack(fill="x", padx=px, pady=(0, 8))
        self._open_outputs_btn.configure(text="\U0001f4c2 \u6253\u5f00\u8f93\u51fa\u76ee\u5f55")

        # Clear cache
        self._clear_btn = ctk.CTkButton(
            left, text="清理缓存", height=28,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=self._do_clear_cache,
        )
        self._clear_btn.pack(fill="x", padx=px, pady=(0, 16))

    def _build_image_controls(self) -> None:
        self._image_ctr = ctk.CTkFrame(self._mode_ctr, fg_color="transparent")
        self._image_ctr.grid(row=0, column=0, sticky="ew")

        # Concurrency
        cf = ctk.CTkFrame(self._image_ctr, fg_color="transparent")
        cf.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            cf, text="Concurrency", font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        ).pack(side="left")
        self._cc_val = ctk.CTkLabel(
            cf, text="5", font=theme.font_small(),
            text_color=theme.get("TEXT_PRIMARY"), width=30,
        )
        self._cc_val.pack(side="right")

        self._cc_slider = ctk.CTkSlider(
            self._image_ctr, from_=1, to=20, number_of_steps=19,
            command=lambda v: self._cc_val.configure(text=str(int(v))),
        )
        self._cc_slider.set(5)
        self._cc_slider.pack(fill="x", pady=(0, 8))

        # Retries
        rf = ctk.CTkFrame(self._image_ctr, fg_color="transparent")
        rf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            rf, text="Max Retries", font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        ).pack(side="left")
        self._retry_var = ctk.StringVar(value="1")
        self._retry_entry = ctk.CTkEntry(
            rf, textvariable=self._retry_var, width=60, height=28,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_small(), corner_radius=6,
        )
        self._retry_entry.pack(side="right")

    def _build_video_controls(self) -> None:
        self._video_ctr = ctk.CTkFrame(self._mode_ctr, fg_color="transparent")
        self._video_ctr.grid(row=0, column=0, sticky="ew")

        # Duration
        df = ctk.CTkFrame(self._video_ctr, fg_color="transparent")
        df.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            df, text="Duration (s)", font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        ).pack(side="left")
        self._dur_val = ctk.CTkLabel(
            df, text="6", font=theme.font_small(),
            text_color=theme.get("TEXT_PRIMARY"), width=30,
        )
        self._dur_val.pack(side="right")

        self._dur_slider = ctk.CTkSlider(
            self._video_ctr, from_=6, to=30, number_of_steps=24,
            command=lambda v: self._dur_val.configure(text=str(int(v))),
        )
        self._dur_slider.set(6)
        self._dur_slider.pack(fill="x", pady=(0, 8))

        # Quality
        qf = ctk.CTkFrame(self._video_ctr, fg_color="transparent")
        qf.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            qf, text="Quality", font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        ).pack(side="left")
        self._quality_var = ctk.StringVar(value="standard")
        self._quality_dd = ctk.CTkComboBox(
            qf, values=_QUALITIES, variable=self._quality_var,
            width=120, height=28,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_small(), corner_radius=6, state="readonly",
        )
        self._quality_dd.pack(side="right")

        # Ref image
        rif = ctk.CTkFrame(self._video_ctr, fg_color="transparent")
        rif.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            rif, text="Ref Image", font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        ).pack(side="left")
        self._ref_var = ctk.StringVar(value="")
        self._ref_entry = ctk.CTkEntry(
            rif, textvariable=self._ref_var, height=28,
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
            font=theme.font_small(), corner_radius=6,
            placeholder_text="Image URL (optional)",
        )
        self._ref_entry.pack(side="right", fill="x", expand=True, padx=(8, 0))

    def _build_right(self) -> None:
        r = self._right

        # Status
        self._status_lbl = ctk.CTkLabel(
            r, text="", font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._status_lbl.pack(pady=(8, 4))

        # Preview
        self._preview_frame = ctk.CTkFrame(
            r, fg_color=theme.get("BG_CARD"),
            corner_radius=theme.CARD_CORNER_RADIUS,
        )
        self._preview_frame.pack(fill="both", expand=True, padx=24, pady=(4, 8))

        self._preview_lbl = ctk.CTkLabel(
            self._preview_frame,
            text="\u5728\u5de6\u4fa7\u914d\u7f6e\u53c2\u6570\u5e76\u70b9\u51fb\u201c\u751f\u6210\u201d\u5f00\u59cb",
            font=theme.font_body(), text_color=theme.get("TEXT_MUTED"),
        )
        self._preview_lbl.pack(expand=True)

        # Action bar
        self._action_bar = ctk.CTkFrame(r, fg_color="transparent")
        self._action_bar.pack(fill="x", padx=24, pady=(0, 4))
        self._visible_action_buttons: list[ctk.CTkButton] = []
        self._action_bar.bind("<Configure>", self._on_action_bar_resize)

        self._edit_btn = ctk.CTkButton(
            self._action_bar, text="🪄 局部微调",
            height=28,
            fg_color=theme.get("ACCENT_PURPLE"),
            hover_color=theme.get("HOVER_PURPLE"),
            text_color=theme.get("TEXT_WHITE"),
            font=theme.font_small(), corner_radius=6,
            command=self._toggle_edit_mode,
        )

        self._export_btn = ctk.CTkButton(
            self._action_bar, text="导出 PNG",
            height=28,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=self._export_png,
        )

        self._copy_btn = ctk.CTkButton(
            self._action_bar, text="复制图片",
            height=28,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=self._copy_current_image,
        )

        self._i2v_btn = ctk.CTkButton(
            self._action_bar, text="\U0001f3ac \u8f6c\u4e3a\u89c6\u9891",
            height=28,
            fg_color=theme.get("ACCENT_PURPLE"),
            hover_color=theme.get("HOVER_PURPLE"),
            text_color=theme.get("TEXT_WHITE"),
            font=theme.font_small(), corner_radius=6,
            command=self._img_to_video,
        )

        self._open_vid_btn = ctk.CTkButton(
            self._action_bar,
            text="\u5728\u64ad\u653e\u5668\u4e2d\u6253\u5f00",
            height=28,
            fg_color=theme.get("ACCENT_BLUE"),
            hover_color=theme.get("HOVER_BLUE"),
            text_color=theme.get("TEXT_WHITE"),
            font=theme.font_small(), corner_radius=6,
            command=self._open_current_video,
        )
        self._compare_btn = ctk.CTkButton(
            self._action_bar, text="对比原图",
            height=28,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=self._compare_with_parent,
        )
        self._revert_btn = ctk.CTkButton(
            self._action_bar, text="回退上一版",
            height=28,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=self._revert_to_parent,
        )
        self._bundle_btn = ctk.CTkButton(
            self._action_bar, text="导出素材包",
            height=28,
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
            font=theme.font_small(), corner_radius=6,
            command=self._export_artifact_bundle,
        )

        # History
        self._hist_lbl = ctk.CTkLabel(
            r, text="History", font=theme.font_small(),
            text_color=theme.get("TEXT_SECONDARY"), anchor="w",
        )
        self._hist_lbl.pack(fill="x", padx=24, pady=(4, 2))

        self._hist_scroll = ctk.CTkScrollableFrame(
            r, height=160, fg_color=theme.get("BG_CARD"),
            corner_radius=theme.CARD_CORNER_RADIUS,
        )
        self._hist_scroll.pack(fill="x", padx=24, pady=(0, 16))
        for c in range(_HIST_COLS):
            self._hist_scroll.columnconfigure(c, weight=1)

        self._refresh_history()
        self._sync_action_buttons()
        self._edit_btn.configure(text="\U0001fa84 \u5c40\u90e8\u5fae\u8c03")

    # ── Mode switching ──

    def _on_mode_change(self, value: str) -> None:
        self._page_mode = "image" if value == "\u56fe\u7247" else "video"
        if self._page_mode == "video":
            self._exit_edit_mode()
            self._run_mode = "video"
            self._image_ctr.grid_remove()
            self._video_ctr.grid(row=0, column=0, sticky="ew")
            self._mode_hint.configure(text="")
        else:
            self._run_mode = "image" if self._run_mode != "image_edit" else "image_edit"
            self._video_ctr.grid_remove()
            self._image_ctr.grid(row=0, column=0, sticky="ew")
            if self._run_mode == "image_edit" and self._edit_source_entry:
                self._cc_slider.configure(state="disabled")
                self._mode_hint.configure(
                    text=f"当前处于图片微调模式，将基于当前图片继续编辑：{self._edit_source_entry.get('filename', '')}"
                )
            else:
                self._cc_slider.configure(state="normal")
                self._mode_hint.configure(text="")
        self._sync_action_buttons()

    # ── Input handling ──

    def _on_key(self, event) -> Optional[str]:
        if event.keysym == "Return":
            if event.state & 0x1:
                return None
            self.after_idle(self._do_generate)
            return "break"
        return None

    def _get_prompt(self) -> str:
        return self._prompt.get("1.0", "end-1c").strip()

    # ── Generation ──

    def _do_generate(self) -> None:
        prompt = self._get_prompt()
        if not prompt or self._generating:
            return

        size = self._size_var.get()

        try:
            retries = max(0, int(self._retry_var.get() or "1"))
        except (ValueError, TypeError):
            retries = 1

        self._set_generating(True)
        feature = "image_edit" if self._run_mode == "image_edit" else ("image_generation" if self._page_mode == "image" else "video_generation")
        self._active_task_id = get_task_registry().start_task(
            label="Creation Center",
            feature=feature,
            source="manual",
            cancel=self._do_stop,
        )

        if self._run_mode == "image_edit":
            if not self._edit_source_entry:
                self._set_generating(False)
                self._set_status("错误: 当前没有可微调的图片")
                return
            self._client.edit_image(
                prompt=prompt, image_url=self._edit_source_entry.get("url", ""),
                size=size, max_retries=retries,
                on_status=self._on_status,
                on_success=self._on_success,
                on_error=self._on_error,
            )
        elif self._page_mode == "image":
            nsfw = True if self._nsfw_var.get() else None
            self._client.generate_image(
                prompt=prompt, size=size,
                concurrency=int(self._cc_slider.get()),
                max_retries=retries,
                enable_nsfw=nsfw,
                on_status=self._on_status,
                on_success=self._on_success,
                on_error=self._on_error,
            )
        else:
            ref = self._ref_var.get().strip() or None
            self._client.generate_video(
                prompt=prompt, size=size,
                seconds=int(self._dur_slider.get()),
                quality=self._quality_var.get(),
                image_ref=ref,
                on_status=self._on_status,
                on_success=self._on_success,
                on_error=self._on_error,
            )

    def _do_stop(self) -> None:
        self._client.cancel()
        self._set_generating(False)
        self._set_status("\u5df2\u505c\u6b62")
        if self._active_task_id:
            get_task_registry().finish_task(self._active_task_id, status="cancelled", message="已取消")
            self._active_task_id = ""

    def _set_generating(self, active: bool) -> None:
        self._generating = active
        self._gen_btn.configure(state="disabled" if active else "normal")
        self._stop_btn.configure(state="normal" if active else "disabled")
        self._enhance_btn.configure(
            state="disabled" if active or self._enhancing else "normal"
        )

    # ── Callbacks (already on UI thread via _safe_after) ──

    def _on_status(self, msg: str) -> None:
        self._set_status(msg)
        if self._active_task_id:
            get_task_registry().update_task(self._active_task_id, msg)

    def _on_success(self, url: str, media_type: str) -> None:
        self._set_status("\u6b63\u5728\u4fdd\u5b58\u5230\u672c\u5730...")
        self._set_generating(False)
        prompt = self._get_prompt()
        run_mode = self._run_mode
        parent_url = ""
        parent_path = ""
        if run_mode == "image_edit" and self._edit_source_entry:
            parent_url = self._edit_source_entry.get("url", "")
            parent_path = self._edit_source_entry.get("path", "")
        threading.Thread(
            target=self._save_and_display,
            args=(url, media_type, prompt, run_mode, parent_url, parent_path),
            daemon=True,
        ).start()

    def _on_error(self, msg: str) -> None:
        self._set_generating(False)
        self._set_status(f"\u9519\u8bef: {msg}")
        if self._active_task_id:
            get_task_registry().finish_task(self._active_task_id, status="error", message=msg)
            self._active_task_id = ""

    # ── Save & display ──

    def _save_and_display(
        self,
        url: str,
        mtype: str,
        prompt: str,
        run_mode: str,
        parent_url: str,
        parent_path: str,
    ) -> None:
        prompt_meta = self._build_prompt_metadata(prompt)
        entry = (
            self._storage.save_image(
                url, prompt,
                mode=run_mode,
                parent_url=parent_url,
                parent_path=parent_path,
                raw_prompt=prompt_meta["raw_prompt"],
                enhanced_prompt=prompt_meta["enhanced_prompt"],
                model=self._resolve_model_name(run_mode, mtype),
                feature="image_edit" if run_mode == "image_edit" else "image_generation",
                tags=["safe"],
            )
            if mtype == "image"
            else self._storage.save_video(
                url,
                prompt,
                raw_prompt=prompt_meta["raw_prompt"],
                enhanced_prompt=prompt_meta["enhanced_prompt"],
                model=self._resolve_model_name(run_mode, mtype),
                feature="video_generation",
                tags=["safe"],
            )
        )
        try:
            if entry:
                get_run_recorder().annotate_run(
                    self._client.current_run_id,
                    output_path=entry.get("path", ""),
                    output_url=entry.get("url", ""),
                    metadata={
                        "feature": entry.get("feature", ""),
                        "mode": entry.get("mode", ""),
                        "parent_path": entry.get("parent_path", ""),
                    },
                    tags=entry.get("tags", []),
                )
                self.after(0, self._display_result, entry)
            else:
                self.after(0, self._set_status, "\u4fdd\u5b58\u5931\u8d25")
        except Exception:
            pass

    def _display_result(self, entry: dict) -> None:
        self._current_entry = entry
        if self._active_task_id:
            get_task_registry().finish_task(self._active_task_id, status="success", message="完成")
            self._active_task_id = ""

        if entry["type"] == "image":
            self._load_preview(entry["path"])
            if self._run_mode == "image_edit":
                self._edit_source_entry = entry
        else:
            self._preview_lbl.configure(
                image=None, text=f"\U0001f3ac {entry['filename']}",
            )
            self._preview_image = None

        self._set_status("" if self._run_mode != "image_edit" else "当前处于图片微调模式")
        self._sync_action_buttons()
        self._refresh_history()

    def _build_prompt_metadata(self, prompt: str) -> dict[str, str]:
        if self._applied_enhanced_prompt and prompt == self._applied_enhanced_prompt:
            return {
                "raw_prompt": self._applied_original_prompt,
                "enhanced_prompt": self._applied_enhanced_prompt,
            }
        return {"raw_prompt": prompt, "enhanced_prompt": ""}

    @staticmethod
    def _resolve_model_name(run_mode: str, media_type: str) -> str:
        if media_type == "video":
            return "grok-imagine-1.0-video"
        if run_mode == "image_edit":
            return "grok-imagine-1.0-edit"
        return "grok-imagine-1.0"

    def _load_preview(self, path: str) -> None:
        try:
            pil_img = PILImage.open(path)
            pw = max(self._preview_frame.winfo_width() - 40, _PREVIEW_MAX_W)
            ph = max(self._preview_frame.winfo_height() - 40, _PREVIEW_MAX_H)
            w, h = pil_img.size
            ratio = min(pw / w, ph / h, 1.0)
            dw, dh = int(w * ratio), int(h * ratio)

            img = ctk.CTkImage(
                light_image=pil_img, dark_image=pil_img, size=(dw, dh),
            )
            self._preview_lbl.configure(image=img, text="")
            self._preview_image = img
        except Exception:
            logger.exception("Preview load failed: %s", path)
            self._preview_lbl.configure(image=None, text="\u9884\u89c8\u52a0\u8f7d\u5931\u8d25")

    def _sync_action_buttons(self) -> None:
        for btn in (
            self._edit_btn,
            self._export_btn,
            self._copy_btn,
            self._i2v_btn,
            self._open_vid_btn,
            self._compare_btn,
            self._revert_btn,
            self._bundle_btn,
        ):
            btn.grid_forget()

        self._visible_action_buttons = []

        if not self._current_entry:
            return

        if self._current_entry["type"] == "image":
            self._edit_btn.configure(
                text="退出微调" if self._run_mode == "image_edit" else "🪄 局部微调"
            )
            self._edit_btn.pack(side="left", padx=(0, 4))
            self._edit_btn.configure(
                text=(
                    "\u9000\u51fa\u5fae\u8c03"
                    if self._run_mode == "image_edit"
                    else "\U0001fa84 \u5c40\u90e8\u5fae\u8c03"
                )
            )
            self._visible_action_buttons.extend(
                [self._edit_btn, self._export_btn]
            )
            self._copy_btn.configure(
                state="normal" if sys.platform.startswith("win") else "disabled"
            )
            self._visible_action_buttons.extend(
                [self._copy_btn, self._bundle_btn]
            )
            if self._current_entry.get("parent_path"):
                self._visible_action_buttons.extend(
                    [self._compare_btn, self._revert_btn]
                )
            self._visible_action_buttons.append(self._i2v_btn)
        else:
            self._visible_action_buttons.extend(
                [self._open_vid_btn, self._bundle_btn]
            )

        self._relayout_action_buttons()

    def _on_action_bar_resize(self, _event=None) -> None:
        self.after_idle(self._relayout_action_buttons)

    def _relayout_action_buttons(self) -> None:
        if not self._visible_action_buttons:
            return
        width = max(self._action_bar.winfo_width(), 1)
        min_button_width = 132
        spacing = 6
        cols = max(1, width // (min_button_width + spacing))
        cols = min(cols, len(self._visible_action_buttons))
        for index in range(8):
            self._action_bar.grid_columnconfigure(index, weight=1 if index < cols else 0)
        for idx, button in enumerate(self._visible_action_buttons):
            row = idx // cols
            col = idx % cols
            button.grid(
                row=row,
                column=col,
                sticky="ew",
                padx=(0, spacing if col < cols - 1 else 0),
                pady=(0, 6),
            )

    def _toggle_edit_mode(self) -> None:
        if self._run_mode == "image_edit":
            self._exit_edit_mode()
            self._set_status("")
            return
        if self._current_entry and self._current_entry["type"] == "image":
            self._edit_source_entry = self._current_entry
            self._run_mode = "image_edit"
            self._page_mode = "image"
            self._mode_seg.set("\u56fe\u7247")
            self._on_mode_change("\u56fe\u7247")
            self._set_status("当前处于图片微调模式")

    def _exit_edit_mode(self) -> None:
        self._edit_source_entry = None
        if self._page_mode == "image":
            self._run_mode = "image"
            self._cc_slider.configure(state="normal")
        self._mode_hint.configure(text="")
        self._sync_action_buttons()

    def _open_current_video(self) -> None:
        if self._current_entry and self._current_entry["type"] == "video":
            p = self._current_entry["path"]
            if os.path.exists(p):
                os.startfile(p)

    def _img_to_video(self) -> None:
        if self._current_entry and self._current_entry["type"] == "image":
            url = self._current_entry.get("url", "")
            self._exit_edit_mode()
            self._mode_seg.set("\u89c6\u9891")
            self._on_mode_change("\u89c6\u9891")
            if url:
                self._ref_var.set(url)

    def _export_png(self) -> None:
        if not self._current_entry or self._current_entry["type"] != "image":
            return
        src = self._current_entry["path"]
        target = filedialog.asksaveasfilename(
            title="导出 PNG",
            defaultextension=".png",
            initialdir=str(self._storage.images_dir),
            initialfile=Path(src).with_suffix(".png").name,
            filetypes=[("PNG Image", "*.png")],
        )
        if not target:
            return
        try:
            with PILImage.open(src) as img:
                img.save(target, "PNG")
            self._set_status(f"已导出 PNG: {target}")
        except Exception as exc:
            self._set_status(f"错误: 导出失败 - {exc}")

    def _copy_current_image(self) -> None:
        if not self._current_entry or self._current_entry["type"] != "image":
            return
        if not sys.platform.startswith("win"):
            self._set_status("错误: 当前平台不支持图像剪贴板复制")
            return
        try:
            copy_image_to_clipboard(self._current_entry["path"])
            self._set_status("图片已复制到剪贴板")
        except Exception as exc:
            self._set_status(f"错误: 复制失败 - {exc}")

    def _open_outputs_dir(self) -> None:
        try:
            self._storage.outputs_dir.mkdir(parents=True, exist_ok=True)
            open_path(str(self._storage.outputs_dir))
        except Exception as exc:
            self._set_status(f"错误: 无法打开输出目录 - {exc}")

    def _compare_with_parent(self) -> None:
        if not self._current_entry or not self._current_entry.get("parent_path"):
            return
        parent_path = self._current_entry.get("parent_path", "")
        current_path = self._current_entry.get("path", "")
        if not os.path.exists(parent_path) or not os.path.exists(current_path):
            self._set_status("对比失败：找不到原图或当前图")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("微调对比")
        dialog.geometry("1100x620")
        dialog.transient(self)
        dialog.configure(fg_color=theme.get("BG_ROOT"))
        wrap = ctk.CTkFrame(dialog, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=16, pady=16)
        wrap.columnconfigure((0, 1), weight=1)
        for idx, (label, path) in enumerate((("原图", parent_path), ("当前图", current_path))):
            card = ctk.CTkFrame(wrap, fg_color=theme.get("BG_CARD"), corner_radius=8)
            card.grid(row=0, column=idx, sticky="nsew", padx=8)
            ctk.CTkLabel(card, text=label, font=theme.font_heading(15), text_color=theme.get("TEXT_PRIMARY")).pack(pady=(12, 8))
            img = PILImage.open(path)
            img.thumbnail((500, 500))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            lbl = ctk.CTkLabel(card, image=ctk_img, text="")
            lbl.image = ctk_img
            lbl.pack(expand=True, pady=(0, 12))

    def _revert_to_parent(self) -> None:
        if not self._current_entry or not self._current_entry.get("parent_path"):
            return
        parent_path = self._current_entry.get("parent_path", "")
        history = self._storage.get_history()
        parent_entry = next((item for item in history if item.get("path") == parent_path), None)
        if not parent_entry:
            self._set_status("回退失败：历史中未找到上一版")
            return
        self._select_history_entry(parent_entry)
        self._set_status("已回退到上一版")

    def _export_artifact_bundle(self) -> None:
        if not self._current_entry:
            return
        target = filedialog.asksaveasfilename(
            title="导出素材包",
            defaultextension=".zip",
            initialfile=f"{Path(self._current_entry['filename']).stem}_bundle.zip",
            filetypes=[("ZIP Archive", "*.zip")],
        )
        if not target:
            return
        media_path = Path(self._current_entry["path"])
        sidecar = media_path.with_suffix(media_path.suffix + ".json")
        try:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(media_path, arcname=media_path.name)
                if sidecar.exists():
                    zf.write(sidecar, arcname=sidecar.name)
            self._set_status(f"已导出素材包: {target}")
        except Exception as exc:
            self._set_status(f"导出素材包失败: {exc}")

    def reload_settings(self) -> None:
        base_dir = self._config.ui.default_output_dir if self._config and self._config.ui.default_output_dir else str(self._root_dir)
        self._storage = MediaStorage(base_dir=base_dir)

    def _do_enhance_prompt(self) -> None:
        prompt = self._get_prompt()
        if not prompt or self._enhancing or self._generating:
            return
        self._close_enhance_dialog()
        self._enhance_original_text = prompt
        self._enhance_candidate = ""
        self._enhancing = True
        self._enhance_btn.configure(state="disabled", text="润色中...")
        self._enhance_btn.configure(text="\u6da6\u8272\u4e2d...")
        self._enhancer.enhance(
            mode="image",
            text=prompt,
            locked_keywords=self._enhance_dialog.get_locked_keywords() if self._enhance_dialog else [],
            source="manual",
            feature="prompt_enhance",
            on_done=lambda value: self.after(0, self._on_enhance_done, value),
            on_error=lambda msg: self.after(0, self._on_enhance_error, msg),
        )

    def _on_enhance_done(self, value: str) -> None:
        self._enhancing = False
        self._enhance_candidate = value
        self._enhance_btn.configure(
            state="normal" if not self._generating else "disabled",
            text="✨ 智能润色",
        )
        self._enhance_btn.configure(text="\u2728 \u667a\u80fd\u6da6\u8272")
        self._set_status("已生成润色预览")
        self._show_enhance_dialog()

    def _on_enhance_error(self, msg: str) -> None:
        self._enhancing = False
        self._enhance_btn.configure(
            state="normal" if not self._generating else "disabled",
            text="✨ 智能润色",
        )
        if self._enhance_dialog and self._enhance_dialog.winfo_exists():
            self._enhance_dialog.set_busy(False)
            self._enhance_dialog.set_status(msg, is_error=True)
        self._set_status(f"错误: {msg}")

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
            title="提示词润色预览",
            on_confirm=self._confirm_enhancement,
            on_regenerate=self._regenerate_enhancement,
            on_cancel=self._cancel_enhancement,
        )

    def _confirm_enhancement(self) -> None:
        if not self._enhance_candidate:
            return
        self._applied_original_prompt = self._enhance_original_text
        self._applied_enhanced_prompt = self._enhance_candidate
        self._prompt.delete("1.0", "end")
        self._prompt.insert("1.0", self._enhance_candidate)
        self._set_status("已使用润色结果")
        self._close_enhance_dialog()

    def _regenerate_enhancement(self) -> None:
        if self._enhancing or not self._enhance_original_text:
            return
        self._enhancing = True
        self._enhance_btn.configure(state="disabled", text="润色中...")
        if self._enhance_dialog and self._enhance_dialog.winfo_exists():
            self._enhance_dialog.set_busy(True, "正在生成新的润色方案...")
        self._set_status("正在生成新的润色方案...")
        self._enhancer.enhance(
            mode="image",
            text=self._enhance_original_text,
            previous_candidate=self._enhance_candidate,
            variation=True,
            locked_keywords=self._enhance_dialog.get_locked_keywords() if self._enhance_dialog else [],
            source="manual",
            feature="prompt_enhance",
            on_done=lambda value: self.after(0, self._on_enhance_done, value),
            on_error=lambda msg: self.after(0, self._on_enhance_error, msg),
        )

    def _cancel_enhancement(self) -> None:
        if self._enhancing:
            self._enhancer.cancel()
            self._enhancing = False
            self._enhance_btn.configure(
                state="normal" if not self._generating else "disabled",
                text="✨ 智能润色",
            )
        self._set_status("已取消润色")
        self._close_enhance_dialog()

    def _close_enhance_dialog(self) -> None:
        if self._enhance_dialog and self._enhance_dialog.winfo_exists():
            self._enhance_dialog.close()
        self._enhance_dialog = None

    # ── History ──

    def _refresh_history(self) -> None:
        for w in self._hist_widgets:
            w.destroy()
        self._hist_widgets.clear()
        self._hist_images.clear()

        history = self._storage.get_history()
        for i, entry in enumerate(history):
            col = i % _HIST_COLS
            row = i // _HIST_COLS

            card = ctk.CTkFrame(
                self._hist_scroll,
                width=_HIST_THUMB, height=_HIST_THUMB,
                fg_color=theme.get("BG_INPUT"), corner_radius=6,
            )
            card.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            card.grid_propagate(False)

            if (
                entry["type"] == "image"
                and entry.get("thumb")
                and os.path.exists(entry["thumb"])
            ):
                try:
                    ti = PILImage.open(entry["thumb"])
                    ct = ctk.CTkImage(
                        light_image=ti, dark_image=ti,
                        size=(
                            min(ti.width, _HIST_THUMB - 8),
                            min(ti.height, _HIST_THUMB - 8),
                        ),
                    )
                    lbl = ctk.CTkLabel(card, image=ct, text="")
                    lbl.pack(expand=True)
                    self._hist_images.append(ct)
                    lbl.bind("<Button-1>", lambda e, item=entry: self._select_history_entry(item))
                except Exception:
                    ctk.CTkLabel(
                        card, text="\U0001f5bc\ufe0f",
                        font=theme.font_heading(24),
                        text_color=theme.get("TEXT_MUTED"),
                    ).pack(expand=True)
            elif entry["type"] == "video":
                vl = ctk.CTkLabel(
                    card, text=f"\U0001f3ac\n{entry['filename'][:14]}",
                    font=theme.font_small(9),
                    text_color=theme.get("TEXT_SECONDARY"),
                    wraplength=_HIST_THUMB - 16,
                )
                vl.pack(expand=True)
                vl.bind("<Button-1>", lambda e, item=entry: self._select_history_entry(item))
            else:
                ctk.CTkLabel(
                    card, text="\U0001f5bc\ufe0f",
                    font=theme.font_heading(24),
                    text_color=theme.get("TEXT_MUTED"),
                ).pack(expand=True)

            self._hist_widgets.append(card)

    def _select_history_entry(self, entry: dict) -> None:
        self._current_entry = entry
        if entry["type"] == "image":
            self._load_preview(entry["path"])
            if self._run_mode == "image_edit":
                self._edit_source_entry = entry
                self._on_mode_change("图片")
        else:
            if self._run_mode == "image_edit":
                self._exit_edit_mode()
            self._preview_lbl.configure(
                image=None, text=f"\U0001f3ac {entry['filename']}",
            )
            self._preview_image = None
        self._sync_action_buttons()

    @staticmethod
    def _open_video(path: str) -> None:
        if os.path.exists(path):
            os.startfile(path)

    def _do_clear_cache(self) -> None:
        self._storage.clear()
        self._preview_lbl.configure(
            image=None,
            text="\u5728\u5de6\u4fa7\u914d\u7f6e\u53c2\u6570\u5e76\u70b9\u51fb\u201c\u751f\u6210\u201d\u5f00\u59cb",
        )
        self._preview_image = None
        self._current_entry = None
        self._edit_source_entry = None
        self._run_mode = "image" if self._page_mode == "image" else "video"
        self._mode_hint.configure(text="")
        self._sync_action_buttons()
        self._refresh_history()
        self._set_status("\u7f13\u5b58\u5df2\u6e05\u7406")

    # ── Status ──

    def _set_status(self, text: str) -> None:
        self._status_lbl.configure(text=text)

    # ── Theme ──

    def _apply_theme(self) -> None:
        self.configure(fg_color=theme.get("BG_ROOT"))
        self._left.configure(fg_color=theme.get("BG_CARD"))
        self._right.configure(fg_color=theme.get("BG_ROOT"))

        self._mode_seg.configure(
            selected_color=theme.get("ACCENT_PURPLE"),
            selected_hover_color=theme.get("HOVER_PURPLE"),
        )
        self._prompt_label.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._prompt.configure(
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._enhance_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._size_dd.configure(
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._mode_hint.configure(text_color=theme.get("ACCENT_YELLOW"))
        self._retry_entry.configure(
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._quality_dd.configure(
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._ref_entry.configure(
            fg_color=theme.get("BG_INPUT"),
            text_color=theme.get("TEXT_PRIMARY"),
        )

        self._gen_btn.configure(
            fg_color=theme.get("ACCENT_PURPLE"),
            hover_color=theme.get("HOVER_PURPLE"),
        )
        self._stop_btn.configure(
            fg_color=theme.get("ACCENT_RED"),
            hover_color=theme.get("HOVER_RED"),
        )
        self._clear_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._open_outputs_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )

        self._status_lbl.configure(text_color=theme.get("TEXT_SECONDARY"))
        self._preview_frame.configure(fg_color=theme.get("BG_CARD"))
        self._preview_lbl.configure(text_color=theme.get("TEXT_MUTED"))
        self._hist_scroll.configure(fg_color=theme.get("BG_CARD"))
        self._hist_lbl.configure(text_color=theme.get("TEXT_SECONDARY"))

        self._edit_btn.configure(
            fg_color=theme.get("ACCENT_PURPLE"),
            hover_color=theme.get("HOVER_PURPLE"),
        )
        self._export_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._copy_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._i2v_btn.configure(
            fg_color=theme.get("ACCENT_PURPLE"),
            hover_color=theme.get("HOVER_PURPLE"),
        )
        self._open_vid_btn.configure(
            fg_color=theme.get("ACCENT_BLUE"),
            hover_color=theme.get("HOVER_BLUE"),
        )
        self._compare_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._revert_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._bundle_btn.configure(
            fg_color=theme.get("BG_INPUT"),
            hover_color=theme.get("HOVER_GENERIC"),
            text_color=theme.get("TEXT_SECONDARY"),
        )
        self._refresh_history()
        self._sync_action_buttons()

    def destroy(self) -> None:
        theme.remove_listener(self._apply_theme)
        self._client.shutdown()
        self._enhancer.cancel()
        self._close_enhance_dialog()
        super().destroy()
