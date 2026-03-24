from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from gui.utils.api_errors import parse_request_exception, parse_response_error
from gui.utils.run_recorder import get_run_recorder

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "http://127.0.0.1:8000"
_IMAGE_MODEL = "grok-imagine-1.0"
_IMAGE_EDIT_MODEL = "grok-imagine-1.0-edit"
_VIDEO_MODEL = "grok-imagine-1.0-video"
_READY_MAX_CHECKS = 30
_READY_INTERVAL = 3.0


def _find_grok2api_config() -> Path | None:
    candidates = [
        Path(os.environ.get("GROK2API_CONFIG", "")) if os.environ.get("GROK2API_CONFIG") else None,
        Path.home() / "grok2api" / "data" / "config.toml",
    ]
    for p in candidates:
        if p and p.exists():
            return p
    return None


def _load_api_key() -> str:
    env_key = os.environ.get("GROK_API_KEY")
    if env_key:
        return env_key
    try:
        cfg = _find_grok2api_config()
        if cfg:
            for line in cfg.read_text("utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("api_key"):
                    _, _, val = stripped.partition("=")
                    return val.strip().strip('"').strip("'")
    except Exception:
        logger.debug("Failed to read grok2api api_key, using empty")
    return ""


class MediaGenClient:
    """Concurrent image/video/edit client with UI-thread callbacks."""

    def __init__(
        self,
        master: Any,
        api_base: str | None = None,
        connect_timeout: float = 10.0,
        read_timeout: float = 120.0,
    ) -> None:
        self._master = master
        self._api_base = (api_base or os.environ.get("GROK_API_BASE") or _DEFAULT_API_BASE).rstrip("/")
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._api_key = _load_api_key()

        self._lock = threading.Lock()
        self._gen = 0
        self._stop_event = threading.Event()
        self._executor: ThreadPoolExecutor | None = None
        self._sessions: list[requests.Session] = []
        self._destroyed = False
        self._current_run_id = ""

    @property
    def current_run_id(self) -> str:
        return self._current_run_id

    def _is_stale(self, gen: int) -> bool:
        with self._lock:
            return gen != self._gen

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _safe_after(self, gen: int, func: Callable, *args: Any) -> None:
        if self._destroyed or self._is_stale(gen):
            return
        try:
            self._master.after(0, func, *args)
        except Exception:
            pass

    def _next_gen(self) -> int:
        self.cancel()
        with self._lock:
            self._gen += 1
            gen = self._gen
        self._stop_event.clear()
        return gen

    def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        n: int = 1,
        concurrency: int = 5,
        max_retries: int = 1,
        enable_nsfw: Optional[bool] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_success: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        gen = self._next_gen()
        concurrency = max(1, min(20, concurrency))
        self._current_run_id = get_run_recorder().start_run(
            feature="image_generation",
            source="creation_center",
            model=_IMAGE_MODEL,
            mode=size,
            input_text=prompt,
            metadata={"concurrency": concurrency, "enable_nsfw": enable_nsfw},
        )
        threading.Thread(
            target=self._image_coordinator,
            args=(gen, prompt, size, n, concurrency, max_retries, enable_nsfw, on_status, on_success, on_error),
            daemon=True,
        ).start()

    def _image_coordinator(
        self,
        gen: int,
        prompt: str,
        size: str,
        n: int,
        concurrency: int,
        max_retries: int,
        enable_nsfw: Optional[bool],
        on_status: Optional[Callable[[str], None]],
        on_success: Optional[Callable[[str, str], None]],
        on_error: Optional[Callable[[str], None]],
    ) -> None:
        if on_status:
            self._safe_after(gen, on_status, f"正在并发发起 {concurrency} 个生图请求...")

        winner_url: Optional[str] = None
        winner_lock = threading.Lock()
        errors: list[str] = []
        start_time = datetime.now()

        executor = ThreadPoolExecutor(max_workers=concurrency)
        with self._lock:
            self._executor = executor

        def worker(idx: int) -> Optional[str]:
            session = requests.Session()
            with self._lock:
                self._sessions.append(session)
            try:
                for _ in range(max_retries + 1):
                    if self._stop_event.is_set() or self._is_stale(gen):
                        return None
                    with winner_lock:
                        if winner_url is not None:
                            return None
                    payload: dict[str, Any] = {
                        "prompt": prompt,
                        "model": _IMAGE_MODEL,
                        "n": n,
                        "size": size,
                    }
                    if enable_nsfw is not None:
                        payload["enable_nsfw"] = enable_nsfw
                    try:
                        resp = session.post(
                            f"{self._api_base}/v1/images/generations",
                            json=payload,
                            headers=self._headers(),
                            timeout=(self._connect_timeout, self._read_timeout),
                        )
                        if resp.status_code != 200:
                            errors.append(parse_response_error(resp))
                            continue
                        data = resp.json()
                        items = data.get("data", [])
                        if not items:
                            errors.append(f"Worker {idx}: image generation returned no items")
                            continue
                        url = items[0].get("url", "")
                        if not url:
                            b64 = items[0].get("b64_json", "")
                            if b64:
                                url = f"data:image/png;base64,{b64}"
                        if url:
                            return url
                        errors.append(f"Worker {idx}: image generation returned no URL")
                    except Exception as exc:
                        errors.append(parse_request_exception(exc))
                return None
            finally:
                with self._lock:
                    try:
                        self._sessions.remove(session)
                    except ValueError:
                        pass
                session.close()

        try:
            futures = {executor.submit(worker, i): i for i in range(concurrency)}
            for future in as_completed(futures):
                if self._stop_event.is_set() or self._is_stale(gen):
                    break
                result = future.result()
                if result:
                    with winner_lock:
                        if winner_url is None:
                            winner_url = result
                            self._stop_event.set()

            executor.shutdown(wait=False)

            if self._is_stale(gen):
                return
            if winner_url:
                self._stop_event.clear()
                if on_status:
                    self._safe_after(gen, on_status, "图片已返回，正在等待资源可访问...")
                ready_url = self._check_media_ready(winner_url, "image", gen)
                if ready_url and not self._is_stale(gen):
                    get_run_recorder().finish_run(
                        self._current_run_id,
                        success=True,
                        duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                        http_status=200,
                        output_url=ready_url,
                    )
                    if on_status:
                        self._safe_after(gen, on_status, "图片已就绪")
                    if on_success:
                        self._safe_after(gen, on_success, ready_url, "image")
                elif not self._stop_event.is_set() and on_error:
                    message = f"图片资源未就绪: {winner_url}"
                    get_run_recorder().finish_run(
                        self._current_run_id,
                        success=False,
                        duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                        error_message=message,
                    )
                    self._safe_after(gen, on_error, message)
            elif not self._stop_event.is_set() and on_error:
                message = errors[0] if errors else "图片生成失败"
                get_run_recorder().finish_run(
                    self._current_run_id,
                    success=False,
                    duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                    error_message=message,
                )
                self._safe_after(gen, on_error, message)
        except Exception as exc:
            if not self._is_stale(gen) and on_error:
                message = str(exc)
                get_run_recorder().finish_run(
                    self._current_run_id,
                    success=False,
                    duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                    error_message=message,
                )
                self._safe_after(gen, on_error, message)

    def edit_image(
        self,
        prompt: str,
        image_url: str,
        size: str | None = None,
        max_retries: int = 1,
        on_status: Optional[Callable[[str], None]] = None,
        on_success: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        gen = self._next_gen()
        self._current_run_id = get_run_recorder().start_run(
            feature="image_edit",
            source="creation_center",
            model=_IMAGE_EDIT_MODEL,
            mode=size or "",
            input_text=prompt,
            metadata={"reference_url": image_url},
        )
        threading.Thread(
            target=self._edit_worker,
            args=(gen, prompt, image_url, size, max_retries, on_status, on_success, on_error),
            daemon=True,
        ).start()

    def _edit_worker(
        self,
        gen: int,
        prompt: str,
        image_url: str,
        size: str | None,
        max_retries: int,
        on_status: Optional[Callable[[str], None]],
        on_success: Optional[Callable[[str, str], None]],
        on_error: Optional[Callable[[str], None]],
    ) -> None:
        if on_status:
            self._safe_after(gen, on_status, "正在执行局部微调...")

        session = requests.Session()
        start_time = datetime.now()
        with self._lock:
            self._sessions.append(session)
        try:
            payload: dict[str, Any] = {
                "model": _IMAGE_EDIT_MODEL,
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }
                ],
            }
            if size:
                payload["image_config"] = {"n": 1, "size": size, "response_format": "url"}

            for _ in range(max_retries + 1):
                if self._stop_event.is_set() or self._is_stale(gen):
                    return
                try:
                    resp = session.post(
                        f"{self._api_base}/v1/chat/completions",
                        json=payload,
                        headers=self._headers(),
                        timeout=(self._connect_timeout, self._read_timeout),
                    )
                    if resp.status_code != 200:
                        if on_error and not self._is_stale(gen):
                            message = parse_response_error(resp)
                            get_run_recorder().finish_run(
                                self._current_run_id,
                                success=False,
                                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                                http_status=resp.status_code,
                                error_message=message,
                            )
                            self._safe_after(gen, on_error, message)
                        return
                    data = resp.json()
                    choices = data.get("choices") or []
                    content = ""
                    if choices:
                        message = choices[0].get("message") or {}
                        content = str(message.get("content") or "")
                    image_result = self._extract_first_image_url(content)
                    if not image_result:
                        if on_error and not self._is_stale(gen):
                            message = "Image edit returned no results"
                            get_run_recorder().finish_run(
                                self._current_run_id,
                                success=False,
                                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                                http_status=resp.status_code,
                                error_message=message,
                            )
                            self._safe_after(gen, on_error, message)
                        return
                    if on_status:
                        self._safe_after(gen, on_status, "微调结果已返回，正在等待资源可访问...")
                    ready_url = self._check_media_ready(image_result, "image", gen)
                    if ready_url and on_success and not self._is_stale(gen):
                        get_run_recorder().finish_run(
                            self._current_run_id,
                            success=True,
                            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                            http_status=resp.status_code,
                            output_url=ready_url,
                        )
                        self._safe_after(gen, on_success, ready_url, "image")
                    elif on_error and not self._stop_event.is_set():
                        message = f"图片资源未就绪: {image_result}"
                        get_run_recorder().finish_run(
                            self._current_run_id,
                            success=False,
                            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                            http_status=resp.status_code,
                            error_message=message,
                        )
                        self._safe_after(gen, on_error, message)
                    return
                except Exception as exc:
                    if on_error and not self._is_stale(gen):
                        message = parse_request_exception(exc)
                        get_run_recorder().finish_run(
                            self._current_run_id,
                            success=False,
                            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                            error_message=message,
                        )
                        self._safe_after(gen, on_error, message)
                    return
        finally:
            with self._lock:
                try:
                    self._sessions.remove(session)
                except ValueError:
                    pass
            session.close()

    @staticmethod
    def _extract_first_image_url(content: str) -> str:
        text = (content or "").strip()
        if not text:
            return ""
        if "](http" in text and text.startswith("!["):
            start = text.find("](")
            end = text.find(")", start + 2)
            if start != -1 and end != -1:
                return text[start + 2 : end].strip()
        if text.startswith("http://") or text.startswith("https://") or text.startswith("data:"):
            return text.splitlines()[0].strip()
        return ""

    def generate_video(
        self,
        prompt: str,
        size: str = "1792x1024",
        seconds: int = 6,
        quality: str = "standard",
        max_retries: int = 1,
        image_ref: Optional[str] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_success: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        gen = self._next_gen()
        self._current_run_id = get_run_recorder().start_run(
            feature="video_generation",
            source="creation_center",
            model=_VIDEO_MODEL,
            mode=size,
            input_text=prompt,
            metadata={"seconds": seconds, "quality": quality, "image_ref": image_ref or ""},
        )
        threading.Thread(
            target=self._video_worker,
            args=(gen, prompt, size, seconds, quality, max_retries, image_ref, on_status, on_success, on_error),
            daemon=True,
        ).start()

    def _video_worker(
        self,
        gen: int,
        prompt: str,
        size: str,
        seconds: int,
        quality: str,
        max_retries: int,
        image_ref: Optional[str],
        on_status: Optional[Callable[[str], None]],
        on_success: Optional[Callable[[str, str], None]],
        on_error: Optional[Callable[[str], None]],
    ) -> None:
        if on_status:
            self._safe_after(gen, on_status, "正在生成视频...")

        payload: dict[str, Any] = {
            "prompt": prompt,
            "model": _VIDEO_MODEL,
            "size": size,
            "seconds": seconds,
            "quality": quality,
        }
        if image_ref:
            payload["image_reference"] = {"image_url": image_ref}

        session = requests.Session()
        start_time = datetime.now()
        with self._lock:
            self._sessions.append(session)
        try:
            for _ in range(max_retries + 1):
                if self._stop_event.is_set() or self._is_stale(gen):
                    return
                try:
                    resp = session.post(
                        f"{self._api_base}/v1/videos",
                        json=payload,
                        headers=self._headers(),
                        timeout=(self._connect_timeout, 300),
                    )
                    if resp.status_code != 200:
                        if on_error:
                            message = parse_response_error(resp)
                            get_run_recorder().finish_run(
                                self._current_run_id,
                                success=False,
                                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                                http_status=resp.status_code,
                                error_message=message,
                            )
                            self._safe_after(gen, on_error, message)
                        return

                    data = resp.json()
                    url = data.get("url", "")
                    if not url:
                        if on_error:
                            message = "Video generation returned no URL"
                            get_run_recorder().finish_run(
                                self._current_run_id,
                                success=False,
                                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                                http_status=resp.status_code,
                                error_message=message,
                            )
                            self._safe_after(gen, on_error, message)
                        return
                    if on_status:
                        self._safe_after(gen, on_status, "视频已返回，正在等待资源可访问...")
                    ready_url = self._check_media_ready(url, "video", gen)
                    if ready_url and not self._is_stale(gen):
                        get_run_recorder().finish_run(
                            self._current_run_id,
                            success=True,
                            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                            http_status=resp.status_code,
                            output_url=ready_url,
                        )
                        if on_status:
                            self._safe_after(gen, on_status, "视频已就绪")
                        if on_success:
                            self._safe_after(gen, on_success, ready_url, "video")
                    elif on_error and not self._stop_event.is_set():
                        message = f"视频资源未就绪: {url}"
                        get_run_recorder().finish_run(
                            self._current_run_id,
                            success=False,
                            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                            http_status=resp.status_code,
                            error_message=message,
                        )
                        self._safe_after(gen, on_error, message)
                    return
                except Exception as exc:
                    if on_error:
                        message = parse_request_exception(exc)
                        get_run_recorder().finish_run(
                            self._current_run_id,
                            success=False,
                            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                            error_message=message,
                        )
                        self._safe_after(gen, on_error, message)
                    return
        finally:
            with self._lock:
                try:
                    self._sessions.remove(session)
                except ValueError:
                    pass
            session.close()

    def _check_media_ready(self, url: str, expected_type: str, gen: int) -> Optional[str]:
        if url.startswith("data:"):
            return url

        for _ in range(_READY_MAX_CHECKS):
            if self._stop_event.is_set() or self._is_stale(gen) or self._destroyed:
                return None
            try:
                resp = requests.get(url, stream=True, timeout=(5, 10))
                content_type = resp.headers.get("Content-Type", "").lower()
                resp.close()
                if expected_type == "image" and content_type.startswith("image/"):
                    return url
                if expected_type == "video" and (
                    content_type.startswith("video/") or content_type == "application/octet-stream"
                ):
                    return url
            except Exception:
                pass
            self._stop_event.wait(_READY_INTERVAL)
        return None

    def cancel(self) -> None:
        with self._lock:
            self._gen += 1
        self._stop_event.set()
        with self._lock:
            for session in self._sessions:
                try:
                    session.close()
                except Exception:
                    pass
            self._sessions.clear()

    def shutdown(self) -> None:
        self._destroyed = True
        self.cancel()
        with self._lock:
            executor = self._executor
            self._executor = None
        if executor:
            try:
                executor.shutdown(wait=False)
            except Exception:
                pass
