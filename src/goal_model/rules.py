"""Design rules R1-R9 from docs/GOAL-METAMODEL.md.

Each rule yields Issue objects. Errors block a model from being considered
well-formed; warnings are advisory.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import List

from .model import GoalModel, load_metric_registry, load_schema

try:  # pragma: no cover - exercised via CLI/tests, import guard for packaging
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None


@dataclass
class Issue:
    rule: str
    severity: str  # "error" | "warning"
    message: str
    subject: str = ""  # entity id the issue is about

    def __str__(self) -> str:  # pragma: no cover
        prefix = f"[{self.rule}/{self.severity}]"
        subject = f" {self.subject}:" if self.subject else ""
        return f"{prefix}{subject} {self.message}"


# -- JSON Schema conformance -------------------------------------------


def validate_schema(model: GoalModel) -> List[Issue]:
    """Validate the raw instance against schema/goal.schema.json."""
    if Draft202012Validator is None:
        return [Issue("schema", "error", "jsonschema library not installed")]
    validator = Draft202012Validator(load_schema())
    return [
        Issue("schema", "error", e.message, subject="/".join(str(p) for p in e.absolute_path))
        for e in sorted(validator.iter_errors(model.raw), key=lambda e: list(e.absolute_path))
    ]


# -- R1: unique ids ------------------------------------------------------


def check_r1_unique_ids(model: GoalModel) -> List[Issue]:
    issues: List[Issue] = []

    # Checked on raw arrays: parsed dicts silently collapse duplicate keys.
    def check(kind: str, items: list) -> None:
        seen = set()
        for item in items:
            i = item.get("id")
            if i in seen:
                issues.append(Issue("R1", "error", f"Duplicate {kind} id: {i}", i))
            seen.add(i)

    check("agent", model.raw.get("agents", []))
    check("state", model.raw.get("states", []))
    check("goal", model.raw.get("goals", []))
    check("obstacle", model.raw.get("obstacles", []))
    check("constraint", model.raw.get("constraints", []))
    return issues


# -- R2: referential integrity -------------------------------------------


def check_r2_references(model: GoalModel) -> List[Issue]:
    issues: List[Issue] = []
    for g in model.goals.values():
        if g.owner not in model.agents:
            issues.append(Issue("R2", "error", f"owner '{g.owner}' not an agent", g.id))
        for c in g.contributors:
            if c not in model.agents:
                issues.append(Issue("R2", "error", f"contributor '{c}' not an agent", g.id))
        if g.target_state and g.target_state not in model.states:
            issues.append(
                Issue("R2", "error", f"targetState '{g.target_state}' not a state", g.id)
            )
        for s in g.subgoals + g.depends_on:
            if s not in model.goals:
                issues.append(Issue("R2", "error", f"goal reference '{s}' not a goal", g.id))
        for c in g.constraints:
            if c not in model.constraints:
                issues.append(Issue("R2", "error", f"constraint reference '{c}' unknown", g.id))
    for o in model.obstacles.values():
        for t in o.threatens:
            if t not in model.goals:
                issues.append(Issue("R2", "error", f"threatened goal '{t}' not a goal", o.id))
        if o.mitigation and o.mitigation not in model.goals:
            issues.append(Issue("R2", "error", f"mitigation goal '{o.mitigation}' not a goal", o.id))
    return issues


# -- R3: acyclic refinement ----------------------------------------------


def check_r3_acyclic(model: GoalModel) -> List[Issue]:
    issues: List[Issue] = []
    WHITE, GREY, BLACK = 0, 1, 2
    color = {gid: WHITE for gid in model.goals}

    def visit(gid: str, path: List[str]) -> None:
        color[gid] = GREY
        for s in model.goals[gid].subgoals:
            if s not in model.goals:
                continue  # already an R2 error
            if color[s] == GREY:
                issues.append(Issue("R3", "error", "Cyclic refinement via " + " -> ".join(path + [s]), s))
            elif color[s] == WHITE:
                visit(s, path + [s])
        color[gid] = BLACK

    for gid in model.goals:
        if color[gid] == WHITE:
            visit(gid, [gid])
    return issues


# -- R4: leaf actionability ----------------------------------------------


def check_r4_leaf_actionability(model: GoalModel, max_depth: int = 100) -> List[Issue]:
    """AND-refined goals must bottom out in checkable leaves within max_depth."""
    issues: List[Issue] = []

    def depth(gid: str, seen: set) -> int:
        goal = model.goals[gid]
        subs = [s for s in goal.subgoals if s in model.goals]
        if not subs:
            return 1 if goal.success_criteria else 0
        if gid in seen or len(seen) > max_depth:
            return 0  # cycle: already an R3 error
        sub_depths = [depth(s, seen | {gid}) for s in subs]
        return 1 + max(sub_depths)

    for g in model.goals.values():
        subs = [s for s in g.subgoals if s in model.goals]
        if not subs and not g.success_criteria:
            issues.append(
                Issue("R4", "error", "Leaf goal has no success criteria; refine it or add criteria", g.id)
            )
    return issues


# -- R5: owned goals ------------------------------------------------------


def check_r5_owned(model: GoalModel) -> List[Issue]:
    return [
        Issue("R5", "error", f"owner '{g.owner}' not defined in agents", g.id)
        for g in model.goals.values()
        if not g.owner or g.owner not in model.agents
    ]


# -- R6: deadline sanity ---------------------------------------------------


def check_r6_deadlines(model: GoalModel) -> List[Issue]:
    issues: List[Issue] = []

    def deadline(gid: str):
        d = model.goals[gid].deadline
        return _dt.date.fromisoformat(d) if d else None

    for g in model.goals.values():
        own = deadline(g.id)
        if own is None:
            continue
        for dep in g.depends_on:
            if dep in model.goals:
                dep_d = deadline(dep)
                if dep_d is not None and dep_d > own:
                    issues.append(
                        Issue(
                            "R6",
                            "error",
                            f"deadline {own} precedes dependency '{dep}' (due {dep_d})",
                            g.id,
                        )
                    )
    return issues


# -- R7: orphan detection (warning) ----------------------------------------


def check_r7_orphans(model: GoalModel) -> List[Issue]:
    """Flag goals with no structural edges to any other goal.

    A goal is an orphan when no refinement, dependency, or obstruction edge
    connects it to another goal or obstacle — it floats free of the model's
    structure.
    """
    issues: List[Issue] = []
    if len(model.goals) <= 1:
        return issues

    def neighbors(gid: str) -> set:
        goal = model.goals[gid]
        linked = set(goal.subgoals) | set(goal.depends_on)
        for other in model.goals.values():
            if gid in other.subgoals or gid in other.depends_on:
                linked.add(other.id)
        for obstacle in model.obstacles.values():
            if gid in obstacle.threatens or obstacle.mitigation == gid:
                linked.add(obstacle.id)
        return linked

    goal_ids = set(model.goals)
    for gid in model.goals:
        if not (neighbors(gid) & (goal_ids | set(model.obstacles))):
            issues.append(Issue("R7", "warning", "Goal is not connected to any other goal", gid))
    return issues


# -- R8: resource conflict detection (warning) ------------------------------


def check_r8_conflicts(model: GoalModel) -> List[Issue]:
    issues: List[Issue] = []
    goals = list(model.goals.values())
    for i, a in enumerate(goals):
        for b in goals[i + 1 :]:
            if a.owner != b.owner or not a.deadline or a.deadline != b.deadline:
                continue
            shared = set(a.constraints) & set(b.constraints)
            if shared:
                issues.append(
                    Issue(
                        "R8",
                        "warning",
                        f"Shares owner, deadline {a.deadline}, and constraint(s) "
                        f"{sorted(shared)} with '{b.id}'",
                        a.id,
                    )
                )
    return issues


# -- R9: metric reference resolution and coherence --------------------------

# Operators that express a target compatible with each catalog directionality.
_DIRECTIONALITY_OPERATORS = {
    "higher_is_better": {"==", ">", ">="},
    "lower_is_better": {"==", "<", "<="},
    "target_band": {"band"},
    "categorical": {"=="},
}


def check_r9_metric_references(model: GoalModel) -> List[Issue]:
    """Criterion metric references must resolve and stay coherent with the record.

    Resolution is against the local pointer registry (schema/metric-registry.json).
    Unknown catalogs or record ids only warn, because the full catalog is remote
    and the local registry is not exhaustive. Once a record resolves, a target
    whose operator contradicts the record's directionality or whose unit differs
    from the record's unit is an error: automated verification would be wrong.
    """
    issues: List[Issue] = []
    registry = load_metric_registry()
    records = {(r.get("catalog"), r.get("id")): r for r in registry.get("records", [])}
    known_catalogs = {r.get("catalog") for r in registry.get("records", [])} | {
        registry.get("source", {}).get("catalog")
    }
    known_catalogs.discard(None)

    for g in model.goals.values():
        for idx, c in enumerate(g.success_criteria):
            ref = c.metric
            if not ref:
                if c.target:
                    issues.append(
                        Issue("R9", "warning", f"criterion {idx} sets a target without a metric reference", g.id)
                    )
                continue
            catalog, mid = ref.get("catalog"), ref.get("id")
            where = f"criterion {idx} of goal '{g.id}'"
            rec = records.get((catalog, mid))
            if rec is None:
                if catalog in known_catalogs:
                    issues.append(
                        Issue(
                            "R9",
                            "warning",
                            f"{where}: metric '{mid}' not in the local pointer registry for catalog "
                            f"'{catalog}'; verify against the catalog's registry",
                            g.id,
                        )
                    )
                else:
                    issues.append(
                        Issue(
                            "R9",
                            "warning",
                            f"{where}: unknown metric catalog '{catalog}'; cannot verify the reference offline",
                            g.id,
                        )
                    )
                continue
            if ref.get("version") and rec.get("version") and ref["version"] != rec["version"]:
                issues.append(
                    Issue(
                        "R9",
                        "warning",
                        f"{where}: pinned version {ref['version']} differs from the locally known "
                        f"{rec['version']} for '{mid}'",
                        g.id,
                    )
                )
            target = c.target
            if target:
                op = target.get("operator")
                allowed = _DIRECTIONALITY_OPERATORS.get(rec.get("directionality"))
                if allowed is not None and op not in allowed:
                    issues.append(
                        Issue(
                            "R9",
                            "error",
                            f"{where}: operator '{op}' contradicts directionality "
                            f"'{rec.get('directionality')}' of '{mid}' (allowed: {sorted(allowed)})",
                            g.id,
                        )
                    )
                rec_unit, t_unit = rec.get("unit"), target.get("unit")
                if rec_unit and t_unit and str(t_unit).lower() != str(rec_unit).lower():
                    issues.append(
                        Issue(
                            "R9",
                            "error",
                            f"{where}: target unit '{t_unit}' does not match metric unit "
                            f"'{rec_unit}' of '{mid}'",
                            g.id,
                        )
                    )
            if c.verification == "automated" and not target:
                issues.append(
                    Issue(
                        "R9",
                        "warning",
                        f"{where}: automated criterion references metric '{mid}' but sets no "
                        "target; add one for machine-checkable satisfaction",
                        g.id,
                    )
                )
    return issues


CHECKS = [
    ("schema", validate_schema),
    ("R1", check_r1_unique_ids),
    ("R2", check_r2_references),
    ("R3", check_r3_acyclic),
    ("R4", check_r4_leaf_actionability),
    ("R5", check_r5_owned),
    ("R6", check_r6_deadlines),
    ("R7", check_r7_orphans),
    ("R8", check_r8_conflicts),
    ("R9", check_r9_metric_references),
]


def find_issues(model: GoalModel) -> List[Issue]:
    """Run all checks and return every issue found."""
    issues: List[Issue] = []
    for _, check in CHECKS:
        issues.extend(check(model))
    return issues


def check_model(model: GoalModel) -> bool:
    """True when the model has no error-severity issues."""
    return not any(i.severity == "error" for i in find_issues(model))
