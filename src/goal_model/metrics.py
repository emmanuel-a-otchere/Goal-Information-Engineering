"""Dashboard metrics: a read-model over the GOAL model + telemetry + assessments.

``compute_metrics`` derives everything the dashboard shows: per-agent load,
progress, adherence and activity; per-goal status, readiness (from the
planner), deadline risk, activity counts and latest assessment; plus totals
and the most recent events.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

from .planner import Planner
from .report import status_summary
from .telemetry import utcnow_iso


def compute_metrics(ctx) -> Dict[str, Any]:
    model = ctx.model
    planner = Planner()
    steps = {s.goal_id: s for s in planner.plan(model).steps}
    progress = planner.progress(model)

    events = ctx.events.all()
    assessments = ctx.store.load_assessments()
    latest_assessment: Dict[str, Dict[str, Any]] = {}
    for a in assessments:
        latest_assessment[a["goalId"]] = a

    today = date.today()
    goals: Dict[str, Any] = {}
    for gid, g in model.goals.items():
        goal_events = [e for e in events if e.goal_id == gid]
        step = steps.get(gid)
        risk = None
        if g.deadline and g.status not in ("achieved", "abandoned"):
            risk = (date.fromisoformat(g.deadline) - today).days
        la = latest_assessment.get(gid)
        goals[gid] = {
            "statement": g.statement,
            "owner": g.owner,
            "status": g.status,
            "priority": g.priority,
            "deadline": g.deadline,
            "deadlineRiskDays": risk,
            "ready": step.ready if step else False,
            "blockedBy": list(step.blocked_by) if step else [],
            "activities": len(goal_events),
            "lastActivityAt": goal_events[-1].ts if goal_events else None,
            "latestAssessment": (
                {
                    "verdict": la["verdict"],
                    "score": la["score"],
                    "assessor": la["assessor"],
                    "assessedAt": la["assessedAt"],
                }
                if la
                else None
            ),
        }

    agents: Dict[str, Any] = {}
    for rec in ctx.registry.list():
        owned = [gid for gid, g in model.goals.items() if g.owner == rec.id]
        agent_events = [e for e in events if e.agent_id == rec.id]
        agent_assessments = [a for a in assessments if a.get("agentId") == rec.id]
        adherence_scores = [
            a["adherence"]["score"]
            for a in agent_assessments
            if a.get("adherence", {}).get("score") is not None
        ]
        agents[rec.id] = {
            "name": rec.name,
            "type": rec.type,
            "status": rec.status,
            "goalTypes": list(rec.interface.goal_types),
            "maxActiveGoals": rec.interface.max_active_goals,
            "goals": len(owned),
            "activeGoals": sum(1 for gid in owned if model.goals[gid].status == "active"),
            "achievedGoals": sum(1 for gid in owned if model.goals[gid].status == "achieved"),
            "activities": len(agent_events),
            "lastActivityAt": agent_events[-1].ts if agent_events else None,
            "assessments": len(agent_assessments),
            "adherenceScore": (
                round(sum(adherence_scores) / len(adherence_scores), 3)
                if adherence_scores
                else None
            ),
        }

    return {
        "generatedAt": utcnow_iso(),
        "model": {"id": model.id, "name": model.name, "version": model.version},
        "progress": progress,
        "totals": {
            "goals": len(model.goals),
            "byStatus": status_summary(model),
            "agents": len(agents),
            "events": len(events),
            "assessments": len(assessments),
            "overallProgress": progress["overall"],
        },
        "agents": agents,
        "goals": goals,
        "recentEvents": [e.to_dict() for e in events[-20:]],
    }
