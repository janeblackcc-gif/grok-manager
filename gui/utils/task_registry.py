from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable


@dataclass
class TaskInfo:
    task_id: str
    label: str
    feature: str
    source: str
    status: str = "running"
    message: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    cancel: Callable[[], None] | None = None


class TaskRegistry:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskInfo] = {}
        self._listeners: list[Callable[[], None]] = []

    def start_task(
        self,
        *,
        label: str,
        feature: str,
        source: str,
        cancel: Callable[[], None] | None = None,
    ) -> str:
        task_id = uuid.uuid4().hex[:10]
        with self._lock:
            self._tasks[task_id] = TaskInfo(
                task_id=task_id,
                label=label,
                feature=feature,
                source=source,
                cancel=cancel,
            )
        self._notify()
        return task_id

    def update_task(self, task_id: str, message: str = "") -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.message = message
        self._notify()

    def finish_task(self, task_id: str, *, status: str, message: str = "") -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.status = status
            task.message = message
            if status in ("success", "error", "cancelled"):
                self._tasks.pop(task_id, None)
        self._notify()

    def active_tasks(self) -> list[TaskInfo]:
        with self._lock:
            return list(self._tasks.values())

    def on_change(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:
                pass


_REGISTRY: TaskRegistry | None = None


def get_task_registry() -> TaskRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = TaskRegistry()
    return _REGISTRY
