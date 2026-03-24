from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

from gui.utils.api_errors import parse_request_exception, parse_response_error
from gui.utils.run_recorder import get_run_recorder

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "http://127.0.0.1:8000"
_DEFAULT_MODEL = "grok-4.20-beta"

_BASE_SYSTEM = (
    "你现在是一个专业的搜索引擎。"
    "请优先使用联网搜索功能，并给出结构清晰、带有事实来源的回答。"
)

_MODE_SUFFIX = {
    "concise": "请用简洁的语言回答，控制在 200 字以内，直接给出核心信息。",
    "detailed": "请给出详细的分析和解释，包含多个角度和背景信息。",
    "expert": "请以专业报告格式回答，包含摘要、分析、结论和参考来源列表，使用 Markdown。",
}

_NO_WEB = "请仅基于你已有的知识回答，不要进行联网搜索。"


def _find_grok2api_config() -> Path | None:
    candidates = [
        Path(os.environ.get("GROK2API_CONFIG", "")) if os.environ.get("GROK2API_CONFIG") else None,
        Path.home() / "grok2api" / "data" / "config.toml",
    ]
    for p in candidates:
        if p and p.exists():
            return p
    return None


class GrokSearchClient:

    def __init__(
        self,
        api_base: str | None = None,
        model: str | None = None,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
    ) -> None:
        self._api_base = (api_base or os.environ.get("GROK_API_BASE") or _DEFAULT_API_BASE).rstrip("/")
        self._model = model or os.environ.get("GROK_MODEL") or _DEFAULT_MODEL
        self._api_url = f"{self._api_base}/v1/chat/completions"
        self._connect_timeout = connect_timeout or float(os.environ.get("GROK_CONNECT_TIMEOUT", "10"))
        self._read_timeout = read_timeout or float(os.environ.get("GROK_READ_TIMEOUT", "120"))
        self._lock = threading.Lock()
        self._gen = 0
        self._cancel = threading.Event()
        self._resp: requests.Response | None = None
        self._thread: threading.Thread | None = None
        self._api_key = self._load_api_key()

    @property
    def model_name(self) -> str:
        return self._model

    @staticmethod
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

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            resp = self._resp
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def search(
        self,
        query: str,
        mode: str = "detailed",
        web_enabled: bool = True,
        history: list[dict[str, str]] | None = None,
        source: str = "manual",
        feature: str = "search",
        on_chunk: Callable[[str], None] | None = None,
        on_done: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.cancel()
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._resp = None
        self._cancel.clear()
        t = threading.Thread(
            target=self._stream,
            args=(
                gen,
                query,
                mode,
                web_enabled,
                history or [],
                source,
                feature,
                on_chunk,
                on_done,
                on_error,
            ),
            daemon=True,
        )
        self._thread = t
        t.start()

    def _build_system_prompt(self, mode: str, web_enabled: bool) -> str:
        parts = [_BASE_SYSTEM]
        suffix = _MODE_SUFFIX.get(mode)
        if suffix:
            parts.append(suffix)
        if not web_enabled:
            parts.append(_NO_WEB)
        return "\n".join(parts)

    def _is_stale(self, gen: int) -> bool:
        with self._lock:
            return gen != self._gen

    def _stream(
        self,
        gen: int,
        query: str,
        mode: str,
        web_enabled: bool,
        history: list[dict[str, str]],
        source: str,
        feature: str,
        on_chunk: Callable[[str], None] | None,
        on_done: Callable[[str], None] | None,
        on_error: Callable[[str], None] | None,
    ) -> None:
        system_prompt = self._build_system_prompt(mode, web_enabled)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": query})

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
        }
        terminal_fired = False
        collected_content: list[str] = []
        start_time = datetime.now()
        run_id = get_run_recorder().start_run(
            feature=feature,
            source=source,
            model=self._model,
            mode=mode,
            web_enabled=web_enabled,
            input_text=query,
        )
        status_code: int | None = None

        def _fire_done() -> None:
            nonlocal terminal_fired
            if terminal_fired or self._is_stale(gen):
                return
            terminal_fired = True
            get_run_recorder().finish_run(
                run_id,
                success=True,
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                http_status=status_code,
            )
            if on_done:
                on_done("".join(collected_content))

        def _fire_error(msg: str) -> None:
            nonlocal terminal_fired
            if terminal_fired or self._is_stale(gen):
                return
            terminal_fired = True
            get_run_recorder().finish_run(
                run_id,
                success=False,
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                http_status=status_code,
                error_message=msg,
            )
            if on_error:
                on_error(msg)

        try:
            if self._cancel.is_set() or self._is_stale(gen):
                return
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            resp = requests.post(
                self._api_url,
                json=payload,
                headers=headers,
                stream=True,
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
                    _fire_error(parse_response_error(resp))
                    return
                for raw_line in resp.iter_lines(decode_unicode=True):
                    if self._cancel.is_set() or self._is_stale(gen):
                        return
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        content = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if content and on_chunk and not self._is_stale(gen):
                            collected_content.append(content)
                            on_chunk(content)
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue
            _fire_done()
        except Exception as exc:
            if self._cancel.is_set() or self._is_stale(gen):
                return
            logger.exception("search stream error")
            _fire_error(parse_request_exception(exc))
        finally:
            with self._lock:
                if self._gen == gen:
                    self._resp = None
