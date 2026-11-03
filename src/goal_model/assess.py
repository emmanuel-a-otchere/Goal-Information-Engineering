"""Assessment framework: assess an agent against a goal in a standard way.

Every assessment produces an :class:`Assessment` report: per-criterion
verdicts (pass / fail / unverified) with the evidence used, an adherence
section (deadline, constraints, obstacles), a performance section (recorded
activities over time), an overall verdict and a 0..1 score.

Assessors are pluggable and keyed by **goal type**: :class:`AssessorRegistry`
dispatches to a typed assessor when one is registered for the goal's
``type`` (an optional, schema-tolerated goal field), and falls back to
:class:`StandardAssessor` otherwise. To home in on a specific kind of goal,
register a typed assessor (see ``docs/OPERATIONS.md``); a goal type of
``"checklist"`` ships with a built-in :class:`ChecklistAssessor`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Protocol

from .interface import goal_type_of
from .model import evaluate_target, find_metric_record
from .telemetry import EVENT_CONSTRAINT_VIOLATED, EVENT_GOAL_ASSESSED, utcnow_iso

VERDICT_ACHIEVED = "achieved"
VERDICT_PARTIAL = "partial"
VERDICT_NOT_ACHIEVED = "not_achieved"

CRITERION_PASS = "pass"
CRITERION_FAIL = "fail"
CRITERION_UNVERIFIED = "unverified"


class AssessmentError(Exception):
    """Raised when an assessment cannot be performed."""


@dataclass
class CriterionResult:
    description: str
    verification: str
    verdict: str
    evidence: Optional[Any] = None
    note: str = ""
    metric: Optional[str] = None
    measurement: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "verification": self.verification,
            "verdict": self.verdict,
            "evidence": self.evidence,
            "note": self.note,
            "metric": self.metric,
            "measurement": self.measurement,
        }


@dataclass
class Assessment:
    id: str
    goal_id: str
    agent_id: str
    goal_type: str
    assessor: str
    assessed_at: str
    criteria: List[CriterionResult] = field(default_factory=list)
    adherence: Dict[str, Any] = field(default_factory=dict)
    performance: Dict[str, Any] = field(default_factory=dict)
    verdict: str = VERDICT_NOT_ACHIEVED
    score: float = 0.0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goalId": self.goal_id,
            "agentId": self.agent_id,
            "goalType": self.goal_type,
            "assessor": self.assessor,
            "assessedAt": self.assessed_at,
            "criteria": [c.to_dict() for c in self.criteria],
            "adherence": dict(self.adherence),
            "performance": dict(self.performance),
            "verdict": self.verdict,
            "score": self.score,
            "notes": list(self.notes),
        }

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "Assessment":
        return Assessment(
            id=raw["id"],
            goal_id=raw["goalId"],
            agent_id=raw["agentId"],
            goal_type=raw.get("goalType", "general"),
            assessor=raw.get("assessor", ""),
            assessed_at=raw.get("assessedAt", ""),
            criteria=[
                CriterionResult(
                    description=c["description"],
                    verification=c.get("verification", "manual"),
                    verdict=c.get("verdict", CRITERION_UNVERIFIED),
                    evidence=c.get("evidence"),
                    note=c.get("note", ""),
                    metric=c.get("metric"),
                    measurement=c.get("measurement"),
                )
                for c in raw.get("criteria", [])
            ],
            adherence=dict(raw.get("adherence", {})),
            performance=dict(raw.get("performance", {})),
            verdict=raw.get("verdict", VERDICT_NOT_ACHIEVED),
            score=float(raw.get("score", 0.0)),
            notes=list(raw.get("notes", [])),
        )


def _evidence_for(evidence: Dict[str, Any], description: str, index: int) -> Any:
    if description in evidence:
        return evidence[description]
    for key in (index, str(index)):
        if key in evidence:
            return evidence[key]
    return None


def _verdict_of(ev: Any) -> str:
    if ev is None:
        return CRITERION_UNVERIFIED
    if isinstance(ev, bool):
        return CRITERION_PASS if ev else CRITERION_FAIL
    if isinstance(ev, dict) and "pass" in ev:
        return CRITERION_PASS if ev["pass"] else CRITERION_FAIL
    return CRITERION_PASS


def _measurement_of(ev: Any) -> Optional[float]:
    """A numeric evidence value is a raw measurement for a metric-referenced criterion."""
    if ev is None or isinstance(ev, bool):
        return None
    if isinstance(ev, (int, float)):
        return float(ev)
    if isinstance(ev, str):
        try:
            return float(ev)
        except ValueError:
            return None
    if isinstance(ev, dict):
        v = ev.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _metric_verdict(c, ev: Any) -> tuple:
    """Evaluate a metric-referenced criterion with a target against a measurement.

    Returns (verdict, note, measurement). Falls back to explicit pass/fail
    evidence when the evidence is not numeric.
    """
    measurement = _measurement_of(ev)
    if measurement is None:
        verdict = _verdict_of(ev)
        note = "" if verdict != CRITERION_UNVERIFIED else "no evidence supplied"
        return verdict, note, None
    ok = evaluate_target(c.target, measurement)
    verdict = CRITERION_PASS if ok else CRITERION_FAIL
    rec = find_metric_record(c.metric)
    ref = f"{c.metric.get('id')}@{c.metric.get('version')}"
    dir_part = f", {rec.get('directionality')}" if rec and rec.get("directionality") else ""
    unit = c.target.get("unit") or (rec.get("unit") if rec else "") or ""
    note = (
        f"measured {measurement} vs {c.target.get('operator')} {c.target.get('value')} "
        f"{unit} ({ref}{dir_part})".strip()
    )
    ev_unit = ev.get("unit") if isinstance(ev, dict) else None
    if ev_unit and rec and rec.get("unit") and str(ev_unit).lower() != str(rec["unit"]).lower():
        note += f"; unit '{ev_unit}' mismatches metric unit '{rec['unit']}'"
    return verdict, note, measurement


def _parse_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


class Assessor(Protocol):
    """An assessor evaluates an agent's pursuit of one goal."""

    name: str

    def assess(self, ctx, goal_id: str, evidence: Optional[Dict[str, Any]] = None) -> Assessment:
        ...


