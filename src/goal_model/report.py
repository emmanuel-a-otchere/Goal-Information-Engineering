"""Human-readable reports for GOAL models."""

from __future__ import annotations

from typing import Dict, List

from .model import GoalModel
from .rules import Issue, find_issues


def goal_tree(model: GoalModel) -> str:
    """Render the refinement forest as a text tree."""
    lines: List[str] = [f"{model.name} (model {model.id}, version {model.version})"]
    tops = model.top_level_goals()
    if not tops:
        lines.append("  (no goals)")
        return "\n".join(lines)

    def render(gid: str, prefix: str) -> None:
        goal = model.goals[gid]
        marker = {"and": "AND", "or": "OR"}.get(goal.refinement or "", "")
        status = f"[{goal.status}]"
        crit = f" ({len(goal.success_criteria)} criteria)" if goal.success_criteria else ""
        owner = f" @{goal.owner}" if goal.owner else ""
        lines.append(f"{prefix}- {gid}: {goal.statement} {status}{owner}{crit} {marker}".rstrip())
        for s in goal.subgoals:
            if s in model.goals:
                render(s, prefix + "  ")

    for top in tops:
        render(top, "")
    return "\n".join(lines)


def status_summary(model: GoalModel) -> Dict[str, int]:
    summary: Dict[str, int] = {}
    for g in model.goals.values():
        summary[g.status] = summary.get(g.status, 0) + 1
    return summary


def issues_report(issues: List[Issue]) -> str:
    if not issues:
        return "No issues found."
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    lines = []
    if errors:
        lines.append(f"Errors ({len(errors)}):")
        lines += [f"  {i}" for i in errors]
    if warnings:
        lines.append(f"Warnings ({len(warnings)}):")
        lines += [f"  {i}" for i in warnings]
    return "\n".join(lines)


def full_report(model: GoalModel) -> str:
    issues = find_issues(model)
    summary = status_summary(model)
    ok = not any(i.severity == "error" for i in issues)
    parts = [
        goal_tree(model),
        "",
        "Status summary: " + ", ".join(f"{k}: {v}" for k, v in sorted(summary.items()))
        or "Status summary: (none)",
        "",
        f"Well-formed: {'YES' if ok else 'NO'}",
        "",
        issues_report(issues),
    ]
    return "\n".join(parts)
