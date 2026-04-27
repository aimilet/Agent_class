from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Callable


class BackgroundJobCancelled(RuntimeError):
    pass


@dataclass
class BackgroundJobRecord:
    object_type: str
    object_public_id: str
    label: str
    thread: Thread
    started_at: datetime
    cancel_requested: bool = False
    finished_at: datetime | None = None
    error_message: str | None = None

    @property
    def active(self) -> bool:
        return self.thread.is_alive()


class BackgroundJobRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[tuple[str, str], BackgroundJobRecord] = {}

    def start(
        self,
        *,
        object_type: str,
        object_public_id: str,
        label: str,
        target: Callable[[], None],
    ) -> BackgroundJobRecord:
        key = (object_type, object_public_id)
        with self._lock:
            existing = self._jobs.get(key)
            if existing is not None and existing.active:
                raise RuntimeError(f"{label} 已在运行中。")

            holder: dict[str, BackgroundJobRecord] = {}

            def runner() -> None:
                error_message: str | None = None
                try:
                    target()
                except Exception as exc:
                    error_message = f"{type(exc).__name__}: {exc}"
                finally:
                    with self._lock:
                        record = holder["record"]
                        record.finished_at = datetime.now(UTC)
                        record.error_message = error_message

            thread = Thread(
                target=runner,
                name=f"{object_type}:{object_public_id}",
                daemon=True,
            )
            record = BackgroundJobRecord(
                object_type=object_type,
                object_public_id=object_public_id,
                label=label,
                thread=thread,
                started_at=datetime.now(UTC),
            )
            holder["record"] = record
            self._jobs[key] = record
            thread.start()
            return record

    def is_active(self, object_type: str, object_public_id: str) -> bool:
        with self._lock:
            record = self._jobs.get((object_type, object_public_id))
            return bool(record and record.active)

    def request_cancel(self, object_type: str, object_public_id: str) -> bool:
        with self._lock:
            record = self._jobs.get((object_type, object_public_id))
            if record is None or not record.active:
                return False
            record.cancel_requested = True
            return True

    def cancel_requested(self, object_type: str, object_public_id: str) -> bool:
        with self._lock:
            record = self._jobs.get((object_type, object_public_id))
            return bool(record and record.cancel_requested)

    def raise_if_cancel_requested(self, object_type: str, object_public_id: str) -> None:
        if self.cancel_requested(object_type, object_public_id):
            raise BackgroundJobCancelled(f"{object_type}:{object_public_id} 已收到停止请求。")


_REGISTRY = BackgroundJobRegistry()


def get_background_job_registry() -> BackgroundJobRegistry:
    return _REGISTRY