class StandardAssessor:
    """The standard, goal-type-agnostic assessment.

    - Each success criterion is ``pass`` when evidence is supplied for it,
      ``fail`` when evidence explicitly fails it, else ``unverified``.
    - Verdict: ``achieved`` when every criterion passes, ``partial`` when
      some pass, ``not_achieved`` otherwise. Score = passed / total.
    - Adherence: deadline respected (achieved on time, or not yet due) and
      no recorded constraint violations for the goal.
    - Performance: recorded activities for the goal and days since the goal
      was accepted.
    """

    name = "standard"

    def assess(self, ctx, goal_id: str, evidence: Optional[Dict[str, Any]] = None) -> Assessment:
        goal = ctx.model.goals.get(goal_id)
        if goal is None:
            raise AssessmentError(f"unknown goal: {goal_id}")
        evidence = evidence or {}

        criteria: List[CriterionResult] = []
        for i, c in enumerate(goal.success_criteria):
            ev = _evidence_for(evidence, c.description, i)
            metric_id = c.metric.get("id") if c.metric else None
            if c.metric and c.target:
                verdict, note, measurement = _metric_verdict(c, ev)
            else:
                verdict = _verdict_of(ev)
                measurement = None
                note = "" if verdict != CRITERION_UNVERIFIED else "no evidence supplied"
                if c.metric and not c.target and verdict == CRITERION_UNVERIFIED:
                    note = "metric referenced but no target; add a target or supply pass/fail evidence"
            criteria.append(
                CriterionResult(
                    description=c.description,
                    verification=c.verification,
                    verdict=verdict,
                    evidence=ev,
                    note=note,
                    metric=metric_id,
                    measurement=measurement,
                )
            )

        total = len(criteria)
        passed = sum(1 for c in criteria if c.verdict == CRITERION_PASS)
        if total == 0:
            verdict = VERDICT_NOT_ACHIEVED
        elif passed == total:
            verdict = VERDICT_ACHIEVED
        elif passed > 0:
            verdict = VERDICT_PARTIAL
        else:
            verdict = VERDICT_NOT_ACHIEVED
        score = round(passed / total, 3) if total else 0.0

        adherence = self._adherence(ctx, goal)
        performance = self._performance(ctx, goal_id)

        return Assessment(
            id=uuid.uuid4().hex[:12],
            goal_id=goal_id,
            agent_id=goal.owner,
            goal_type=goal_type_of(ctx.model, goal_id),
            assessor=self.name,
            assessed_at=utcnow_iso(),
            criteria=criteria,
            adherence=adherence,
            performance=performance,
            verdict=verdict,
            score=score,
            notes=[],
        )

    def _adherence(self, ctx, goal) -> Dict[str, Any]:
        deadline_ok: Optional[bool] = None
        if goal.deadline:
            due = date.fromisoformat(goal.deadline)
            deadline_ok = goal.status == "achieved" or date.today() <= due
        violations = ctx.events.filter(goal_id=goal.id, type=EVENT_CONSTRAINT_VIOLATED)
        constraints_respected = not violations
        checks = [v for v in (deadline_ok, constraints_respected) if v is not None]
        score = round(sum(1 for v in checks if v) / len(checks), 3) if checks else None
        return {
            "deadline": goal.deadline,
            "deadlineOk": deadline_ok,
            "constraintsRespected": constraints_respected,
            "constraintViolations": len(violations),
            "score": score,
        }

    def _performance(self, ctx, goal_id: str) -> Dict[str, Any]:
        events = ctx.events.filter(goal_id=goal_id)
        actions = [e for e in events if e.type == "action.recorded"]
        accepted = next((e for e in events if e.type == "goal.accepted"), None)
        first = _parse_ts(events[0].ts) if events else None
        last = _parse_ts(events[-1].ts) if events else None
        days_active = None
        if accepted is not None and first is not None:
            days_active = max(0, ((last or first) - first).days)
        return {
            "activities": len(events),
            "actions": len(actions),
            "acceptedAt": accepted.ts if accepted else None,
            "firstActivityAt": events[0].ts if events else None,
            "lastActivityAt": events[-1].ts if events else None,
            "daysActive": days_active,
        }


