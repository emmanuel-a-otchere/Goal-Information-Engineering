# Agent Operations (Phase 5): strategy, plan, and API reference

This document is the strategy and plan for advancing Goal Information
Engineering from a static metamodel to **executable operations**: tools and
APIs with which a user administers agents, an agent *declares an interface
for accepting a well-defined goal*, a dashboard monitors goal-realizing
activities/actions, performance and adherence, and a framework assesses an
agent against a goal in a standard way — with a registry for homing in on
specific goal types.

## 1. Strategy

**The metamodel stays static; operations live beside it.** Per the project
ground rules (CONTRIBUTING.md), integrations stay out of the core and must
not require schema changes. So Phase 5 adds a thin **runtime layer** next to
a GOAL model file — never a change to `schema/goal.schema.json`:

- The **GOAL model file remains the single source of truth for goal state**
  (status, owner, criteria). Runtime status transitions validate against
  schema + R1–R8 before being persisted atomically.
- An **operations store** (a directory, default `.goal-ops/`) holds only
  runtime state: `agents.json` (registry), `events.jsonl` (telemetry),
  `assessments.json` (assessment reports).
- **Zero new dependencies**: the REST API and dashboard use only the Python
  standard library (`http.server`), and bind to **loopback (127.0.0.1)
  only** — the server refuses non-loopback hosts. It is a local
  administration surface, not a public service.
- **Protocol-first ingestion**: an agent's acceptance of a goal is governed
  by its *declared interface* (accepted schema versions, goal types,
  capabilities, capacity), enforced at acceptance time with explicit,
  machine-readable rejection reasons.
- **Event-sourced telemetry**: every operation appends an event to the
  JSONL log; the dashboard/metrics are read-models derived from
  model + events + assessments. This is also the timestamped evidence/audit
  trail foreseen in the metamodel roadmap.
- **Pluggable assessment**: one standard assessment plus a registry of
  goal-type-specific assessors; the goal's optional `type` field (tolerated
  by the schema, which does not set `additionalProperties: false`) selects
  the typed assessor.

### Architecture

```
                 ┌──────────────────────────────────────────────┐
                 │  Executable surfaces                          │
                 │  CLI (goal agent|accept|event|transition|     │
                 │  assess|dashboard|serve)   REST API + HTML   │
                 │  dashboard (goal serve, loopback only)        │
                 └───────────────┬──────────────────────────────┘
                                 │ RuntimeContext (runtime.py)
        ┌────────────────────────┼───────────────────────────┐
        ▼                        ▼                           ▼
 GOAL model file        OperationsStore (.goal-ops/)   AssessorRegistry
 (source of truth  ◄──  agents.json | events.jsonl  ◄── standard + typed
  for goal state)        assessments.json                 assessors
        ▲                        ▲
        │              telemetry EventLog (JSONL append)
        └─ Planner (ready/blocked, progress) ──► metrics read-model ──► dashboard
```

### Components

| Module | Role |
|---|---|
| `store.py` | `OperationsStore`: atomic JSON/JSONL persistence for runtime state |
| `registry.py` | `AgentRegistry` + `AgentRecord` + declared `GoalInterface` |
| `interface.py` | Goal ingestion: `accept_goal`, `transition`, `record_action`, `GoalRejection` |
| `telemetry.py` | `EventLog` / `Event`: append-only activity log |
| `assess.py` | `Assessor` protocol, `StandardAssessor`, `ChecklistAssessor`, `AssessorRegistry`, `assess_goal` |
| `metrics.py` | `compute_metrics`: dashboard read-model over model + events + assessments |
| `dashboard.py` | Text (CLI) and HTML renderers |
| `runtime.py` | `RuntimeContext`: model + store + registry + events + assessors |
| `server.py` | Loopback-only REST API (`http.server`) + HTML dashboard |

## 2. Plan (delivery order)

1. **P5.1 Store + registry** — administer agents: register/list/show/retire,
   each declaring its `GoalInterface`.
2. **P5.2 Goal ingestion interface** — `accept_goal` enforces the declared
   interface + metamodel rules and returns an acceptance ticket; lifecycle
   `transition` with guarded status moves.
