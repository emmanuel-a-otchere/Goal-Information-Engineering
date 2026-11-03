"""Loopback REST API + dashboard server for agent goal operations.

Stdlib-only (``http.server``), no new dependencies. The server binds to
127.0.0.1 by default and is meant for local administration of agents and
their goals; it is not designed to be exposed publicly.

Endpoints:

- ``GET  /``                              HTML dashboard (auto-refreshing)
- ``GET  /api/health``                    liveness probe
- ``GET  /api/agents``                    list agents
- ``POST /api/agents``                    register an agent (body: agent record incl. ``interface``)
- ``GET  /api/agents/{id}``               one agent
- ``PATCH /api/agents/{id}``              update name/status/interface/metadata
- ``POST /api/agents/{id}/retire``        retire an agent
- ``GET  /api/agents/{id}/goals``         goals owned by an agent
- ``POST /api/agents/{id}/goals``         accept a goal (body: ``{"goalId": ...}``) -> 201 acceptance
- ``GET  /api/goals``                     list goals with ops state
- ``GET  /api/goals/{id}``                one goal with ops state
- ``POST /api/goals/{id}/events``         record an activity (body: ``{"type": ..., "agentId": ..., ...}``)
- ``POST /api/goals/{id}/status``         lifecycle transition (body: ``{"agentId": ..., "status": ..., "reason": ...}``)
- ``POST /api/goals/{id}/assess``         run an assessment (body: ``{"goalType": ..., "evidence": {...}}``)
- ``GET  /api/metrics``                   dashboard metrics read-model (JSON)
- ``GET  /api/events?agentId=&goalId=&type=&limit=``   telemetry
- ``GET  /api/assessments?goalId=``       persisted assessments
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .assess import AssessmentError
from .dashboard import render_dashboard_html
from .interface import GoalRejection
from .registry import AGENT_STATUSES, GoalInterface, RegistryError
from .runtime import RuntimeContext
from .telemetry import ACTIVITY_EVENT_TYPES, EVENT_ACTION_RECORDED

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8377


def _goal_view(ctx, goal_id: str) -> Optional[Dict[str, Any]]:
    goal = ctx.model.goals.get(goal_id)
    if goal is None:
        return None
    m = ctx.metrics()
    goal_dict = {
        "id": goal.id,
        "statement": goal.statement,
        "owner": goal.owner,
        "targetState": goal.target_state,
        "successCriteria": [
            {"description": c.description, "evidence": c.evidence, "verification": c.verification}
            for c in goal.success_criteria
        ],
        "contributors": list(goal.contributors),
        "priority": goal.priority,
        "status": goal.status,
        "deadline": goal.deadline,
        "subgoals": list(goal.subgoals),
        "refinement": goal.refinement,
        "dependsOn": list(goal.depends_on),
        "constraints": list(goal.constraints),
        "abandonReason": goal.abandon_reason,
    }
    return {"goal": goal_dict, "ops": m["goals"].get(goal_id, {})}


def make_handler(ctx: RuntimeContext):
    class Handler(BaseHTTPRequestHandler):
        server_version = "GoalOps/0.1"

        def log_message(self, format, *args):  # keep test/CLI output clean
            pass

        # -- helpers ------------------------------------------------------

        def _send_json(self, status: int, data: Any) -> None:
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, status: int, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                raise ValueError("request body is not valid JSON")
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _error(self, status: int, message: str, **extra: Any) -> None:
            self._send_json(status, {"error": message, **extra})

        # -- routing --------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            qs = parse_qs(urlparse(self.path).query)
            try:
                if path == "/":
                    self._send_html(200, render_dashboard_html(ctx.metrics()))
                elif path == "/api/health":
                    self._send_json(200, {"status": "ok"})
                elif path == "/api/agents":
                    self._send_json(200, {"agents": [a.to_dict() for a in ctx.registry.list()]})
                elif m := re.fullmatch(r"/api/agents/([^/]+)", path):
                    agent = ctx.registry.get(m.group(1))
                    self._send_json(200, agent.to_dict())
                elif m := re.fullmatch(r"/api/agents/([^/]+)/goals", path):
                    agent = ctx.registry.get(m.group(1))
                    goals = [
                        gid for gid, g in ctx.model.goals.items() if g.owner == agent.id
                    ]
                    self._send_json(200, {"agentId": agent.id, "goals": goals})
                elif path == "/api/goals":
                    self._send_json(200, {"goals": list(ctx.model.goals)})
                elif m := re.fullmatch(r"/api/goals/([^/]+)", path):
                    view = _goal_view(ctx, m.group(1))
                    if view is None:
                        self._error(404, f"unknown goal: {m.group(1)}")
                    else:
                        self._send_json(200, view)
                elif path == "/api/metrics":
                    self._send_json(200, ctx.metrics())
                elif path == "/api/events":
                    events = ctx.events.filter(
                        agent_id=qs.get("agentId", [None])[0],
                        goal_id=qs.get("goalId", [None])[0],
                        type=qs.get("type", [None])[0],
                        limit=int(qs["limit"][0]) if "limit" in qs else None,
                    )
                    self._send_json(200, {"events": [e.to_dict() for e in events]})
                elif path == "/api/assessments":
                    assessments = ctx.store.load_assessments()
                    gid = qs.get("goalId", [None])[0]
                    if gid:
                        assessments = [a for a in assessments if a.get("goalId") == gid]
                    self._send_json(200, {"assessments": assessments})
                else:
                    self._error(404, f"no such endpoint: {path}")
            except RegistryError as exc:
                self._error(404, str(exc))
            except ValueError as exc:
                self._error(400, str(exc))

        def do_PATCH(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                m = re.fullmatch(r"/api/agents/([^/]+)", path)
                if not m:
                    self._error(404, f"no such endpoint: {path}")
                    return
                body = self._body()
                status = body.get("status")
                if status is not None and status not in AGENT_STATUSES:
                    self._error(400, f"invalid status: {status}")
                    return
                interface = (
                    GoalInterface.from_dict(body["interface"]) if "interface" in body else None
                )
                agent = ctx.registry.update(
                    m.group(1),
                    name=body.get("name"),
                    status=status,
                    interface=interface,
                    metadata=body.get("metadata"),
                )
                self._send_json(200, agent.to_dict())
            except RegistryError as exc:
                self._error(404, str(exc))
            except ValueError as exc:
                self._error(400, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                if path == "/api/agents":
                    body = self._body()
                    for field_name in ("id", "name", "type"):
                        if not body.get(field_name):
                            self._error(400, f"missing field: {field_name}")
                            return
                    record = ctx.registry.register(
                        id=body["id"],
                        name=body["name"],
                        type=body["type"],
                        interface=(
                            GoalInterface.from_dict(body["interface"])
                            if body.get("interface")
                            else None
                        ),
                        metadata=body.get("metadata"),
                    )
                    self._send_json(201, record.to_dict())
                    return
                m = re.fullmatch(r"/api/agents/([^/]+)/goals", path)
                if m:
                    body = self._body()
                    goal_id = body.get("goalId")
                    if not goal_id:
                        self._error(400, "missing field: goalId")
                        return
                    acceptance = ctx.accept_goal(m.group(1), goal_id)
                    self._send_json(201, acceptance.to_dict())
                    return
                m = re.fullmatch(r"/api/agents/([^/]+)/retire", path)
                if m:
                    self._send_json(200, ctx.registry.retire(m.group(1)).to_dict())
                    return
                m = re.fullmatch(r"/api/goals/([^/]+)/events", path)
                if m:
                    body = self._body()
                    event_type = body.get("type", EVENT_ACTION_RECORDED)
                    if event_type not in ACTIVITY_EVENT_TYPES:
                        self._error(
                            400,
                            f"event type must be one of {sorted(ACTIVITY_EVENT_TYPES)}",
                        )
                        return
                    agent_id = body.get("agentId", "")
                    payload = {k: v for k, v in body.items() if k not in ("type", "agentId")}
                    event = ctx.events.append(event_type, agent_id=agent_id, goal_id=m.group(1), **payload)
                    self._send_json(201, event.to_dict())
                    return
                m = re.fullmatch(r"/api/goals/([^/]+)/status", path)
                if m:
                    body = self._body()
                    for field_name in ("agentId", "status"):
                        if not body.get(field_name):
                            self._error(400, f"missing field: {field_name}")
                            return
                    event = ctx.transition(
                        body["agentId"], m.group(1), body["status"], reason=body.get("reason", "")
                    )
                    self._send_json(200, event.to_dict())
                    return
                m = re.fullmatch(r"/api/goals/([^/]+)/assess", path)
                if m:
                    body = self._body()
                    assessment = ctx.assess_goal(
                        m.group(1),
                        goal_type=body.get("goalType"),
                        evidence=body.get("evidence"),
                    )
                    self._send_json(201, assessment.to_dict())
                    return
                self._error(404, f"no such endpoint: {path}")
            except RegistryError as exc:
                self._error(404, str(exc))
            except GoalRejection as exc:
                self._send_json(409, {"error": "goal rejected", "reasons": exc.reasons})
            except AssessmentError as exc:
                self._error(404, str(exc))
            except ValueError as exc:
                self._error(400, str(exc))

    return Handler


def make_server(
    ctx: RuntimeContext, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> ThreadingHTTPServer:
    """Build the HTTP server. ``port=0`` picks a free ephemeral port."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("refusing to bind non-loopback host; use 127.0.0.1")
    return ThreadingHTTPServer((host, port), make_handler(ctx))


def serve(ctx: RuntimeContext, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = make_server(ctx, host, port)
    actual_host, actual_port = server.server_address[:2]
    print(f"GOAL operations dashboard: http://{actual_host}:{actual_port}/ (loopback only, Ctrl+C to stop)")
    print(f"JSON API under http://{actual_host}:{actual_port}/api/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
