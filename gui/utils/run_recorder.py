from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_RECENT = 200


def _default_record_path() -> Path:
    app_data = os.environ.get("APPDATA")
    if app_data:
        base = Path(app_data) / "grok-manager"
    else:
        base = Path.home() / ".grok-manager"
    base.mkdir(parents=True, exist_ok=True)
    return base / "run_records.jsonl"


def summarize_text(text: str, limit: int = 160) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def classify_error(message: str) -> str:
    lowered = (message or "").lower()
    if not lowered:
        return ""
    if "429" in lowered or "rate limit" in lowered:
        return "rate_limited"
    if "502" in lowered or "bad gateway" in lowered or "upstream" in lowered:
        return "upstream_error"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "connection" in lowered or "refused" in lowered or "unreachable" in lowered:
        return "connection_error"
    return "request_error"


@dataclass
class RunRecord:
    run_id: str
    timestamp: str
    feature: str
    source: str
    model: str
    mode: str = ""
    web_enabled: bool | None = None
    input_summary: str = ""
    success: bool = False
    duration_ms: int = 0
    http_status: int | None = None
    error_type: str = ""
    error_message: str = ""
    output_path: str = ""
    output_url: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RunRecorder:

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_record_path()
        self._lock = threading.Lock()
        self._active: dict[str, RunRecord] = {}

    @property
    def path(self) -> Path:
        return self._path

    def start_run(
        self,
        *,
        feature: str,
        source: str,
        model: str,
        mode: str = "",
        web_enabled: bool | None = None,
        input_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        run_id = uuid.uuid4().hex[:12]
        record = RunRecord(
            run_id=run_id,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            feature=feature,
            source=source,
            model=model,
            mode=mode,
            web_enabled=web_enabled,
            input_summary=summarize_text(input_text),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._active[run_id] = record
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        success: bool,
        duration_ms: int,
        http_status: int | None = None,
        error_message: str = "",
        output_path: str = "",
        output_url: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            record = self._active.pop(run_id, None)
        if record is None:
            return
        record.success = success
        record.duration_ms = duration_ms
        record.http_status = http_status
        record.error_message = error_message
        record.error_type = classify_error(error_message)
        record.output_path = output_path
        record.output_url = output_url
        if tags:
            record.tags = list(tags)
        if metadata:
            record.metadata.update(metadata)
        self._append_record(record)

    def annotate_run(
        self,
        run_id: str,
        *,
        output_path: str = "",
        output_url: str = "",
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        if not run_id:
            return
        records = self.load_recent(limit=_MAX_RECENT)
        updated = False
        for record in records:
            if record.run_id != run_id:
                continue
            if output_path:
                record.output_path = output_path
            if output_url:
                record.output_url = output_url
            if metadata:
                record.metadata.update(metadata)
            if tags:
                existing = list(record.tags)
                for tag in tags:
                    if tag not in existing:
                        existing.append(tag)
                record.tags = existing
            updated = True
            break
        if updated:
            self._rewrite(records)

    def load_recent(self, limit: int = 20) -> list[RunRecord]:
        if not self._path.exists():
            return []
        records: list[RunRecord] = []
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    records.append(RunRecord(**json.loads(line)))
        except Exception:
            logger.exception("Failed to load run records")
            return []
        return list(reversed(records[-limit:]))

    def _append_record(self, record: RunRecord) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("Failed to append run record")

    def _rewrite(self, records: list[RunRecord]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                for record in reversed(records[-_MAX_RECENT:]):
                    f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
            os.replace(str(tmp), str(self._path))
        except Exception:
            logger.exception("Failed to rewrite run records")


_RECORDER: RunRecorder | None = None


def get_run_recorder() -> RunRecorder:
    global _RECORDER
    if _RECORDER is None:
        _RECORDER = RunRecorder()
    return _RECORDER