3. **P5.3 Telemetry** — JSONL event log of goal-realizing activities/actions.
4. **P5.4 Assessment framework** — standard assessment (per-criterion
   verdicts, adherence, performance, score) + goal-type registry with a
   built-in `checklist` typed assessor; custom types plug in via
   `AssessorRegistry.register`.
5. **P5.5 Dashboard** — metrics read-model + CLI text dashboard + HTML
   dashboard + `GET /api/metrics`.
6. **P5.6 REST API** — `goal serve` (loopback only) exposing all of the
   above as JSON APIs.
7. **P5.7 Docs/tests/CI** — this document, README sync, pytest coverage, CI
   smoke.

Next steps beyond this phase: real Source/Sink adapters feeding telemetry
from external systems (GitHub Issues, CI), auth on the ops API for shared
hosts, and recurring goals.

## 3. Concepts

### Agent and declared goal interface

```json
{
  "id": "agent-runner",
  "name": "The Runner",
  "type": "human",
  "status": "active",
  "interface": {
    "version": "0.1.0",
    "schemaVersions": ["0.1.0"],
    "goalTypes": ["fitness", "*"],
    "capabilities": ["accept-goals", "report-actions"],
    "maxActiveGoals": 10
  }
}
```

`GoalInterface.goalTypes` uses `"*"` for any type. The goal's own optional
`"type": "fitness"` field is what typed assessors and admission checks key on.

### Acceptance

`accept_goal(agent, goal)` checks, in order: agent exists and is active;
the model's `schemaVersion` is accepted; the goal exists, is owned by the
agent, is not terminal; the goal type is accepted; capacity
(`maxActiveGoals`) is not exceeded; the model passes schema + R1–R8. On
success a proposed goal becomes `active`, an acceptance ticket is returned,
and a `goal.accepted` event is logged. On failure a `GoalRejection` carries
**all** reasons (HTTP 409 with `{"reasons": [...]}`).

### Telemetry events

`agent.registered`, `agent.retired`, `goal.accepted`, `goal.status_changed`,
`action.recorded`, `criterion.checked`, `obstacle.raised`,
`constraint.violated`, `goal.assessed` — each with `id`, ISO-8601 `ts`,
`agentId`, `goalId`, `payload`.

### Assessment

`assess_goal(goal_id, goal_type?, evidence?)` picks the assessor via the
registry (explicit `goal_type` > goal's declared `type` > `standard`
fallback), runs it, persists the report to `assessments.json`, and logs
`goal.assessed`. An `Assessment` contains per-criterion
`pass|fail|unverified` verdicts with evidence, an **adherence** section
(deadline ok, constraints respected, violation count, score), a
**performance** section (activities, actions, accepted/first/last activity,
days active), an overall `verdict` (`achieved|partial|not_achieved`) and a
0..1 `score`.

Evidence is keyed by criterion description or by zero-based index
(`{"0": "..."}` is robust for descriptions containing `=`).

