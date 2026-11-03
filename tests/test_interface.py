import copy

import pytest
from test_rules import BASE

from goal_model.interface import GoalRejection, accept_goal, record_action, transition
from goal_model.registry import GoalInterface
from goal_model.telemetry import (
    EVENT_ACTION_RECORDED,
    EVENT_GOAL_ACCEPTED,
    EVENT_GOAL_STATUS_CHANGED,
)
from opsbase import make_ctx

AGENT = {"id": "a1", "name": "Agent One", "type": "human"}


def test_accept_proposed_goal_activates_it_and_logs(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    assert ctx.model.goals["g2"].status == "proposed"
    acc = accept_goal(ctx, "a1", "g2")
    assert acc.agent_id == "a1" and acc.goal_id == "g2" and acc.ticket
    assert ctx.model.goals["g2"].status == "active"
    ctx.reload()
    assert ctx.model.goals["g2"].status == "active"  # persisted to the model file
    events = ctx.events.filter(type=EVENT_GOAL_ACCEPTED)
    assert len(events) == 1 and events[0].payload["ticket"] == acc.ticket


def test_accept_already_active_goal_is_idempotent(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    acc = accept_goal(ctx, "a1", "g1")
    assert ctx.model.goals["g1"].status == "active"
    assert acc.goal_id == "g1"


def test_reject_unknown_agent(tmp_path):
    ctx = make_ctx(tmp_path)
    with pytest.raises(GoalRejection) as err:
        accept_goal(ctx, "ghost", "g1")
    assert "unknown agent" in err.value.reasons[0]


def test_reject_retired_agent(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    ctx.registry.retire("a1")
    with pytest.raises(GoalRejection) as err:
        accept_goal(ctx, "a1", "g2")
    assert any("retired" in r for r in err.value.reasons)


def test_reject_owner_mismatch(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT, {"id": "a2", "name": "Two", "type": "system"}])
    with pytest.raises(GoalRejection) as err:
        accept_goal(ctx, "a2", "g1")  # g1 owned by a1
    assert any("owner" in r for r in err.value.reasons)


def test_reject_unsupported_schema_version(tmp_path):
    ctx = make_ctx(
        tmp_path,
        agents=[{"id": "a1", "name": "A", "type": "human",
                 "interface": GoalInterface(schema_versions=["9.9.9"])}],
    )
    with pytest.raises(GoalRejection) as err:
        accept_goal(ctx, "a1", "g2")
    assert any("schemaVersion" in r for r in err.value.reasons)


def test_reject_unsupported_goal_type(tmp_path):
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["type"] = "fitness"
    ctx = make_ctx(
        tmp_path,
        raw=raw,
        agents=[{"id": "a1", "name": "A", "type": "human",
                 "interface": GoalInterface(goal_types=["okr"])}],
    )
    with pytest.raises(GoalRejection) as err:
        accept_goal(ctx, "a1", "g2")
    assert any("goal type 'fitness'" in r for r in err.value.reasons)


def test_reject_at_capacity(tmp_path):
    ctx = make_ctx(
        tmp_path,
        agents=[{"id": "a1", "name": "A", "type": "human",
                 "interface": GoalInterface(max_active_goals=1)}],
    )
    # g1 is already active (1 active goal) -> accepting proposed g2 exceeds capacity
    with pytest.raises(GoalRejection) as err:
        accept_goal(ctx, "a1", "g2")
    assert any("capacity" in r for r in err.value.reasons)


def test_reject_when_model_not_wellformed(tmp_path):
    raw = copy.deepcopy(BASE)
    raw["goals"][1]["owner"] = "nobody"  # R2/R5 error
    ctx = make_ctx(tmp_path, raw=raw, agents=[AGENT])
    with pytest.raises(GoalRejection) as err:
        accept_goal(ctx, "a1", "g2")
    assert any("not well-formed" in r for r in err.value.reasons)


def test_record_action(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    event = record_action(ctx, "a1", "g1", "wrote tests", detail="3 files")
    assert event.type == EVENT_ACTION_RECORDED
    assert ctx.events.filter(goal_id="g1")[0].payload["action"] == "wrote tests"
    with pytest.raises(GoalRejection):
        record_action(ctx, "a1", "nope", "x")


def test_transition_lifecycle(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    accept_goal(ctx, "a1", "g2")  # proposed -> active
    event = transition(ctx, "a1", "g2", "achieved")
    assert event.payload["toStatus"] == "achieved"
    assert ctx.model.goals["g2"].status == "achieved"
    with pytest.raises(GoalRejection):
        transition(ctx, "a1", "g2", "active")  # terminal -> anything is rejected


def test_transition_abandoned_requires_reason(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    with pytest.raises(GoalRejection):
        transition(ctx, "a1", "g2", "abandoned")
    transition(ctx, "a1", "g2", "abandoned", reason="superseded")
    ctx.reload()
    raw_goal = next(g for g in ctx.model.raw["goals"] if g["id"] == "g2")
    assert raw_goal["status"] == "abandoned" and raw_goal["abandonReason"] == "superseded"
    assert ctx.events.filter(type=EVENT_GOAL_STATUS_CHANGED)[-1].payload["toStatus"] == "abandoned"


def test_transition_rejects_wrong_owner_and_bad_status(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT, {"id": "a2", "name": "Two", "type": "system"}])
    with pytest.raises(GoalRejection):
        transition(ctx, "a2", "g2", "active")
    with pytest.raises(GoalRejection):
        transition(ctx, "a1", "g2", "bogus")
