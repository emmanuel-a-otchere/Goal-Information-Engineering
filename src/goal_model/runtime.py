"""Runtime context: a GOAL model bound to an operations store.

Both executable surfaces of the operations layer — the CLI and the loopback
REST server — share this context, so behavior is identical across them. The
context owns the in-memory model, persists model mutations atomically, and
wires together the registry, telemetry log, and assessor registry.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .assess import AssessorRegistry, assess_goal
from .interface import accept_goal, record_action, transition
from .metrics import compute_metrics
from .model import GoalModel, load, load_dict
from .registry import AgentRegistry
from .rules import find_issues
from .store import OperationsStore
from .telemetry import EventLog

DEFAULT_STORE_DIR = ".goal-ops"


class RuntimeContext:
    def __init__(self, model_path: str | Path, store_dir: str | Path = DEFAULT_STORE_DIR):
        self.model_path = Path(model_path)
        self.model: GoalModel = load(self.model_path)
        self.store = OperationsStore(store_dir)
        self.events = EventLog(self.store)
        self.registry = AgentRegistry(self.store, self.events)
        self.assessors = AssessorRegistry.default()

    def reload(self) -> None:
        self.model = load(self.model_path)

    def save_model(self) -> None:
        """Persist the in-memory model back to its file, atomically."""
        tmp = self.model_path.with_suffix(self.model_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.model.raw, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, self.model_path)

    def set_goal_status(
        self, goal_id: str, status: str, abandon_reason: Optional[str] = None
    ) -> None:
        """Update a goal's status in the raw model, validate, and persist."""
        raw = json.loads(json.dumps(self.model.raw))
        goal = next((g for g in raw["goals"] if g["id"] == goal_id), None)
        if goal is None:
            raise ValueError(f"unknown goal: {goal_id}")
        goal["status"] = status
        if abandon_reason is not None:
            goal["abandonReason"] = abandon_reason
        elif "abandonReason" in goal and status != "abandoned":
            del goal["abandonReason"]
        new_model = load_dict(raw)
        errors = [i for i in find_issues(new_model) if i.severity == "error"]
        if errors:
            raise ValueError(
                "status change would invalidate model: " + "; ".join(str(i) for i in errors)
            )
        self.model = new_model
        self.save_model()

    # -- operations-layer entry points (shared by CLI and server) ---------

    def accept_goal(self, agent_id: str, goal_id: str):
        return accept_goal(self, agent_id, goal_id)

    def record_action(self, agent_id: str, goal_id: str, action: str, detail: str = ""):
        return record_action(self, agent_id, goal_id, action, detail)

    def transition(self, agent_id: str, goal_id: str, new_status: str, reason: str = ""):
        return transition(self, agent_id, goal_id, new_status, reason)

    def assess_goal(
        self,
        goal_id: str,
        goal_type: Optional[str] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ):
        return assess_goal(self, goal_id, goal_type=goal_type, evidence=evidence)

    def metrics(self) -> Dict[str, Any]:
        return compute_metrics(self)
