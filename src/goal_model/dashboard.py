"""Dashboard renderers: text (CLI) and HTML (loopback web dashboard)."""

from __future__ import annotations

import html
from typing import Any, Dict


def _pct(x):
    return "-" if x is None else f"{x * 100:.0f}%"


def _metric_criteria_txt(g: Dict[str, Any]) -> str:
    """Compact one-line rendering of a goal's metric-referenced criteria."""
    parts = []
    for mc in g.get("metricCriteria", []):
        t = mc.get("target") or {}
        tgt = ""
        if t:
            tgt = " ".join(
                f"target {t.get('operator')} {t.get('value')} {t.get('unit') or ''}".split()
            )
        latest = ""
        if mc.get("latestVerdict"):
            latest = f" | latest: {mc['latestVerdict']}"
            if mc.get("latestMeasurement") is not None:
                latest += f" (measured {mc['latestMeasurement']})"
        parts.append(f"{mc['metric']}@{mc.get('version')} {tgt}{latest}".rstrip())
    return "; ".join(parts) or "-"


def render_dashboard_text(m: Dict[str, Any]) -> str:
    lines = [
        f"GOAL operations dashboard - {m['model']['name']} (model {m['model']['id']} v{m['model']['version']})",
        f"Generated at {m['generatedAt']}",
        "",
        f"Totals: {m['totals']['goals']} goals "
        + ", ".join(f"{k}={v}" for k, v in sorted(m["totals"]["byStatus"].items()))
        + f" | overall progress {_pct(m['totals']['overallProgress'])}"
        + f" | {m['totals']['events']} events, {m['totals']['assessments']} assessments, "
        f"{m['totals']['agents']} agents",
        "",
        "Agents:",
    ]
    if not m["agents"]:
        lines.append("  (none registered)")
    for aid, a in m["agents"].items():
        lines.append(
            f"  {aid} [{a['status']}] {a['name']} ({a['type']}) - "
            f"goals {a['goals']} (active {a['activeGoals']}, achieved {a['achievedGoals']}), "
            f"activities {a['activities']}, adherence {_pct(a['adherenceScore'])}"
        )
    lines += ["", "Goals:"]
    for gid, g in m["goals"].items():
        state = "READY" if g["ready"] else f"BLOCKED by {', '.join(g['blockedBy'])}" if g["blockedBy"] else "-"
        risk = "-" if g["deadlineRiskDays"] is None else f"{g['deadlineRiskDays']}d to deadline"
        la = g["latestAssessment"]
        assess = (
            f"assessment {la['verdict']} ({la['score']:.0%} via {la['assessor']})"
            if la
            else "no assessment yet"
        )
        lines.append(
            f"  {gid} [{g['status']}] {g['statement']}"
            f"\n      owner={g['owner']} priority={g['priority'] or '-'} {state} {risk} | "
            f"activities={g['activities']} | {assess}"
        )
        if g.get("metricCriteria"):
            lines.append(f"      metric criteria: {_metric_criteria_txt(g)}")
    lines += ["", "Recent events:"]
    if not m["recentEvents"]:
        lines.append("  (none)")
    for e in m["recentEvents"][-10:]:
        lines.append(f"  {e['ts']} {e['type']} agent={e['agentId'] or '-'} goal={e['goalId'] or '-'}")
    return "\n".join(lines)


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="10">
<title>GOAL operations dashboard - {title}</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; margin: 2rem; color: #1a1a1a; }}
h1 {{ font-size: 1.3rem; }} h2 {{ font-size: 1.05rem; margin-top: 1.6rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: left; font-size: 0.85rem; vertical-align: top; }}
th {{ background: #f4f4f4; }}
.meta {{ color: #666; font-size: 0.8rem; }}
.achieved {{ color: #0a7d00; }} .partial {{ color: #b26a00; }} .not_achieved {{ color: #b00000; }}
</style>
</head>
<body>
<h1>GOAL operations dashboard &mdash; {title}</h1>
<p class="meta">Model {model_id} v{version} &middot; generated {generated} &middot; auto-refresh 10s &middot; loopback only</p>
<h2>Totals</h2>
<p>{totals}</p>
<h2>Agents</h2>
{agents_table}
<h2>Goals</h2>
{goals_table}
<h2>Recent events</h2>
{events_table}
</body>
</html>
"""


def _table(headers, rows):
    if not rows:
        return "<p class='meta'>(none)</p>"
    out = ["<table><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr>"]
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    out.append("</table>")
    return "".join(out)


def render_dashboard_html(m: Dict[str, Any]) -> str:
    e = html.escape
    totals = m["totals"]
    totals_txt = (
        f"{totals['goals']} goals ("
        + ", ".join(f"{e(k)}={v}" for k, v in sorted(totals["byStatus"].items()))
        + f") &middot; overall progress {_pct(totals['overallProgress'])} &middot; "
        f"{totals['events']} events &middot; {totals['assessments']} assessments &middot; "
        f"{totals['agents']} agents"
    )
    agent_rows = [
        [
            e(aid),
            f"{e(a['name'])} ({e(a['type'])})",
            e(a["status"]),
            str(a["goals"]),
            f"{a['activeGoals']} active / {a['achievedGoals']} achieved",
            str(a["activities"]),
            _pct(a["adherenceScore"]),
            e(a["lastActivityAt"] or "-"),
        ]
        for aid, a in m["agents"].items()
    ]
    goal_rows = []
    for gid, g in m["goals"].items():
        state = "READY" if g["ready"] else ("BLOCKED: " + e(", ".join(g["blockedBy"])) if g["blockedBy"] else "-")
        risk = "-" if g["deadlineRiskDays"] is None else f"{g['deadlineRiskDays']}d"
        la = g["latestAssessment"]
        assess = (
            f"<span class='{e(la['verdict'])}'>{e(la['verdict'])}</span> {la['score']:.0%} ({e(la['assessor'])})"
            if la
            else "none"
        )
        goal_rows.append(
            [
                e(gid),
                e(g["statement"]),
                e(g["status"]),
                e(g["owner"]),
                state,
                risk,
                str(g["activities"]),
                e(_metric_criteria_txt(g)),
                assess,
            ]
        )
    event_rows = [
        [e(ev["ts"]), e(ev["type"]), e(ev["agentId"] or "-"), e(ev["goalId"] or "-")]
        for ev in m["recentEvents"][-15:]
    ]
    return _PAGE.format(
        title=e(m["model"]["name"]),
        model_id=e(m["model"]["id"]),
        version=e(m["model"]["version"]),
        generated=e(m["generatedAt"]),
        totals=totals_txt,
        agents_table=_table(
            ["Agent", "Name (type)", "Status", "Goals", "Active/Achieved", "Activities", "Adherence", "Last activity"],
            agent_rows,
        ),
        goals_table=_table(
            ["Goal", "Statement", "Status", "Owner", "Readiness", "Deadline risk", "Activities", "Metric criteria", "Latest assessment"],
            goal_rows,
        ),
        events_table=_table(["Time", "Event", "Agent", "Goal"], event_rows),
    )
