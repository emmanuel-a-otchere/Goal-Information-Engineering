import copy
from datetime import date, timedelta

from test_rules import BASE

from goal_model.interface import accept_goal, record_action, transition
from goal_model.assess import assess_goal
from opsbase import make_ctx

AGENT = {"id": "a1", "name": "Agent One", "type": "human"}


def test_metrics_shape_and_totals(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    m = ctx.metrics()
    assert m["model"]["id"] == "m"
    assert m["totals"]["goals"] == 2
    assert m["totals"]["byStatus"] == {"active": 1, "proposed": 1}
    assert m["totals"]["agents"] == 1
    assert m["agents"]["a1"]["goals"] == 2
    assert m["agents"]["a1"]["activeGoals"] == 1
    assert m["goals"]["g2"]["ready"] is True  # no unmet dependencies
    assert m["goals"]["g2"]["latestAssessment"] is None
    assert [e["type"] for e in m["recentEvents"]] == ["agent.registered"]


def test_metrics_reflect_operations(tmp_path):
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["deadline"] = (date.today() + timedelta(days=5)).isoformat()
    ctx = make_ctx(tmp_path, raw=raw, agents=[AGENT])
    accept_goal(ctx, "a1", "g2")
    record_action(ctx, "a1", "g2", "worked out")
    a = assess_goal(ctx, "g2", evidence={"criterion two": "log"})

    m = ctx.metrics()
    # registered + accepted + action + assessed
    assert m["agents"]["a1"]["activities"] == 4
    assert m["agents"]["a1"]["assessments"] == 1
    assert m["agents"]["a1"]["adherenceScore"] == 1.0
    g2 = m["goals"]["g2"]
    assert g2["activities"] == 3  # accepted + action + assessed
    assert g2["deadlineRiskDays"] == 5
    assert g2["latestAssessment"]["verdict"] == "achieved"
    assert g2["latestAssessment"]["score"] == a.score
    assert m["totals"]["events"] == 4
    assert m["totals"]["assessments"] == 1
    assert m["recentEvents"][-1]["type"] == "goal.assessed"


def test_metrics_blocked_goal_and_overdue(tmp_path):
    raw = copy.deepcopy(BASE)
    raw["goals"][0]["dependsOn"] = ["g2"]
    raw["goals"][1]["deadline"] = "2000-01-01"
    ctx = make_ctx(tmp_path, raw=raw, agents=[AGENT])
    m = ctx.metrics()
    assert m["goals"]["g1"]["ready"] is False
    assert m["goals"]["g1"]["blockedBy"] == ["g2"]
    assert m["goals"]["g2"]["deadlineRiskDays"] < 0


def test_metrics_after_achieved_goal_has_no_deadline_risk(tmp_path):
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["deadline"] = "2000-01-01"
    ctx = make_ctx(tmp_path, raw=raw, agents=[AGENT])
    accept_goal(ctx, "a1", "g2")
    transition(ctx, "a1", "g2", "achieved")
    m = ctx.metrics()
    assert m["goals"]["g2"]["deadlineRiskDays"] is None
    assert m["totals"]["byStatus"]["achieved"] == 1


# -- metric criteria in the dashboard read-model ---------------------------

METRIC_CRITERION = {
    "description": "Monthly retention >= 97.5%",
    "verification": "automated",
    "metric": {
        "catalog": "dea-catalog-metrics",
        "id": "dea:metric-customer-retention-rate",
        "version": "1.2.0",
    },
    "target": {"operator": ">=", "value": 97.5, "unit": "percent"},
}


def metric_model_ctx(tmp_path):
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["successCriteria"] = [copy.deepcopy(METRIC_CRITERION)]
    return make_ctx(tmp_path, raw=raw, agents=[AGENT])


def test_metrics_expose_metric_criteria_with_latest_measurement(tmp_path):
    ctx = metric_model_ctx(tmp_path)
    m = ctx.metrics()
    mc = m["goals"]["g2"]["metricCriteria"]
    assert len(mc) == 1
    assert mc[0]["metric"] == "dea:metric-customer-retention-rate"
    assert mc[0]["catalog"] == "dea-catalog-metrics"
    assert mc[0]["version"] == "1.2.0"
    assert mc[0]["target"] == {"operator": ">=", "value": 97.5, "unit": "percent"}
    assert "latestVerdict" not in mc[0]
    assert m["goals"]["g1"]["metricCriteria"] == []

    assess_goal(ctx, "g2", evidence={"0": "97.6"})
    m = ctx.metrics()
    mc = m["goals"]["g2"]["metricCriteria"][0]
    assert mc["latestVerdict"] == "pass"
    assert mc["latestMeasurement"] == 97.6


def test_dashboard_renderers_show_metric_criteria(tmp_path):
    from goal_model.dashboard import render_dashboard_html, render_dashboard_text

    ctx = metric_model_ctx(tmp_path)
    assess_goal(ctx, "g2", evidence={"0": "97.6"})
    m = ctx.metrics()
    txt = render_dashboard_text(m)
    assert "dea:metric-customer-retention-rate@1.2.0" in txt
    assert "target >= 97.5 percent" in txt
    assert "measured 97.6" in txt
    page = render_dashboard_html(m)
    assert "dea:metric-customer-retention-rate@1.2.0" in page
    assert "Metric criteria" in page
