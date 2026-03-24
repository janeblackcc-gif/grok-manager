from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SESSIONS = 20
_MAX_RESULT_LEN = 50000


def _default_history_path() -> Path:
    try:
        app_data = os.environ.get("APPDATA")
        if app_data:
            base = Path(app_data) / "grok-manager"
        else:
            base = Path.home() / ".grok-manager"
        base.mkdir(parents=True, exist_ok=True)
        return base / "search_sessions.json"
    except Exception:
        logger.warning("Cannot create history dir, falling back to temp")
        import tempfile
        return Path(tempfile.gettempdir()) / "grok-manager-search_sessions.json"


def _validate_session(s: Any) -> bool:
    return (
        isinstance(s, dict)
        and isinstance(s.get("id"), str)
        and isinstance(s.get("messages"), list)
    )


class Session:
    """A single conversation session with Grok."""

    def __init__(
        self,
        session_id: str | None = None,
        title: str = "",
        messages: list[dict[str, str]] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        mode: str = "detailed",
        web_enabled: bool = True,
        source: str = "manual",
        feature: str = "search",
        model: str = "",
        tags: list[str] | None = None,
    ) -> None:
        self.id = session_id or uuid.uuid4().hex[:12]
        self.title = title
        self.messages: list[dict[str, str]] = messages or []
        now = datetime.now().isoformat(timespec="seconds")
        self.created_at = created_at or now
        self.updated_at = updated_at or now
        self.mode = mode
        self.web_enabled = web_enabled
        self.source = source
        self.feature = feature
        self.model = model
        self.tags = list(tags or [])

    @property
    def turn_count(self) -> int:
        return sum(1 for m in self.messages if m.get("role") == "user")

    @property
    def last_result(self) -> str:
        for m in reversed(self.messages):
            if m.get("role") == "assistant":
                return m.get("content", "")
        return ""

    @property
    def display_title(self) -> str:
        prefix = "[\u5212\u8bcd] " if self.source == "floating" else ""
        if self.title:
            return prefix + self.title
        for m in self.messages:
            if m.get("role") == "user":
                q = m["content"]
                return prefix + q[:30] + ("..." if len(q) > 30 else "")
        return prefix + "\u65b0\u5bf9\u8bdd"

    @property
    def first_query(self) -> str:
        for m in self.messages:
            if m.get("role") == "user":
                return m["content"]
        return ""

    def add_turn(self, query: str, result: str) -> None:
        self.messages.append({"role": "user", "content": query})
        if result:
            content = result[:_MAX_RESULT_LEN]
            self.messages.append({"role": "assistant", "content": content})
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "messages": self.messages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "mode": self.mode,
            "web_enabled": self.web_enabled,
            "source": self.source,
            "feature": self.feature,
            "model": self.model,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Session:
        return cls(
            session_id=d.get("id"),
            title=d.get("title", ""),
            messages=d.get("messages", []),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
            mode=d.get("mode", "detailed"),
            web_enabled=d.get("web_enabled", True),
            source=d.get("source", "manual"),
            feature=d.get("feature", "search"),
            model=d.get("model", ""),
            tags=d.get("tags", []),
        )


class SessionStore:

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_history_path()
        self._sessions: list[Session] = []
        self.load()

    def load(self) -> None:
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text("utf-8"))
                if isinstance(raw, list):
                    self._sessions = [
                        Session.from_dict(s) for s in raw if _validate_session(s)
                    ]
                else:
                    self._sessions = []
        except Exception:
            logger.warning("Failed to load session store")
            self._sessions = []

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = [s.to_dict() for s in self._sessions]
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), "utf-8"
            )
        except Exception:
            logger.warning("Failed to save session store to %s", self._path)

    def create_session(
        self,
        mode: str = "detailed",
        web: bool = True,
        source: str = "manual",
        title: str = "",
        feature: str = "search",
        model: str = "",
        tags: list[str] | None = None,
    ) -> Session:
        session = Session(
            mode=mode,
            web_enabled=web,
            source=source,
            title=title,
            feature=feature,
            model=model,
            tags=tags,
        )
        self._sessions.insert(0, session)
        if len(self._sessions) > _MAX_SESSIONS:
            self._sessions = self._sessions[:_MAX_SESSIONS]
        self.save()
        return session

    def create_session_from_turn(
        self,
        query: str,
        result: str,
        mode: str = "detailed",
        web: bool = True,
        source: str = "manual",
        title: str = "",
        feature: str = "search",
        model: str = "",
        tags: list[str] | None = None,
    ) -> Session:
        session = self.create_session(
            mode=mode,
            web=web,
            source=source,
            title=title,
            feature=feature,
            model=model,
            tags=tags,
        )
        session.add_turn(query, result)
        self.update_session(session)
        return session

    def get_session(self, session_id: str) -> Session | None:
        for session in self._sessions:
            if session.id == session_id:
                return session
        return None

    def update_session(self, session: Session) -> None:
        session.updated_at = datetime.now().isoformat(timespec="seconds")
        self._sessions = [s for s in self._sessions if s.id != session.id]
        self._sessions.insert(0, session)
        self.save()

    def get_all(self) -> list[Session]:
        return list(self._sessions)

    def delete_session(self, session_id: str) -> None:
        self._sessions = [s for s in self._sessions if s.id != session_id]
        self.save()

    def clear(self) -> None:
        self._sessions.clear()
        self.save()
