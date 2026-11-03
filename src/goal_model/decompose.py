"""Goal decomposition: propose candidate subgoals for a goal.

Decomposition is *suggestion, not mutation*: decomposers return candidate
goal dictionaries; the caller validates and inserts them explicitly via
:meth:`apply_decomposition`. Two decomposers ship:

- :class:`TemplateDecomposer` — fully deterministic, offline. Derives
  subgoals from the goal's own structure: obstacles, criteria, and a
  plan/measure/verify pattern.
- :class:`LLMDecomposer` — takes any callable ``(prompt: str) -> str`` that
  returns JSON (an LLM client, a mock, a scripted response) and turns free
  text into candidate goals. The library never calls a network service
  itself; the callable is injected by the caller.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from .model import GoalModel
from .rules import find_issues

DEFAULT_REFINEMENT = "and"


class DecompositionError(Exception):
    """Raised when candidate subgoals cannot be applied."""


def _next_id(model: GoalModel, goal_id: str, n: int) -> str:
    return f"{goal_id}-sub{n}"


class TemplateDecomposer:
    """Deterministic, structure-driven decomposition.

    Sources of candidate subgoals, in order:

    1. **Obstacle mitigations** — every obstacle threatening the goal that
       has no mitigation goal yet suggests one subgoal.
    2. **Criterion milestones** — every success criterion suggests a
       subgoal that establishes it.
    3. **Plan pattern** — a stable 'prepare / pursue / verify' triple, so
       the goal bottoms out in checkable leaves (design rule R4).

    Candidates inherit owner and deadline from the parent goal.
    """

    name = "template"

    def decompose(self, model: GoalModel, goal_id: str) -> List[Dict[str, Any]]:
        goal = model.goals.get(goal_id)
        if goal is None:
            raise DecompositionError(f"unknown goal: {goal_id}")
        candidates: List[Dict[str, Any]] = []
        n = 1

        def add(statement: str, criterion: Optional[str] = None, priority: Optional[str] = None) -> None:
            nonlocal n
            gid = _next_id(model, goal_id, n)
            n += 1
            cand: Dict[str, Any] = {
                "id": gid,
                "statement": statement,
                "owner": goal.owner,
                "status": "proposed",
                "successCriteria": [
                    {
                        "description": criterion or f"Goal '{gid}' is verifiably satisfied.",
                        "verification": "manual",
                    }
                ],
            }
            if goal.deadline:
                cand["deadline"] = goal.deadline
            if priority:
                cand["priority"] = priority
            candidates.append(cand)

        # 1. obstacle mitigations
        for obstacle in model.obstacles.values():
            if goal_id in obstacle.threatens and obstacle.mitigation is None:
                add(f"Mitigate obstacle: {obstacle.description}")

        # 2. criterion milestones
        for crit in goal.success_criteria:
            add(f"Establish criterion: {crit.description}")

        # 3. plan pattern
        add(f"Prepare: gather what is needed to pursue '{goal.statement}'")
        add(f"Pursue: execute the work required for '{goal.statement}'")
        add(f"Verify: check every success criterion of '{goal.statement}'")

        return candidates


class LLMDecomposer:
    """LLM-assisted decomposition via an injected callable.

    ``llm_call`` receives a prompt and must return a JSON array of goal
    objects (statement + optional success criteria). The decomposer assigns
    ids and owners locally and never trusts the model output blindly:
    candidates must still pass schema validation on apply.
    """

    name = "llm"

    def __init__(self, llm_call: Callable[[str], str]):
        self._llm_call = llm_call

    def _prompt(self, goal, model: GoalModel) -> str:
        criteria = "; ".join(c.description for c in goal.success_criteria) or "(none)"
        obstacles = "; ".join(
            o.description for o in model.obstacles.values() if goal.id in o.threatens
        )
        return (
            "Decompose the following goal into 2-6 concrete subgoals. "
            "Respond with ONLY a JSON array of objects with keys "
            '"statement" (string) and "successCriteria" (array of strings).\n'
            f"Goal: {goal.statement}\n"
            f"Success criteria: {criteria}\n"
            f"Known obstacles: {obstacles or '(none)'}\n"
        )

    def decompose(self, model: GoalModel, goal_id: str) -> List[Dict[str, Any]]:
        goal = model.goals.get(goal_id)
        if goal is None:
            raise DecompositionError(f"unknown goal: {goal_id}")
        raw = self._llm_call(self._prompt(goal, model))
        try:
            parsed = json.loads(_extract_json(raw))
        except json.JSONDecodeError as exc:
            raise DecompositionError(f"LLM output was not valid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            parsed = parsed.get("subgoals", []) if isinstance(parsed, dict) else []

        candidates: List[Dict[str, Any]] = []
        for n, item in enumerate(parsed, start=1):
            if not isinstance(item, dict) or not item.get("statement"):
                continue
            gid = _next_id(model, goal_id, n)
            criteria = [
                {"description": c if isinstance(c, str) else str(c)}
                for c in item.get("successCriteria", ["Subgoal is verifiably satisfied."])
                if c
            ]
            cand: Dict[str, Any] = {
                "id": gid,
                "statement": str(item["statement"]),
                "owner": goal.owner,
                "status": "proposed",
                "successCriteria": criteria,
            }
            if goal.deadline:
                cand["deadline"] = goal.deadline
            candidates.append(cand)
        return candidates


def _extract_json(text: str) -> str:
    """Pull the first JSON array/object out of possibly chatty LLM output."""
    match = re.search(r"[\[{]", text)
    if not match:
        return text
    start = match.start()
    opener = text[start]
    closer = "]" if opener == "[" else "}"
    depth = 0
    for i in range(start, len(text)):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def apply_decomposition(
    model: GoalModel,
    goal_id: str,
    candidates: List[Dict[str, Any]],
    refinement: str = DEFAULT_REFINEMENT,
    validate: bool = True,
) -> Dict[str, Any]:
    """Insert candidate subgoals under goal_id and return the new raw model.

    Applies R2 (ids resolve), R3 (no cycles — candidates are new ids), and a
    full schema+rules check on the resulting model. Raises
    :class:`DecompositionError` if the result would be invalid and
    ``validate`` is true; otherwise returns the raw dict anyway.
    """
    goal = model.goals.get(goal_id)
    if goal is None:
        raise DecompositionError(f"unknown goal: {goal_id}")
    raw = json.loads(json.dumps(model.raw))  # deep copy
    raw_goals = {g["id"]: g for g in raw["goals"]}
    parent = raw_goals[goal_id]

    for cand in candidates:
        if cand["id"] in raw_goals:
            raise DecompositionError(f"id collision: {cand['id']}")
        raw["goals"].append(json.loads(json.dumps(cand)))
        raw_goals[cand["id"]] = cand
    parent.setdefault("subgoals", []).extend(c["id"] for c in candidates)
    parent["refinement"] = refinement

    if validate:
        from .model import load_dict

        issues = find_issues(load_dict(raw))
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise DecompositionError(
                "decomposition would make the model invalid: "
                + "; ".join(str(i) for i in errors)
            )
    return raw
