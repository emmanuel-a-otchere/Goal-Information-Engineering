"""Planning over GOAL models: state gaps, readiness, and pursuit order.

The planner layer is deliberately simple and deterministic: it turns the
model's declared structure (dependencies, refinement, status) into an
ordered plan. A goal here means "a desired state reachable from the current
state"; the planner's job is to expose the *gap* and a defensible order of
pursuit, not to invent domain actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .model import GoalModel


@dataclass
class Step:
    goal_id: str
    statement: str
    ready: bool
    blocked_by: List[str] = field(default_factory=list)
    depth: int = 0


@dataclass
class Plan:
    steps: List[Step] = field(default_factory=list)

    @property
    def ready_steps(self) -> List[Step]:
        return [s for s in self.steps if s.ready and not s.blocked_by]

    def as_dict(self) -> List[Dict]:
        return [
            {
                "goal": s.goal_id,
                "statement": s.statement,
                "ready": s.ready,
                "blockedBy": s.blocked_by,
                "depth": s.depth,
            }
            for s in self.steps
        ]


@dataclass
class StateGap:
    goal_id: str
    target: Optional[str]
    current: List[str] = field(default_factory=list)
    open_criteria: List[str] = field(default_factory=list)


class Planner:
    """Dependency- and refinement-aware pursuit planner.

    A goal is *ready* when: its status is not achieved/abandoned, every
    declared dependency is achieved, and (for subgoals) their parent is
    active. Blocked goals report what blocks them.
    """

    def state_gaps(self, model: GoalModel) -> List[StateGap]:
        current = [s.id for s in model.states.values() if s.is_current]
        gaps: List[StateGap] = []
        for g in model.goals.values():
            if g.status in ("achieved", "abandoned"):
                continue
            gaps.append(
                StateGap(
                    goal_id=g.id,
                    target=g.target_state,
                    current=list(current),
                    open_criteria=[c.description for c in g.success_criteria],
                )
            )
        return gaps

    def plan(self, model: GoalModel) -> Plan:
        steps: List[Step] = []
        achieved = {gid for gid, g in model.goals.items() if g.status == "achieved"}

        def depth_of(gid: str, seen: frozenset = frozenset()) -> int:
            if gid in seen or gid not in model.goals:
                return 0
            goal = model.goals[gid]
            if not goal.depends_on:
                return 0
            return 1 + max(
                (depth_of(d, seen | {gid}) for d in goal.depends_on if d in model.goals),
                default=0,
            )

        for gid, g in model.goals.items():
            if g.status in ("achieved", "abandoned"):
                continue
            unmet = [d for d in g.depends_on if d in model.goals and d not in achieved]
            parent_blockers = [
                p
                for p in model.goals.values()
                if gid in p.subgoals and p.status not in ("active", "achieved")
            ]
            blocked_by = unmet + [p.id for p in parent_blockers]
            steps.append(
                Step(
                    goal_id=gid,
                    statement=g.statement,
                    ready=not blocked_by,
                    blocked_by=blocked_by,
                    depth=depth_of(gid),
                )
            )

        # order: dependencies first (depth), then priority, then id
        prio_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, None: 4}
        steps.sort(key=lambda s: (s.depth, prio_rank.get(model.goals[s.goal_id].priority, 4), s.goal_id))
        return Plan(steps=steps)

    def progress(self, model: GoalModel) -> Dict[str, float]:
        """Fraction of goals achieved, overall and by top-level goal."""
        total = len(model.goals)
        achieved = sum(1 for g in model.goals.values() if g.status == "achieved")
        by_top: Dict[str, float] = {}
        for top in model.top_level_goals():
            closure = model.subgoal_closure(top)
            done = sum(
                1 for gid in closure if model.goals[gid].status == "achieved"
            )
            by_top[top] = round(done / len(closure), 3) if closure else 0.0
        return {
            "overall": round(achieved / total, 3) if total else 0.0,
            "byTopLevel": by_top,
        }
