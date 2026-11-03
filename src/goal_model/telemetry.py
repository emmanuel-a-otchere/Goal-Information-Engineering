"""Telemetry: an append-only log of goal-realizing activities and actions.

Every state-changing operation in the operations layer (accepting a goal,
changing its status, recording an action, checking a criterion, raising an
obstacle, running an assessment) appends an event here. The dashboard and
the metrics read-model are derived from this log, which also serves as the
timestamped evidence/audit trail foreseen in the metamodel roadmap.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

EVENT_AGENT_REGISTERED = "agent.registered"
EVENT_AGENT_RETIRED = "agent.retired"
EVENT_GOAL_ACCEPTED = "goal.accepted"
EVENT_GOAL_STATUS_CHANGED = "goal.status_changed"
EVENT_ACTION_RECORDED = "action.recorded"
EVENT_CRITERION_CHECKED = "criterion.checked"
EVENT_OBSTACLE_RAISED = "obstacle.raised"
EVENT_CONSTRAINT_VIOLATED = "constraint.violated"
EVENT_GOAL_ASSESSED = "goal.assessed"

ACTIVITY_EVENT_TYPES = (
    EVENT_ACTION_RECORDED,
    EVENT_CRITERION_CHECKED,
    EVENT_OBSTACLE_RAISED,
    EVENT_CONSTRAINT_VIOLATED,
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Event:
    type: str
    agent_id: str = ""
    goal_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = utcnow_iso()
        if not self.id:
            self.id = uuid.uuid4().hex[:12]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "type": self.type,
            "agentId": self.agent_id,
            "goalId": self.goal_id,
            "payload": self.payload,
        }

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "Event":
        return Event(
            type=raw["type"],
            agent_id=raw.get("agentId", ""),
            goal_id=raw.get("goalId", ""),
            payload=dict(raw.get("payload", {})),
            ts=raw.get("ts", ""),
            id=raw.get("id", ""),
        )


class EventLog:
    """Append-only event log backed by the operations store (JSONL)."""

    def __init__(self, store):
        self.store = store

    def append(self, type: str, agent_id: str = "", goal_id: str = "", **payload: Any) -> Event:
        event = Event(type=type, agent_id=agent_id, goal_id=goal_id, payload=payload)
        self.store.append_event(event.to_dict())
        return event

    def all(self) -> List[Event]:
        return [Event.from_dict(d) for d in self.store.read_events()]

    def filter(
        self,
        agent_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Event]:
        events = self.all()
        if agent_id is not None:
            events = [e for e in events if e.agent_id == agent_id]
        if goal_id is not None:
            events = [e for e in events if e.goal_id == goal_id]
        if type is not None:
            events = [e for e in events if e.type == type]
        if limit is not None:
            events = events[-limit:]
        return events
