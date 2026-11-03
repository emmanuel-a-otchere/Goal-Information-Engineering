from goal_model.store import OperationsStore
from goal_model.telemetry import (
    EVENT_ACTION_RECORDED,
    EVENT_GOAL_ACCEPTED,
    Event,
    EventLog,
)


def test_store_roundtrip_agents_and_assessments(tmp_path):
    store = OperationsStore(tmp_path / "ops")
    assert store.load_agents() == []
    store.save_agents([{"id": "a1"}])
    assert store.load_agents() == [{"id": "a1"}]
    assert store.load_assessments() == []
    store.save_assessments([{"id": "x"}])
    assert store.load_assessments() == [{"id": "x"}]


def test_event_log_append_read_filter(tmp_path):
    log = EventLog(OperationsStore(tmp_path / "ops"))
    assert log.all() == []
    e1 = log.append(EVENT_GOAL_ACCEPTED, agent_id="a1", goal_id="g1", ticket="t1")
    e2 = log.append(EVENT_ACTION_RECORDED, agent_id="a1", goal_id="g2", action="run")
    e3 = log.append(EVENT_ACTION_RECORDED, agent_id="a2", goal_id="g2", action="walk")

    assert e1.ts and e1.id
    events = log.all()
    assert [e.type for e in events] == [EVENT_GOAL_ACCEPTED, EVENT_ACTION_RECORDED, EVENT_ACTION_RECORDED]
    assert [e.goal_id for e in log.filter(goal_id="g2")] == ["g2", "g2"]
    assert [e.agent_id for e in log.filter(agent_id="a2")] == ["a2"]
    assert len(log.filter(type=EVENT_ACTION_RECORDED)) == 2
    assert len(log.filter(limit=2)) == 2
    assert events[1].payload["action"] == "run"
    assert e2.to_dict()["goalId"] == "g2"


def test_event_from_dict_roundtrip():
    e = Event(type="x", agent_id="a", goal_id="g", payload={"k": 1}, ts="2026-01-01T00:00:00+00:00", id="abc")
    assert Event.from_dict(e.to_dict()) == e
