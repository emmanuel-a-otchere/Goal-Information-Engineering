"""Adapters: bridges between GOAL models and external systems.

The core stays minimal; every integration (issue trackers, OKR tools,
CI pipelines, calendars) is an optional adapter implementing one of the
protocols below. Adapters are *external* to the core metamodel and must
never require schema changes to function.

Two-way model:

- **Sink** — write goals *out* to a system (create issues for subgoals,
  register deadlines in a calendar, trigger CI jobs for executable
  criteria).
- **Source** — read state *back* from a system (issue status → goal
  status, CI result → criterion verification) as ``Update`` proposals
  that the user reviews before applying.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol

from .model import GoalModel


@dataclass
class Update:
    """A proposed change to the model, produced by a Source adapter."""

    goal_id: str
    field: str  # e.g. "status", "evidence"
    value: object
    reason: str = ""

    def apply(self, model: GoalModel, validate: bool = True) -> GoalModel:
        """Return a copy of the model with this update applied."""
        import copy
        import json

        raw = copy.deepcopy(model.raw)
        goal = next(g for g in raw["goals"] if g["id"] == self.goal_id)
        goal[self.field] = self.value
        new_model = GoalModel(raw)
        if validate:
            from .rules import find_issues

            errors = [i for i in find_issues(new_model) if i.severity == "error"]
            if errors:
                raise ValueError(f"update would invalidate model: {errors}")
        return new_model


class Sink(Protocol):
    """Writes goals out to an external system."""

    name: str

    def push(self, model: GoalModel, goal_ids: Optional[List[str]] = None) -> Dict[str, str]:
        """Push goals (default: all) and return a mapping goal id -> external id."""
        ...


class Source(Protocol):
    """Reads state back from an external system."""

    name: str

    def pull(self, model: GoalModel) -> List[Update]:
        """Return proposed updates based on the external system's state."""
        ...


# -- built-in reference adapters -------------------------------------------


class StdoutSink:
    """A no-op sink that prints what would be pushed. Useful for testing
    adapter wiring and as a template for real integrations."""

    name = "stdout"

    def push(self, model: GoalModel, goal_ids: Optional[List[str]] = None) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for gid in goal_ids or list(model.goals):
            goal = model.goals[gid]
            external_id = f"stdout:{gid}"
            print(f"[stdout] {external_id}: {goal.statement}")
            mapping[gid] = external_id
        return mapping


class CsvExport:
    """Export goals to CSV — the simplest real-world distribution path."""

    name = "csv"

    def export(self, model: GoalModel, goal_ids: Optional[List[str]] = None) -> str:
        header = "id,statement,owner,status,priority,deadline,refinement,subgoals"
        rows = [header]
        for gid in goal_ids or list(model.goals):
            g = model.goals[gid]
            stmt = '"' + g.statement.replace('"', '""') + '"'
            rows.append(
                ",".join(
                    [
                        gid,
                        stmt,
                        g.owner,
                        g.status,
                        g.priority or "",
                        g.deadline or "",
                        g.refinement or "",
                        " ".join(g.subgoals),
                    ]
                )
            )
        return "\n".join(rows) + "\n"


ADAPTERS = {"stdout": StdoutSink, "csv": CsvExport}
