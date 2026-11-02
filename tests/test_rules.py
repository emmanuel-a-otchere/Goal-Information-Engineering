import copy
from pathlib import Path

import pytest

from goal_model import check_model, find_issues, load
from goal_model.model import load_dict
from goal_model.rules import (
    check_r1_unique_ids,
    check_r2_references,
    check_r3_acyclic,
    check_r4_leaf_actionability,
    check_r5_owned,
    check_r6_deadlines,
    check_r7_orphans,
    check_r8_conflicts,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

BASE = {
    "id": "m",
    "name": "Test Model",
    "version": "0.1.0",
    "schemaVersion": "0.1.0",
    "agents": [{"id": "a1", "name": "Agent One", "type": "human"}],
    "states": [{"id": "s1", "description": "target", "isCurrent": False}],
    "goals": [
        {
            "id": "g1",
            "statement": "Top goal.",
            "owner": "a1",
            "targetState": "s1",
            "successCriteria": [{"description": "criterion one"}],
            "status": "active",
            "priority": "high",
            "subgoals": ["g2"],
            "refinement": "and",
        },
        {
            "id": "g2",
            "statement": "Sub goal.",
            "owner": "a1",
            "successCriteria": [{"description": "criterion two"}],
            "status": "proposed",
        },
    ],
}


def base():
    return load_dict(copy.deepcopy(BASE))


def rule_codes(model, fn):
    return {i.rule for i in fn(model)}


# -- shipped examples ----------------------------------------------------


@pytest.mark.parametrize("example", ["business-okr.json", "fitness-goal.json"])
def test_examples_valid(example):
    model = load(EXAMPLES / example)
    assert check_model(model), [str(i) for i in find_issues(model)]


@pytest.mark.parametrize("example", ["business-okr.json", "fitness-goal.json"])
def test_examples_have_expected_warnings_or_none(example):
    model = load(EXAMPLES / example)
    assert all(i.severity != "error" for i in find_issues(model))


# -- R1 -------------------------------------------------------------------


def test_r1_detects_duplicate_goal_ids():
    raw = copy.deepcopy(BASE)
    dup = copy.deepcopy(raw["goals"][1])  # same id "g2" twice
    raw["goals"].append(dup)
    model = load_dict(raw)
    assert "R1" in rule_codes(model, check_r1_unique_ids)


# -- R2 -------------------------------------------------------------------


def test_r2_detects_bad_owner_and_refs():
    raw = copy.deepcopy(BASE)
    raw["goals"][0]["owner"] = "ghost"
    raw["goals"][0]["subgoals"] = ["missing"]
    raw["goals"][0]["targetState"] = "nope"
    model = load_dict(raw)
    r2 = check_r2_references(model)
    assert {i.subject for i in r2} == {"g1"}
    assert len(r2) == 3


def test_r2_detects_bad_obstacle_refs():
    raw = copy.deepcopy(BASE)
    raw["obstacles"] = [
        {"id": "o1", "description": "bad obstacle", "threatens": "missing", "mitigation": "also-missing"}
    ]
    model = load_dict(raw)
    assert len(check_r2_references(model)) == 2


# -- R3 -------------------------------------------------------------------


def test_r3_detects_cycle():
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["subgoals"] = ["g1"]  # g1 -> g2 -> g1
    model = load_dict(raw)
    assert check_r3_acyclic(model)


def test_r3_no_cycle_in_healthy_model():
    assert check_r3_acyclic(base()) == []


# -- R4 -------------------------------------------------------------------


def test_r4_flags_criterialess_leaf():
    raw = copy.deepcopy(BASE)
    raw["goals"][1].pop("successCriteria")
    model = load_dict(raw)
    assert check_r4_leaf_actionability(model)


def test_r4_ok_when_leaf_has_criteria():
    assert check_r4_leaf_actionability(base()) == []


# -- R5 -------------------------------------------------------------------


def test_r5_detects_missing_owner():
    raw = copy.deepcopy(BASE)
    raw["goals"][1].pop("owner")
    raw["agents"] = []  # also fails schema; R5 should still fire
    model = load_dict(raw)
    assert check_r5_owned(model)


# -- R6 -------------------------------------------------------------------


def test_r6_detects_impossible_deadline_ordering():
    raw = copy.deepcopy(BASE)
    raw["goals"][0]["dependsOn"] = ["g2"]
    raw["goals"][0]["deadline"] = "2026-01-01"
    raw["goals"][1]["deadline"] = "2026-06-01"  # dependency due AFTER dependent
    model = load_dict(raw)
    assert check_r6_deadlines(model)


def test_r6_ok_with_sane_deadlines():
    raw = copy.deepcopy(BASE)
    raw["goals"][0]["dependsOn"] = ["g2"]
    raw["goals"][0]["deadline"] = "2026-06-01"
    raw["goals"][1]["deadline"] = "2026-01-01"
    assert check_r6_deadlines(load_dict(raw)) == []


# -- R7 -------------------------------------------------------------------


def test_r7_detects_orphan_goal():
    raw = copy.deepcopy(BASE)
    raw["goals"].append(
        {
            "id": "g3",
            "statement": "Orphan.",
            "owner": "a1",
            "successCriteria": [{"description": "c3"}],
        }
    )
    model = load_dict(raw)
    issues = check_r7_orphans(model)
    assert [i.subject for i in issues] == ["g3"]
    assert issues[0].severity == "warning"


# -- R8 -------------------------------------------------------------------


def test_r8_detects_resource_conflict():
    raw = copy.deepcopy(BASE)
    raw["constraints"] = [{"id": "c1", "description": "budget cap", "kind": "budget"}]
    for g in raw["goals"]:
        g["deadline"] = "2026-01-31"
        g["constraints"] = ["c1"]
    raw["goals"][0]["owner"] = "a1"
    raw["goals"][1]["owner"] = "a1"
    model = load_dict(raw)
    issues = check_r8_conflicts(model)
    assert issues and issues[0].severity == "warning"


def test_r8_no_conflict_without_shared_deadline():
    raw = copy.deepcopy(BASE)
    raw["constraints"] = [{"id": "c1", "description": "budget cap", "kind": "budget"}]
    raw["goals"][0].update({"deadline": "2026-01-31", "constraints": ["c1"]})
    raw["goals"][1].update({"deadline": "2026-03-31", "constraints": ["c1"]})
    assert check_r8_conflicts(load_dict(raw)) == []


# -- find_issues / check_model --------------------------------------------


def test_find_issues_aggregates_and_check_model_blocks_errors():
    raw = copy.deepcopy(BASE)
    raw["goals"][0]["owner"] = "ghost"
    model = load_dict(raw)
    assert not check_model(model)
    codes = {i.rule for i in find_issues(model)}
    assert "R2" in codes