class ChecklistAssessor:
    """Typed assessor for goal type ``checklist``: every criterion must pass
    with evidence, and no unmitigated obstacle may threaten the goal."""

    name = "checklist"
    goal_types = ["checklist"]

    def assess(self, ctx, goal_id: str, evidence: Optional[Dict[str, Any]] = None) -> Assessment:
        base = StandardAssessor().assess(ctx, goal_id, evidence=evidence)
        base.assessor = self.name
        open_obstacles = [
            o.id
            for o in ctx.model.obstacles.values()
            if goal_id in o.threatens and o.mitigation is None
        ]
        if open_obstacles:
            base.notes.append(f"unmitigated obstacles: {', '.join(open_obstacles)}")
            if base.verdict == VERDICT_ACHIEVED:
                base.verdict = VERDICT_PARTIAL
                base.score = round(base.score * 0.9, 3)
        return base


class AssessorRegistry:
    """Dispatches assessments to typed assessors, falling back to standard."""

    def __init__(self, fallback: Optional[Assessor] = None):
        self._by_type: Dict[str, Assessor] = {}
        self._fallback = fallback or StandardAssessor()

    @classmethod
    def default(cls) -> "AssessorRegistry":
        registry = cls()
        registry.register("checklist", ChecklistAssessor())
        return registry

    def register(self, goal_type: str, assessor: Assessor) -> None:
        self._by_type[goal_type] = assessor

    def for_goal_type(self, goal_type: str) -> Assessor:
        return self._by_type.get(goal_type, self._fallback)

    def types(self) -> List[str]:
        return sorted(self._by_type)


def assess_goal(
    ctx,
    goal_id: str,
    goal_type: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
    registry: Optional[AssessorRegistry] = None,
) -> Assessment:
    """Assess the owning agent against ``goal_id`` and persist the report.

    The assessor is chosen by the explicit ``goal_type`` if given, else by the
    goal's declared ``type`` field, else the standard fallback. The report is
    appended to the store's assessments and a ``goal.assessed`` event is
    logged.
    """
    registry = registry or ctx.assessors
    goal = ctx.model.goals.get(goal_id)
    if goal is None:
        raise AssessmentError(f"unknown goal: {goal_id}")
    gtype = goal_type or goal_type_of(ctx.model, goal_id)
    assessor = registry.for_goal_type(gtype)
    assessment = assessor.assess(ctx, goal_id, evidence=evidence)
    assessment.goal_type = gtype
    assessment.assessor = assessor.name
    if not assessment.agent_id:
        assessment.agent_id = goal.owner

    assessments = ctx.store.load_assessments()
    assessments.append(assessment.to_dict())
    ctx.store.save_assessments(assessments)
    ctx.events.append(
        EVENT_GOAL_ASSESSED,
        agent_id=assessment.agent_id,
        goal_id=goal_id,
        verdict=assessment.verdict,
        score=assessment.score,
        assessor=assessment.assessor,
        goalType=gtype,
    )
    return assessment
