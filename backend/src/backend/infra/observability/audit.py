from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.domain.enums import ActorType
from backend.domain.models import AuditEvent


class AuditService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        event_type: str,
        object_type: str,
        object_public_id: str,
        actor_type: str = ActorType.SYSTEM,
        actor_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            public_id=AuditEvent.build_public_id(),
            event_type=event_type,
            object_type=object_type,
            object_public_id=object_public_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_payload_json=payload,
        )
        self.session.add(event)
        self.session.flush()
        return event
