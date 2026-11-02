import copy

import pytest

from goal_model.model import load_dict
from goal_model.planner import Planner

from test_rules import BASE


def model():
    return load_dict(copy.deepcopy(BASE))


def test_state_gaps_report_current_and_target():
    raw = copy.deepcopy(BASE)
    raw["states"][0]["isCurrent"] = True
    gaps = Planner().state_gaps(load_dict(raw))
    by_id = {g.goal_id: g for g in gaps}
    assert by_id["g1"].target == "s1"
    assert by_id["g1"].current == ["s1"]
    assert by_id["g1"].open_criteria == ["criterion one"]


def test_plan_orders_dependencies_first():
    raw = copy.deepcopy(BASE)
    raw["goals"][0]["dependsOn"] = ["g2"]
    plan = Planner().plan(load_dict(raw))
    ids = [s.goal_id for s in plan.steps]
    assert ids.index("g2") < ids.index("g1")
    assert plan.steps[0].ready


def test_blocked_goals_report_blockers():
    raw = copy.deepcopy(BASE)
    raw["goals"][0]["dependsOn"] = ["g2"]  # g2 not achieved
    plan = Planner().plan(load_dict(raw))
    by_id = {s.goal_id: s for s in plan.steps}
    assert not by_id["g1"].ready
    assert by_id["g1"].blocked_by == ["g2"]


def test_subgoal_blocked_when_parent_not_active():
    raw = copy.deepcopy(BASE)
    raw["goals"][0]["status"] = "proposed"  # parent of g2 not active
    plan = Planner().plan(load_dict(raw))
    by_id = {s.goal_id: s for s in plan.steps}
    assert not by_id["g2"].ready
    assert "g1" in by_id["g2"].blocked_by


def test_achieved_and_abandoned_goals_excluded():
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["status"] = "achieved"
    raw["goals"][1]["successCriteria"] = [{"description": "c"}]
    plan = Planner().plan(load_dict(raw))
    assert [s.goal_id for s in plan.steps] == ["g1"]


def test_progress_overall_and_by_toplevel():
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["status"] = "achieved"
    progress = Planner().progress(load_dict(raw))
    assert progress["overall"] == 0.5
    assert progress["byTopLevel"]["g1"] == 0.5


def test_plan_respects_priority_within_depth():
    raw = copy.deepcopy(BASE)
    raw["goals"].append(
        {
            "id": "g0",
            "statement": "Critical sibling.",
            "owner": "a1",
            "priority": "critical",
            "successCriteria": [{"description": "c0"}],
        }
    )
    plan = Planner().plan(load_dict(raw))
    assert plan.steps[0].goal_id == "g0"