When a criterion carries a `metric` reference and a `target` (metamodel v0.2,
rule R9), a **numeric** evidence value is treated as a measurement and
evaluated mechanically against the target (`<`, `<=`, `>`, `>=`, `==`,
`band`), e.g. `goal assess model.json --store .goal-ops --goal goal-churn
--evidence "0=97.6"`. The criterion verdict note records the measured value,
the target, and the resolved catalog record with its directionality from the
local pointer registry (`schema/metric-registry.json`, sourced from
[dea-catalog-metrics](https://github.com/technehub-labs/dea-catalog-metrics));
`CriterionResult` also persists `metric` and `measurement` for the audit
trail. Explicit boolean/`{"pass": ...}` evidence still overrides.

The dashboard read-model (`GET /api/metrics`, `goal dashboard`) exposes each
goal's `metricCriteria` — catalog, record id, pinned version, target, and the
latest assessed verdict/measurement — rendered in both the text and HTML
dashboards.

## 4. CLI reference

```bash
goal agent register --store .goal-ops --id agent-runner --name "The Runner" --type human \
    --goal-type fitness --capability accept-goals --max-active-goals 10
goal agent list --store .goal-ops [--json] [--status active]
goal agent show --store .goal-ops agent-runner
goal agent retire --store .goal-ops agent-runner

goal accept model.json --store .goal-ops --agent agent-runner --goal goal-base
goal event model.json --store .goal-ops --agent agent-runner --goal goal-base --action "long run" --detail "25km"
goal transition model.json --store .goal-ops --agent agent-runner --goal goal-base --status achieved
goal assess model.json --store .goal-ops --goal goal-base --goal-type fitness --evidence "0=app export wk1-4"
goal dashboard model.json --store .goal-ops [--json]
goal serve model.json --store .goal-ops --host 127.0.0.1 --port 8377
```

`--store` defaults to `.goal-ops/`. `accept`/`transition` persist model
changes atomically (validated first).

## 5. REST API reference (loopback only)

Base URL `http://127.0.0.1:8377` (configurable via `--host/--port`; the
server refuses non-loopback binds).

| Method & path | Body | Response |
|---|---|---|
| `GET /` | — | HTML dashboard (auto-refresh 10s) |
| `GET /api/health` | — | `{"status": "ok"}` |
| `GET /api/agents` | — | `{"agents": [...]}` |
| `POST /api/agents` | `{id, name, type, interface?, metadata?}` | `201` agent record |
| `GET /api/agents/{id}` | — | agent record (`404` unknown) |
| `PATCH /api/agents/{id}` | `{name?, status?, interface?, metadata?}` | updated record |
| `POST /api/agents/{id}/retire` | — | retired record |
| `GET /api/agents/{id}/goals` | — | goals owned by the agent |
| `POST /api/agents/{id}/goals` | `{"goalId": "..."}` | `201` acceptance ticket; `409 {"reasons": [...]}` |
| `GET /api/goals` / `GET /api/goals/{id}` | — | goal ids / goal + ops state |
| `POST /api/goals/{id}/events` | `{"type": "action.recorded", "agentId": "...", ...}` | `201` event (`400` for non-activity types) |
| `POST /api/goals/{id}/status` | `{"agentId", "status", "reason?"}` | `200` event; `409` illegal transition |
| `POST /api/goals/{id}/assess` | `{"goalType?", "evidence?"}` | `201` assessment |
| `GET /api/metrics` | — | dashboard metrics read-model |
| `GET /api/events?agentId=&goalId=&type=&limit=` | — | filtered telemetry |
| `GET /api/assessments?goalId=` | — | persisted assessments |

## 6. Extending: homing in on a goal type

1. Give goals of that type a declared type: `"type": "fitness"` on the goal
   (optional field; the schema allows additional properties).
2. Declare it on the agent's interface: `goalTypes: ["fitness"]`.
3. Register a typed assessor:

```python
from goal_model.assess import StandardAssessor, AssessorRegistry

class FitnessAssessor(StandardAssessor):
    name = "fitness"
    # override assess() for domain-specific checks (e.g. parse
    # "pace <= 5:40 min/km" style criteria against evidence)

registry = AssessorRegistry.default()
registry.register("fitness", FitnessAssessor())
ctx.assessors = registry
```

`assess_goal` then dispatches to `FitnessAssessor` for `"fitness"` goals and
falls back to `StandardAssessor` for everything else. A goal type of
`"checklist"` is built in (`ChecklistAssessor`): all criteria must pass with
evidence and no unmitigated obstacle may threaten the goal.

## 7. Library usage

```python
from goal_model.runtime import RuntimeContext

ctx = RuntimeContext("model.json", ".goal-ops")
ctx.registry.register("agent-runner", "The Runner", "human")
ticket = ctx.accept_goal("agent-runner", "goal-base")   # may raise GoalRejection
ctx.record_action("agent-runner", "goal-base", "long run", detail="25km")
assessment = ctx.assess_goal("goal-base", evidence={"0": "app export wk1-4"})
metrics = ctx.metrics()                                   # dashboard read-model
```
