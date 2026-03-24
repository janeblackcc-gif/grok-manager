from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

import requests

from gui.utils.api_errors import parse_request_exception, parse_response_error
from gui.utils.run_recorder import get_run_recorder

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "http://127.0.0.1:8000"
_DEFAULT_MODEL = "grok-4.20-beta"

_SYSTEM_PROMPTS = {
    "search": (
        "You rewrite user input into a concise, structured AI search instruction. "
        "Preserve intent, do not add facts, do not answer the question. "
        "Return only the rewritten query in Chinese."
    ),
    "image": (
        "You rewrite simple image-generation prompts into a richer professional art prompt. "
        "Preserve the original subject and intent. Expand with composition, lighting, materials, style, "
        "camera or render cues when helpful. Return only the rewritten prompt in Chinese."
    ),
}


def _find_grok2api_config() -> Path | None:
    candidates = [
        Path(os.environ.get("GROK2API_CONFIG", "")) if os.environ.get("GROK2API_CONFIG") else None,
        Path.home() / "grok2api" / "data" / "config.toml",
    ]
    for path in candidates:
        if path and path.exists():
            return path
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
                    _, _, value = stripped.partition("=")
                    return value.strip().strip('"').strip("'")
    except Exception:
        logger.debug("Failed to read grok2api api_key, using empty")
    return ""


class PromptEnhancerClient:

    def __init__(
        self,
        api_base: str | None = None,
        model: str | None = None,
        connect_timeout: float = 10.0,
        read_timeout: float = 60.0,
    ) -> None:
        self._api_base = (api_base or os.environ.get("GROK_API_BASE") or _DEFAULT_API_BASE).rstrip("/")
        self._api_url = f"{self._api_base}/v1/chat/completions"
        self._model = model or os.environ.get("GROK_MODEL") or _DEFAULT_MODEL
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._api_key = _load_api_key()
        self._lock = threading.Lock()
        self._gen = 0
        self._cancel = threading.Event()
        self._resp: requests.Response | None = None

    @property
    def model_name(self) -> str:
        return self._model

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            resp = self._resp
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def enhance(
        self,
        mode: Literal["search", "image"],
        text: str,
        previous_candidate: str | None = None,
        variation: bool = False,
        locked_keywords: list[str] | None = None,
        source: str = "manual",
        feature: str = "prompt_enhance",
        on_done: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.cancel()
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._resp = None
        self._cancel.clear()
        threading.Thread(
            target=self._run,
            args=(
                gen,
                mode,
                text,
                previous_candidate,
                variation,
                list(locked_keywords or []),
                source,
                feature,
                on_done,
                on_error,
            ),
            daemon=True,
        ).start()

    def _is_stale(self, gen: int) -> bool:
        with self._lock:
            return gen != self._gen

    def _run(
        self,
        gen: int,
        mode: Literal["search", "image"],
        text: str,
        previous_candidate: str | None,
        variation: bool,
        locked_keywords: list[str],
        source: str,
        feature: str,
        on_done: Callable[[str], None] | None,
        on_error: Callable[[str], None] | None,
    ) -> None:
        start_time = datetime.now()
        status_code: int | None = None
        run_id = get_run_recorder().start_run(
            feature=feature,
            source=source,
            model=self._model,
            mode=mode,
            input_text=text,
            metadata={
                "variation": variation,
                "locked_keywords": locked_keywords,
            },
        )
        try:
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPTS[mode]},
                {"role": "user", "content": text},
            ]
            if locked_keywords:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Keep these keywords unchanged in the rewrite: "
                            + ", ".join(locked_keywords)
                            + "."
                        ),
                    }
                )
            if variation:
                if previous_candidate:
                    messages.append({"role": "assistant", "content": previous_candidate})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Rewrite the same original input again, but return a meaningfully different "
                            "alternative version that still preserves the original intent. "
                            "Return only the rewritten text."
                        ),
                    }
                )
            payload = {
                "model": self._model,
                "stream": False,
                "temperature": 0.4,
                "messages": messages,
            }
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            resp = requests.post(
                self._api_url,
                json=payload,
                headers=headers,
                timeout=(self._connect_timeout, self._read_timeout),
            )
            with self._lock:
                if self._gen != gen:
                    resp.close()
                    return
                self._resp = resp
            if self._cancel.is_set():
                resp.close()
                return
            with resp:
                status_code = resp.status_code
                if resp.status_code != 200:
                    if on_error and not self._is_stale(gen):
                        message = parse_response_error(resp)
                        get_run_recorder().finish_run(
                            run_id,
                            success=False,
                            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                            http_status=status_code,
                            error_message=message,
                        )
                        on_error(message)
                    return
                data = resp.json()
                choices = data.get("choices") or []
                content = ""
                if choices:
                    message = choices[0].get("message") or {}
                    content = str(message.get("content") or "").strip()
                if not content:
                    if on_error and not self._is_stale(gen):
                        message = "润色返回空内容"
                        get_run_recorder().finish_run(
                            run_id,
                            success=False,
                            duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                            http_status=status_code,
                            error_message=message,
                        )
                        on_error(message)
                    return
                get_run_recorder().finish_run(
                    run_id,
                    success=True,
                    duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                    http_status=status_code,
                )
                if on_done and not self._is_stale(gen):
                    on_done(content)
        except Exception as exc:
            if on_error and not self._cancel.is_set() and not self._is_stale(gen):
                message = parse_request_exception(exc)
                get_run_recorder().finish_run(
                    run_id,
                    success=False,
                    duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                    http_status=status_code,
                    error_message=message,
                )
                on_error(message)
        finally:
            with self._lock:
                if self._gen == gen:
                    self._resp = None
