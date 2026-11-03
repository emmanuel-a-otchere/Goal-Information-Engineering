import pytest

from goal_model.registry import (
    AGENT_RETIRED,
    AgentRegistry,
    GoalInterface,
    RegistryError,
)
from goal_model.store import OperationsStore
from goal_model.telemetry import EVENT_AGENT_REGISTERED, EVENT_AGENT_RETIRED, EventLog


def registry(tmp_path):
    store = OperationsStore(tmp_path / "ops")
    return AgentRegistry(store, EventLog(store))


def test_register_get_list(tmp_path):
    reg = registry(tmp_path)
    rec = reg.register("a1", "Agent One", "human")
    assert rec.interface.accepts_goal_type("anything")
    assert reg.get("a1").name == "Agent One"
    reg.register("a2", "Agent Two", "system", interface=GoalInterface(goal_types=["fitness"]))
    assert {a.id for a in reg.list()} == {"a1", "a2"}
    assert not reg.get("a2").interface.accepts_goal_type("okr")
    assert reg.get("a2").interface.accepts_goal_type("fitness")
    assert [a.id for a in reg.list(status=AGENT_RETIRED)] == []


def test_duplicate_id_rejected(tmp_path):
    reg = registry(tmp_path)
    reg.register("a1", "Agent One", "human")
    with pytest.raises(RegistryError):
        reg.register("a1", "Again", "human")


def test_unknown_agent_raises(tmp_path):
    with pytest.raises(RegistryError):
        registry(tmp_path).get("nope")


def test_update_and_retire(tmp_path):
    reg = registry(tmp_path)
    reg.register("a1", "Agent One", "human")
    rec = reg.update("a1", name="Renamed", status="paused", interface=GoalInterface(max_active_goals=3))
    assert rec.name == "Renamed" and rec.status == "paused"
    assert reg.get("a1").interface.max_active_goals == 3
    with pytest.raises(RegistryError):
        reg.update("a1", status="bogus")
    retired = reg.retire("a1")
    assert retired.status == AGENT_RETIRED
    assert [a.id for a in reg.list(status=AGENT_RETIRED)] == ["a1"]


def test_registration_and_retirement_emit_events(tmp_path):
    store = OperationsStore(tmp_path / "ops")
    log = EventLog(store)
    reg = AgentRegistry(store, log)
    reg.register("a1", "Agent One", "human")
    reg.retire("a1")
    types = [e.type for e in log.all()]
    assert types == [EVENT_AGENT_REGISTERED, EVENT_AGENT_RETIRED]


def test_interface_dict_roundtrip():
    iface = GoalInterface(
        version="0.1.0",
        schema_versions=["0.1.0", "0.2.0"],
        goal_types=["okr"],
        capabilities=["accept-goals", "self-assess"],
        max_active_goals=5,
    )
    assert GoalInterface.from_dict(iface.to_dict()) == iface
    assert iface.accepts_schema_version("0.2.0")
    assert not iface.accepts_schema_version("9.9.9")
