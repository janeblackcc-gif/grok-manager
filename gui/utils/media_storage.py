from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import requests
from PIL import Image

logger = logging.getLogger(__name__)

_HISTORY_CAP = 30
_THUMB_MAX = 180


class MediaStorage:
    """Local media file storage + history management."""

    def __init__(self, base_dir: Optional[str] = None) -> None:
        root = Path(base_dir) if base_dir else Path.cwd()
        self._outputs_dir = self._resolve_outputs_dir(root)
        self._images_dir = self._outputs_dir / "images"
        self._videos_dir = self._outputs_dir / "videos"
        self._thumbs_dir = self._outputs_dir / "thumbnails"
        self._history_path = self._outputs_dir / "history.json"
        self._write_lock = threading.Lock()

        for d in (self._images_dir, self._videos_dir, self._thumbs_dir):
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _resolve_outputs_dir(root: Path) -> Path:
        try:
            if root.name.lower() == "outputs":
                return root
        except Exception:
            pass
        return root / "outputs"

    @property
    def outputs_dir(self) -> Path:
        return self._outputs_dir

    @property
    def images_dir(self) -> Path:
        return self._images_dir

    def save_image(
        self,
        url: str,
        prompt: str = "",
        *,
        mode: str = "image",
        parent_url: str = "",
        parent_path: str = "",
        raw_prompt: str = "",
        enhanced_prompt: str = "",
        model: str = "",
        feature: str = "image_generation",
        source: str = "manual",
        result_status: str = "success",
        tags: list[str] | None = None,
    ) -> Optional[dict[str, Any]]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = secrets.token_hex(3)
        filename = f"img_{ts}_{suffix}.png"
        filepath = self._images_dir / filename

        if not self._is_safe_path(filepath):
            return None
        if not self._save_image_png(url, filepath):
            return None

        thumb_name = f"thumb_{filename}"
        thumb_path = self._thumbs_dir / thumb_name
        self._make_thumbnail(filepath, thumb_path)

        entry = {
            "type": "image",
            "filename": filename,
            "path": str(filepath),
            "thumb": str(thumb_path) if thumb_path.exists() else "",
            "url": url,
            "prompt": prompt,
            "mode": mode,
            "feature": feature,
            "source": source,
            "model": model,
            "raw_prompt": raw_prompt,
            "enhanced_prompt": enhanced_prompt,
            "result_status": result_status,
            "tags": list(tags or []),
            "parent_url": parent_url,
            "parent_path": parent_path,
            "created": datetime.now().isoformat(),
        }
        self._write_sidecar(filepath, entry)
        self._append_history(entry)
        return entry

    def save_video(
        self,
        url: str,
        prompt: str = "",
        *,
        raw_prompt: str = "",
        enhanced_prompt: str = "",
        model: str = "",
        feature: str = "video_generation",
        source: str = "manual",
        result_status: str = "success",
        tags: list[str] | None = None,
    ) -> Optional[dict[str, Any]]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = secrets.token_hex(3)
        filename = f"vid_{ts}_{suffix}.mp4"
        filepath = self._videos_dir / filename

        if not self._is_safe_path(filepath):
            return None
        if not self._download(url, filepath):
            return None

        entry = {
            "type": "video",
            "filename": filename,
            "path": str(filepath),
            "thumb": "",
            "url": url,
            "prompt": prompt,
            "feature": feature,
            "source": source,
            "model": model,
            "raw_prompt": raw_prompt,
            "enhanced_prompt": enhanced_prompt,
            "result_status": result_status,
            "tags": list(tags or []),
            "created": datetime.now().isoformat(),
        }
        self._write_sidecar(filepath, entry)
        self._append_history(entry)
        return entry

    def get_history(self) -> list[dict[str, Any]]:
        try:
            if self._history_path.exists():
                data = json.loads(self._history_path.read_text("utf-8"))
                if isinstance(data, list):
                    return data
        except Exception:
            logger.debug("Failed to load history.json")
        return []

    def clear(self) -> None:
        with self._write_lock:
            import shutil

            for sub in (self._images_dir, self._videos_dir, self._thumbs_dir):
                if sub.exists():
                    shutil.rmtree(sub)
                    sub.mkdir(parents=True, exist_ok=True)
            self._atomic_write([])

    def _is_safe_path(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            outputs_resolved = self._outputs_dir.resolve()
            return resolved == outputs_resolved or outputs_resolved in resolved.parents
        except Exception:
            return False

    @staticmethod
    def _download(url: str, dest: Path) -> bool:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            resp = requests.get(url, stream=True, timeout=(10, 120))
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            return True
        except Exception:
            logger.exception("Download failed: %s", url)
            return False

    @staticmethod
    def _load_image_bytes(url: str) -> bytes:
        if url.startswith("data:"):
            import base64

            _, _, data_part = url.partition(",")
            return base64.b64decode(data_part)

        resp = requests.get(url, timeout=(10, 120))
        resp.raise_for_status()
        return resp.content

    def _save_image_png(self, url: str, dest: Path) -> bool:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            raw = self._load_image_bytes(url)
            with Image.open(BytesIO(raw)) as img:
                normalized = img.convert(
                    "RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB"
                )
                normalized.save(dest, "PNG")
            return True
        except Exception:
            logger.exception("Failed to normalize image as PNG: %s", url)
            return False

    @staticmethod
    def _make_thumbnail(src: Path, dest: Path) -> None:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as img:
                img.thumbnail((_THUMB_MAX, _THUMB_MAX))
                img.save(dest, "PNG")
        except Exception:
            logger.debug("Thumbnail creation failed for %s", src)

    def _append_history(self, entry: dict[str, Any]) -> None:
        with self._write_lock:
            history = self.get_history()
            history.insert(0, entry)
            if len(history) > _HISTORY_CAP:
                history = history[:_HISTORY_CAP]
            self._atomic_write(history)

    def _write_sidecar(self, media_path: Path, entry: dict[str, Any]) -> None:
        try:
            sidecar = media_path.with_suffix(media_path.suffix + ".json")
            sidecar.write_text(json.dumps(entry, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            logger.exception("Failed to write sidecar for %s", media_path)

    def _atomic_write(self, data: list) -> None:
        tmp = self._history_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            os.replace(str(tmp), str(self._history_path))
        except Exception:
            logger.exception("Atomic write failed for history.json")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
