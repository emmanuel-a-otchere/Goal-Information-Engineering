import http.client
import json
import threading

import pytest
from opsbase import make_ctx

from goal_model.server import make_server

AGENT = {"id": "a1", "name": "Agent One", "type": "human"}


@pytest.fixture()
def server(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    srv = make_server(ctx, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield ctx, srv.server_address[1]
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def call(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    payload = json.dumps(body) if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    conn.request(method, path, body=payload, headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, resp.getheader("Content-Type"), raw


def call_json(port, method, path, body=None):
    status, _, raw = call(port, method, path, body)
    return status, json.loads(raw)


def test_health_and_dashboard_html(server):
    _, port = server
    status, data = call_json(port, "GET", "/api/health")
    assert status == 200 and data["status"] == "ok"
    status, ctype, raw = call(port, "GET", "/")
    assert status == 200 and "text/html" in ctype
    assert b"GOAL operations dashboard" in raw


def test_agent_crud_over_api(server):
    _, port = server
    status, data = call_json(port, "POST", "/api/agents", {
        "id": "a2", "name": "Bot", "type": "system",
        "interface": {"goalTypes": ["okr"], "maxActiveGoals": 2},
    })
    assert status == 201 and data["interface"]["goalTypes"] == ["okr"]
    status, data = call_json(port, "POST", "/api/agents", {"id": "a2", "name": "dup", "type": "system"})
    assert status == 404
    status, data = call_json(port, "GET", "/api/agents")
    assert {a["id"] for a in data["agents"]} == {"a1", "a2"}
    status, data = call_json(port, "GET", "/api/agents/a2")
    assert data["name"] == "Bot"
    status, data = call_json(port, "PATCH", "/api/agents/a2", {"status": "paused"})
    assert status == 200 and data["status"] == "paused"
    status, data = call_json(port, "POST", "/api/agents/a2/retire")
    assert status == 200 and data["status"] == "retired"


def test_accept_goal_over_api(server):
    _, port = server
    status, data = call_json(port, "POST", "/api/agents/a1/goals", {"goalId": "g2"})
    assert status == 201 and data["goalId"] == "g2" and data["ticket"]
    status, data = call_json(port, "POST", "/api/agents/a1/goals", {"goalId": "missing"})
    assert status == 409 and any("unknown goal" in r for r in data["reasons"])
    status, data = call_json(port, "POST", "/api/agents/ghost/goals", {"goalId": "g1"})
    assert status == 409
    status, data = call_json(port, "GET", "/api/agents/a1/goals")
    assert status == 200 and set(data["goals"]) == {"g1", "g2"}


def test_events_status_assess_metrics_over_api(server):
    ctx, port = server
    call_json(port, "POST", "/api/agents/a1/goals", {"goalId": "g2"})

    status, data = call_json(port, "POST", "/api/goals/g2/events", {
        "type": "action.recorded", "agentId": "a1", "action": "trained",
    })
    assert status == 201 and data["type"] == "action.recorded"
    status, data = call_json(port, "POST", "/api/goals/g2/events", {"type": "goal.accepted"})
    assert status == 400  # lifecycle events are not accepted here

    status, data = call_json(port, "POST", "/api/goals/g2/status", {
        "agentId": "a1", "status": "achieved",
    })
    assert status == 200 and data["payload"]["toStatus"] == "achieved"
    assert ctx.model.goals["g2"].status == "achieved"
    status, data = call_json(port, "POST", "/api/goals/g2/status", {
        "agentId": "a1", "status": "active",
    })
    assert status == 409

    status, data = call_json(port, "POST", "/api/goals/g2/assess", {
        "evidence": {"criterion two": "training log export"},
    })
    assert status == 201 and data["verdict"] == "achieved" and data["score"] == 1.0

    status, data = call_json(port, "GET", "/api/metrics")
    assert status == 200
    assert data["goals"]["g2"]["status"] == "achieved"
    # registered + accepted + action + status_changed + assessed
    assert data["agents"]["a1"]["activities"] == 5

    status, data = call_json(port, "GET", "/api/events?goalId=g2&type=action.recorded")
    assert len(data["events"]) == 1 and data["events"][0]["payload"]["action"] == "trained"
    status, data = call_json(port, "GET", "/api/assessments?goalId=g2")
    assert len(data["assessments"]) == 1
    status, data = call_json(port, "GET", "/api/goals/g2")
    assert status == 200 and data["goal"]["id"] == "g2" and data["ops"]["status"] == "achieved"
    status, data = call_json(port, "GET", "/api/goals/nope")
    assert status == 404
    status, data = call_json(port, "GET", "/api/nope")
    assert status == 404


def test_server_refuses_non_loopback_host(tmp_path):
    ctx = make_ctx(tmp_path, agents=[AGENT])
    with pytest.raises(ValueError):
        make_server(ctx, host="0.0.0.0", port=0)
