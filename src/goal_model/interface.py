"""Goal ingestion interface: how an agent accepts a well-defined goal.

``accept_goal`` is the single entry point through which a goal is offered to
an agent. It enforces the agent's declared :class:`GoalInterface` (schema
version, goal type, capacity) plus the metamodel's own rules (the model must
be well-formed, the goal must be owned by the agent, not already closed),
then activates the goal and records a telemetry event. Every failure is a
:class:`GoalRejection` carrying explicit reasons, so callers (API, CLI,
other agents) can explain why a goal was not accepted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from .registry import AGENT_ACTIVE, RegistryError
from .rules import find_issues
from .telemetry import (
    EVENT_ACTION_RECORDED,
    EVENT_GOAL_ACCEPTED,
    EVENT_GOAL_STATUS_CHANGED,
    Event,
    utcnow_iso,
)

TERMINAL_STATUSES = ("achieved", "abandoned")
ALLOWED_TRANSITIONS = {
    "proposed": {"active", "abandoned"},
    "active": {"achieved", "abandoned"},
    "achieved": set(),
    "abandoned": set(),
}


class GoalRejection(Exception):
    """A goal was not accepted; ``reasons`` explains every failed check."""

    def __init__(self, reasons: List[str]):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass
class Acceptance:
    """A ticket proving an agent accepted a goal through its interface."""

    ticket: str
    agent_id: str
    goal_id: str
    accepted_at: str
    interface_version: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticket": self.ticket,
            "agentId": self.agent_id,
            "goalId": self.goal_id,
            "acceptedAt": self.accepted_at,
            "interfaceVersion": self.interface_version,
        }


def goal_type_of(model, goal_id: str) -> str:
    """The goal's declared type (optional schema-tolerated field), default 'general'."""
    for raw in model.raw.get("goals", []):
        if raw.get("id") == goal_id:
            return str(raw.get("type", "general"))
    return "general"


def accept_goal(ctx, agent_id: str, goal_id: str) -> Acceptance:
    """Offer goal ``goal_id`` to agent ``agent_id``; return an Acceptance ticket.

    Raises :class:`GoalRejection` with all failed checks if the goal cannot
    be accepted.
    """
    reasons: List[str] = []

    try:
        agent = ctx.registry.get(agent_id)
    except RegistryError as exc:
        raise GoalRejection([str(exc)]) from exc
    if agent.status != AGENT_ACTIVE:
        reasons.append(f"agent '{agent_id}' is {agent.status}, not active")

    schema_version = str(ctx.model.raw.get("schemaVersion", "0.1.0"))
    if not agent.interface.accepts_schema_version(schema_version):
        reasons.append(
            f"agent interface does not accept schemaVersion {schema_version} "
            f"(accepts: {agent.interface.schema_versions})"
        )

    goal = ctx.model.goals.get(goal_id)
    if goal is None:
        raise GoalRejection([f"unknown goal: {goal_id}"])
    if goal.owner != agent_id:
        reasons.append(f"goal owner is '{goal.owner}', not '{agent_id}'")
    if goal.status in TERMINAL_STATUSES:
        reasons.append(f"goal is already {goal.status}")

    gtype = goal_type_of(ctx.model, goal_id)
    if not agent.interface.accepts_goal_type(gtype):
        reasons.append(
            f"agent interface does not accept goal type '{gtype}' "
            f"(accepts: {agent.interface.goal_types})"
        )

    active = [
        gid
        for gid, g in ctx.model.goals.items()
        if g.owner == agent_id and g.status == "active"
    ]
    if goal.status != "active" and len(active) >= agent.interface.max_active_goals:
        reasons.append(
            f"agent at capacity: {len(active)} active goals "
            f"(max {agent.interface.max_active_goals})"
        )

    errors = [i for i in find_issues(ctx.model) if i.severity == "error"]
    if errors:
        reasons.append("model is not well-formed: " + "; ".join(str(i) for i in errors))

    if reasons:
        raise GoalRejection(reasons)

    if goal.status == "proposed":
        ctx.set_goal_status(goal_id, "active")

    ticket = uuid.uuid4().hex[:12]
    accepted_at = utcnow_iso()
    ctx.events.append(
        EVENT_GOAL_ACCEPTED,
        agent_id=agent_id,
        goal_id=goal_id,
        ticket=ticket,
        goalType=gtype,
        interfaceVersion=agent.interface.version,
    )
    return Acceptance(
        ticket=ticket,
        agent_id=agent_id,
        goal_id=goal_id,
        accepted_at=accepted_at,
        interface_version=agent.interface.version,
    )


def record_action(ctx, agent_id: str, goal_id: str, action: str, detail: str = "") -> Event:
    """Record a goal-realizing action performed by an agent."""
    if goal_id not in ctx.model.goals:
        raise GoalRejection([f"unknown goal: {goal_id}"])
    return ctx.events.append(
        EVENT_ACTION_RECORDED,
        agent_id=agent_id,
        goal_id=goal_id,
        action=action,
        detail=detail,
    )


def transition(ctx, agent_id: str, goal_id: str, new_status: str, reason: str = "") -> Event:
    """Move a goal through its lifecycle, enforcing allowed transitions."""
    goal = ctx.model.goals.get(goal_id)
    if goal is None:
        raise GoalRejection([f"unknown goal: {goal_id}"])
    if goal.owner != agent_id:
        raise GoalRejection([f"goal owner is '{goal.owner}', not '{agent_id}'"])
    if new_status not in ALLOWED_TRANSITIONS:
        raise GoalRejection([f"unknown status: {new_status}"])
    if new_status not in ALLOWED_TRANSITIONS.get(goal.status, set()):
        raise GoalRejection(
            [f"cannot move goal from '{goal.status}' to '{new_status}'"]
        )
    if new_status == "abandoned" and not reason:
        raise GoalRejection(["abandoning a goal requires a reason"])
    ctx.set_goal_status(goal_id, new_status, abandon_reason=reason or None)
    return ctx.events.append(
        EVENT_GOAL_STATUS_CHANGED,
        agent_id=agent_id,
        goal_id=goal_id,
        fromStatus=goal.status,
        toStatus=new_status,
        reason=reason,
    )
