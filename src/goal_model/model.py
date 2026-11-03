"""Loading and in-memory representation of GOAL models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schema" / "goal.schema.json"
METRIC_REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent / "schema" / "metric-registry.json"


@dataclass
class Agent:
    id: str
    name: str
    type: str
    contact: Optional[str] = None


@dataclass
class State:
    id: str
    description: str
    is_current: bool = False


@dataclass
class Criterion:
    description: str
    evidence: Optional[str] = None
    verification: str = "manual"
    metric: Optional[Dict[str, Any]] = None
    target: Optional[Dict[str, Any]] = None


@dataclass
class Constraint:
    id: str
    description: str
    kind: str


@dataclass
class Obstacle:
    id: str
    description: str
    threatens: List[str]
    mitigation: Optional[str] = None

    @staticmethod
    def _as_list(value: Any) -> List[str]:
        if value is None:
            return []
        return [value] if isinstance(value, str) else list(value)


@dataclass
class Goal:
    id: str
    statement: str
    owner: str
    target_state: Optional[str] = None
    success_criteria: List[Criterion] = field(default_factory=list)
    contributors: List[str] = field(default_factory=list)
    priority: Optional[str] = None
    status: str = "proposed"
    deadline: Optional[str] = None
    subgoals: List[str] = field(default_factory=list)
    refinement: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    abandon_reason: Optional[str] = None


class GoalModel:
    """An in-memory GOAL model with lookup indexes."""

    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.id: str = raw["id"]
        self.name: str = raw["name"]
        self.version: str = raw["version"]
        self.description: Optional[str] = raw.get("description")

        self.agents: Dict[str, Agent] = {
            a["id"]: Agent(
                id=a["id"], name=a["name"], type=a["type"], contact=a.get("contact")
            )
            for a in raw.get("agents", [])
        }
        self.states: Dict[str, State] = {
            s["id"]: State(
                id=s["id"], description=s["description"], is_current=s.get("isCurrent", False)
            )
            for s in raw.get("states", [])
        }
        self.goals: Dict[str, Goal] = {}
        for g in raw.get("goals", []):
            self.goals[g["id"]] = Goal(
                id=g["id"],
                statement=g["statement"],
                owner=g.get("owner", ""),
                target_state=g.get("targetState"),
                success_criteria=[
                    Criterion(
                        description=c["description"],
                        evidence=c.get("evidence"),
                        verification=c.get("verification", "manual"),
                        metric=c.get("metric"),
                        target=c.get("target"),
                    )
                    for c in g.get("successCriteria", [])
                ],
                contributors=list(g.get("contributors", [])),
                priority=g.get("priority"),
                status=g.get("status", "proposed"),
                deadline=g.get("deadline"),
                subgoals=list(g.get("subgoals", [])),
                refinement=g.get("refinement"),
                depends_on=list(g.get("dependsOn", [])),
                constraints=list(g.get("constraints", [])),
                abandon_reason=g.get("abandonReason"),
            )
        self.obstacles: Dict[str, Obstacle] = {
            o["id"]: Obstacle(
                id=o["id"],
                description=o["description"],
                threatens=Obstacle._as_list(o.get("threatens")),
                mitigation=o.get("mitigation"),
            )
            for o in raw.get("obstacles", [])
        }
        self.constraints: Dict[str, Constraint] = {
            c["id"]: Constraint(id=c["id"], description=c["description"], kind=c["kind"])
            for c in raw.get("constraints", [])
        }

    # -- queries ---------------------------------------------------------

    def subgoal_closure(self, goal_id: str) -> set:
        """All goals reachable from goal_id via subgoal links."""
        seen: set = set()
        stack = [goal_id]
        while stack:
            gid = stack.pop()
            if gid in seen:
                continue
            seen.add(gid)
            goal = self.goals.get(gid)
            if goal:
                stack.extend(goal.subgoals)
        return seen

    def top_level_goals(self) -> List[str]:
        """Goals that are not a subgoal of any other goal."""
        referenced = {s for g in self.goals.values() for s in g.subgoals}
        return [gid for gid in self.goals if gid not in referenced]


def load_schema() -> Dict[str, Any]:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_metric_registry() -> Dict[str, Any]:
    """Pointer registry of external metric-catalog records (schema/metric-registry.json)."""
    with open(METRIC_REGISTRY_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load(path: str | Path) -> GoalModel:
    """Load a GOAL model from a JSON file."""
    with open(path, "r", encoding="utf-8") as fh:
        return GoalModel(json.load(fh))


def load_dict(raw: Dict[str, Any]) -> GoalModel:
    return GoalModel(raw)
