from __future__ import annotations

import json
from typing import Any

import requests


def _extract_message(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    error = payload.get("error")
    if not isinstance(error, dict):
        return "", ""
    message = str(error.get("message") or "").strip()
    code = str(error.get("code") or "").strip()
    return message, code


def parse_http_error(status_code: int, body_text: str = "") -> str:
    message = ""
    code = ""
    if body_text:
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            payload = None
        message, code = _extract_message(payload)

    if status_code == 429 or code == "rate_limit_exceeded":
        return message or "请求频率过高或当前没有可用 token，请稍后重试。"
    if status_code == 502:
        return message or "上游服务暂时不可用（502），请稍后重试。"
    if status_code == 401:
        return message or "API 认证失败，请检查 API Key。"
    if status_code == 400:
        return message or "请求参数无效，请检查输入内容。"
    if message:
        return f"{message} (HTTP {status_code})"
    return f"API 返回 HTTP {status_code}"


def parse_request_exception(exc: Exception) -> str:
    if isinstance(exc, requests.ConnectionError):
        return "无法连接 Grok2API 服务，请先在 Services 页面启动。"
    if isinstance(exc, requests.Timeout):
        return "请求超时，请稍后重试。"
    if isinstance(exc, requests.RequestException):
        response = exc.response
        if response is not None:
            return parse_http_error(response.status_code, _safe_text(response))
    return str(exc) or "请求失败"


def parse_response_error(response: requests.Response) -> str:
    return parse_http_error(response.status_code, _safe_text(response))


def _safe_text(response: requests.Response) -> str:
    try:
        return response.text[:1000]
    except Exception:
        return ""
