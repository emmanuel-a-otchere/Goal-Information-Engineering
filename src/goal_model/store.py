"""Operations store: runtime persistence for the agent-operations layer.

The GOAL model file remains the single source of truth for goal state. This
store holds only *runtime* state, kept in a directory next to the model:

- ``agents.json``        the agent registry (AgentRecord dicts)
- ``events.jsonl``       append-only telemetry event log
- ``assessments.json``   persisted assessment reports

All writes are atomic (write to a temp file, then replace).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List


class OperationsStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def agents_path(self) -> Path:
        return self.root / "agents.json"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def assessments_path(self) -> Path:
        return self.root / "assessments.json"

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _write_json(self, path: Path, data: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)

    def load_agents(self) -> List[Dict[str, Any]]:
        return self._read_json(self.agents_path, [])

    def save_agents(self, agents: List[Dict[str, Any]]) -> None:
        self._write_json(self.agents_path, agents)

    def load_assessments(self) -> List[Dict[str, Any]]:
        return self._read_json(self.assessments_path, [])

    def save_assessments(self, assessments: List[Dict[str, Any]]) -> None:
        self._write_json(self.assessments_path, assessments)

    def append_event(self, event: Dict[str, Any]) -> None:
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    def read_events(self) -> List[Dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: List[Dict[str, Any]] = []
        with open(self.events_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
