import copy

import pytest
from test_rules import BASE

from goal_model.assess import (
    Assessment,
    AssessorRegistry,
    ChecklistAssessor,
    StandardAssessor,
    assess_goal,
)
from goal_model.interface import accept_goal, record_action
from goal_model.telemetry import EVENT_CONSTRAINT_VIOLATED, EVENT_GOAL_ASSESSED
from opsbase import make_ctx

AGENT = {"id": "a1", "name": "Agent One", "type": "human"}


def test_standard_assessor_no_evidence_is_not_achieved(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    a = assess_goal(ctx, "g1")
    assert a.assessor == "standard"
    assert a.verdict == "not_achieved" and a.score == 0.0
    assert all(c.verdict == "unverified" for c in a.criteria)
    assert a.adherence["constraintsRespected"] is True


def test_standard_assessor_full_evidence_achieved(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    a = assess_goal(ctx, "g1", evidence={"criterion one": "release v0.1.0 published"})
    assert a.verdict == "achieved" and a.score == 1.0
    assert a.criteria[0].verdict == "pass"


def test_evidence_by_index_and_explicit_fail(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    a = assess_goal(ctx, "g1", evidence={0: "ok", "criterion one": {"pass": False}})
    # description key wins over index
    assert a.criteria[0].verdict == "fail"
    b = assess_goal(ctx, "g2", evidence={"0": "done"})
    assert b.criteria[0].verdict == "pass"


def test_partial_verdict_and_persistence_and_event(tmp_path):
    raw = copy.deepcopy(BASE)
    raw["goals"][0]["successCriteria"].append({"description": "criterion two"})
    ctx = make_ctx(tmp_path, raw=raw, agents=[AGENT])
    a = assess_goal(ctx, "g1", evidence={"criterion one": "done"})
    assert a.verdict == "partial" and a.score == 0.5
    stored = ctx.store.load_assessments()
    assert len(stored) == 1 and stored[0]["goalId"] == "g1" and stored[0]["verdict"] == "partial"
    ev = ctx.events.filter(type=EVENT_GOAL_ASSESSED)
    assert len(ev) == 1 and ev[0].payload["assessor"] == "standard"
    assert Assessment.from_dict(stored[0]).to_dict() == stored[0]


def test_adherence_deadline_and_constraint_violations(tmp_path):
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["deadline"] = "2000-01-01"  # long past, goal not achieved
    ctx = make_ctx(tmp_path, raw=raw, agents=[AGENT])
    ctx.events.append(EVENT_CONSTRAINT_VIOLATED, agent_id="a1", goal_id="g2", constraint="c1")
    a = assess_goal(ctx, "g2")
    assert a.adherence["deadlineOk"] is False
    assert a.adherence["constraintsRespected"] is False
    assert a.adherence["constraintViolations"] == 1
    assert a.adherence["score"] == 0.0


def test_performance_counts_activities(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    accept_goal(ctx, "a1", "g2")
    record_action(ctx, "a1", "g2", "step 1")
    record_action(ctx, "a1", "g2", "step 2")
    a = assess_goal(ctx, "g2")
    assert a.performance["actions"] == 2
    assert a.performance["activities"] == 3  # accepted + 2 actions + assessed? no: assess logs after
    assert a.performance["acceptedAt"] is not None


def test_registry_typed_dispatch_and_fallback(tmp_path):
    registry = AssessorRegistry.default()
    assert "checklist" in registry.types()
    assert registry.for_goal_type("okr").name == "standard"
    assert registry.for_goal_type("checklist").name == "checklist"

    class FitnessAssessor(StandardAssessor):
        name = "fitness"

    registry.register("fitness", FitnessAssessor())
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["type"] = "fitness"
    ctx = make_ctx(tmp_path, raw=raw, agents=[AGENT])
    ctx.assessors = registry
    a = assess_goal(ctx, "g2", evidence={"criterion two": "log export"})
    assert a.assessor == "fitness" and a.goal_type == "fitness"
    # explicit goal_type override beats the declared one
    b = assess_goal(ctx, "g2", goal_type="checklist", evidence={"criterion two": "log"})
    assert b.assessor == "checklist"


def test_checklist_assessor_flags_unmitigated_obstacles(tmp_path):
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["type"] = "checklist"
    raw["obstacles"] = [
        {"id": "o1", "description": "knee pain", "threatens": "g2"},
    ]
    ctx = make_ctx(tmp_path, raw=raw, agents=[AGENT])
    a = assess_goal(ctx, "g2", evidence={"criterion two": "done"})
    assert a.assessor == "checklist"
    assert a.verdict == "partial"  # downgraded from achieved by open obstacle
    assert any("o1" in n for n in a.notes)

    raw["obstacles"][0]["mitigation"] = "g1"
    ctx = make_ctx(tmp_path / "second", raw=raw, agents=[AGENT])
    a = assess_goal(ctx, "g2", evidence={"criterion two": "done"})
    assert a.verdict == "achieved"
    assert isinstance(ChecklistAssessor(), ChecklistAssessor)


def test_assess_unknown_goal_raises(tmp_path):
    from goal_model.assess import AssessmentError

    ctx = make_ctx(tmp_path, agents=[AGENT])
    with pytest.raises(AssessmentError):
        assess_goal(ctx, "nope")


# -- metric-referenced criteria (dea-catalog-metrics pointer registry) -------

CRR_CRITERION = {
    "description": "Monthly retention >= 97.5%",
    "verification": "automated",
    "metric": {
        "catalog": "dea-catalog-metrics",
        "id": "dea:metric-customer-retention-rate",
        "version": "1.2.0",
    },
    "target": {"operator": ">=", "value": 97.5, "unit": "percent"},
}


def metric_ctx(tmp_path, criterion=CRR_CRITERION):
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["successCriteria"] = [criterion]
    return make_ctx(tmp_path, raw=raw, agents=[AGENT])


def test_metric_criterion_measurement_pass(tmp_path):
    ctx = metric_ctx(tmp_path)
    a = assess_goal(ctx, "g2", evidence={"0": "97.6"})
    c = a.criteria[0]
    assert c.verdict == "pass"
    assert c.metric == "dea:metric-customer-retention-rate"
    assert c.measurement == 97.6
    assert "97.6" in c.note and "higher_is_better" in c.note
    assert a.verdict == "achieved" and a.score == 1.0


def test_metric_criterion_measurement_fail(tmp_path):
    ctx = metric_ctx(tmp_path)
    a = assess_goal(ctx, "g2", evidence={0: 90.0})
    assert a.criteria[0].verdict == "fail"
    assert a.criteria[0].measurement == 90.0
    assert a.verdict == "not_achieved" and a.score == 0.0


def test_metric_criterion_dict_value_and_unit_mismatch_note(tmp_path):
    ctx = metric_ctx(tmp_path)
    a = assess_goal(ctx, "g2", evidence={"0": {"value": 98.0, "unit": "ratio"}})
    c = a.criteria[0]
    assert c.verdict == "pass" and c.measurement == 98.0
    assert "mismatches metric unit" in c.note


def test_metric_criterion_band_target(tmp_path):
    crit = copy.deepcopy(CRR_CRITERION)
    crit["target"] = {"operator": "band", "value": [97.0, 99.0], "unit": "percent"}
    ctx = metric_ctx(tmp_path, crit)
    assert assess_goal(ctx, "g2", evidence={"0": 98.2}).criteria[0].verdict == "pass"
    assert assess_goal(ctx, "g2", evidence={"0": 96.0}).criteria[0].verdict == "fail"


def test_metric_criterion_without_target_falls_back_to_evidence(tmp_path):
    crit = copy.deepcopy(CRR_CRITERION)
    crit.pop("target")
    ctx = metric_ctx(tmp_path, crit)
    a = assess_goal(ctx, "g2", evidence={"0": True})
    assert a.criteria[0].verdict == "pass"
    b = assess_goal(ctx, "g2")
    assert b.criteria[0].verdict == "unverified" and "no target" in b.criteria[0].note


def test_metric_assessment_persists_round_trip(tmp_path):
    ctx = metric_ctx(tmp_path)
    assess_goal(ctx, "g2", evidence={"0": "97.6"})
    stored = ctx.store.load_assessments()
    assert stored[0]["criteria"][0]["metric"] == "dea:metric-customer-retention-rate"
    assert stored[0]["criteria"][0]["measurement"] == 97.6
    assert Assessment.from_dict(stored[0]).to_dict() == stored[0]


def test_evaluate_target_operators():
    from goal_model.model import evaluate_target

    assert evaluate_target({"operator": ">=", "value": 97.5}, 97.5)
    assert not evaluate_target({"operator": ">", "value": 97.5}, 97.5)
    assert evaluate_target({"operator": "<=", "value": 2.5}, 2.5)
    assert not evaluate_target({"operator": "<", "value": 2.5}, 2.5)
    assert evaluate_target({"operator": "==", "value": 100}, 100)
    assert evaluate_target({"operator": "band", "value": [1, 2]}, 1.5)
    assert not evaluate_target({"operator": "band", "value": [1, 2]}, 3)
    assert not evaluate_target({"operator": "band", "value": "x"}, 1)


def test_find_metric_record_resolves_pointer_registry():
    from goal_model.model import find_metric_record

    rec = find_metric_record(
        {"catalog": "dea-catalog-metrics", "id": "dea:metric-mean-time-to-recovery"}
    )
    assert rec and rec["directionality"] == "lower_is_better" and rec["unit"] == "minute"
    assert find_metric_record({"catalog": "dea-catalog-metrics", "id": "dea:metric-nope"}) is None
    assert find_metric_record({"catalog": "other", "id": "x"}) is None
    assert find_metric_record(None) is None
