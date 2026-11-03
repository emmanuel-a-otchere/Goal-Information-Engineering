# The GOAL Metamodel (v0.1)

This document defines the core concepts of the Goal-Information-Engineering project: what a **goal** is, how goals relate to each other and to the world, and how these concepts are serialized for machine use. The companion machine-readable schema lives at [`schema/goal.schema.json`](../schema/goal.schema.json).

## 1. Purpose

Existing goal-modeling traditions (KAOS, i*, GRL, Tropos, OKRs) are primarily **human-drawn and human-read**: they express goals as diagrams or prose. This project's contribution is a **machine-native** goal model — a small, strict, versioned data model that software (agents, planners, workflow engines, CI pipelines) can validate, query, decompose, and execute against directly.

## 2. Core definition

> A **Goal** is a statement of a **desired state of the world**, owned by an agent, bounded by conditions of satisfaction, and reachable from a current state through a (possibly implicit) plan.

Three consequences of this definition drive the model:

1. **State-based, not action-based.** A goal specifies *where you want to be*, not *what to do*. Actions and plans are derived artifacts, referenced by goals but not part of a goal's identity.
2. **Ownership is mandatory.** A goal without an owning agent is a wish, not a goal. Ownership can be shared (multiple agents) but never absent.
3. **Satisfaction is checkable.** Every goal carries `successCriteria` — evidence-based conditions that a machine (or a human) can evaluate to decide whether the goal is achieved. A goal without checkable success criteria is not yet modeled.

## 3. Core entities

| Entity | Meaning | Key fields |
|---|---|---|
| `GoalModel` | A named, versioned container of goals and supporting entities. | `id`, `name`, `version`, `goals`, `agents`, `states`, `obstacles` |
| `Goal` | A desired state with a target and measurable satisfaction conditions. | `id`, `statement`, `targetState` (ref), `successCriteria[]`, `priority`, `status`, `owner` (ref), `deadline`, `subgoals`, `refinement` |
| `Agent` | Any human, team, organization, or software system that can own or contribute to goals. | `id`, `name`, `type` (`human` \| `team` \| `organization` \| `system`) |
| `State` | A described situation of the world, current or target. | `id`, `description`, `isCurrent` |
| `Obstacle` | A condition that threatens or blocks goal achievement. | `id`, `threatens` (goal ref), `description`, `mitigation` (goal ref, optional) |
| `Criterion` | One checkable condition of success. | `description`, `evidence` (where/how to check), `verification` (`manual` \| `automated`), optional `metric` (catalog/id/version reference to a canonical metric record, e.g. [dea-catalog-metrics](https://github.com/technehub-labs/dea-catalog-metrics)) + `target` (`operator`/`value`/`unit` — the value this goal demands) |
| `Constraint` | A hard limit on how a goal may be pursued. | `description`, `kind` (`budget` \| `time` \| `resource` \| `policy` \| `other`) |

## 4. Core relationships

- **Refinement (`AND` / `OR`):** a goal may decompose into `subgoals`. `AND` refinement means *all* subgoals must be satisfied; `OR` means *at least one*. (KAOS-style.) Refinement trees must be acyclic.
- **Ownership:** `owner` and `contributors` reference agents. A goal must have at least one owner.
- **Obstruction:** an `Obstacle` `threatens` one or more goals and may be `mitigated` by another goal.
- **State gap:** every goal references a `targetState`; a goal model may declare one or more `isCurrent` states, giving the delta that planning operates over.
- **Dependency:** a goal may `dependsOn` other goals (achievement ordering) without being a subgoal.

## 5. Goal lifecycle (status)

`proposed → active → achieved | abandoned`

- `proposed`: modeled but not committed to.
- `active`: owned and being pursued.
- `achieved`: all success criteria verified.
- `abandoned`: intentionally dropped (with an optional `abandonReason` retained for knowledge).

## 6. Design rules (machine-checkable)

These are the rules the reference tooling (planned) will enforce:

1. **R1 — Unique IDs.** All entity IDs are unique within a model.
2. **R2 — Referential integrity.** Every reference (`owner`, `targetState`, `threatens`, `mitigation`, `dependsOn`, `subgoals`) resolves to an entity in the same model.
3. **R3 — Acyclic refinement.** Subgoal graphs contain no cycles.
4. **R4 — Leaf actionability.** Every `AND`-refined goal must eventually bottom out in goals whose success criteria are directly checkable (no infinite refinement).
5. **R5 — Owned goals.** Every goal has ≥ 1 owner.
6. **R6 — Deadline sanity.** A goal's deadline, if set, must not precede the deadlines of goals that depend on it being achieved first (where declared).
7. **R7 — Orphan detection (warning).** Goals not reachable from any top-level goal are flagged for review.
8. **R8 — Conflict detection (warning).** Two goals sharing an owner, deadline window, and resource constraint may be flagged for resource conflict review.
9. **R9 — Metric reference coherence.** A criterion with a `metric` reference is resolved against the local pointer registry (`schema/metric-registry.json`). Once resolved, its `target` operator must be coherent with the record's directionality (`higher_is_better` → `>=`/`>`/`==`, `lower_is_better` → `<=`/`<`/`==`, `target_band` → `band`, `categorical` → `==`) and its `unit` must match the record's unit — violations are errors. Unresolvable references (unknown catalog or record, since the full catalog is remote), pinned-version mismatches, a `target` without a `metric`, and an `automated` criterion with a `metric` but no `target` are warnings.

## 7. Positioning relative to prior art

| Tradition | Focus | What this project takes / adds |
|---|---|---|
| KAOS | Goal-oriented requirements, refinement, obstacles | Takes refinement + obstacle concepts; adds a strict JSON data model instead of diagrams |
| i* / GRL | Agents, intentions, dependencies | Takes agent ownership; adds machine-checkable success criteria |
| OKR | Business alignment, measurable outcomes | Takes measurable outcomes and cadence; adds formal refinement and dependency semantics |
| BDI agents | Desires, intentions, plans | Takes the goal–plan separation; targets a portable interchange format instead of agent-internal structures |
| Goal reasoning (AI) | Autonomous agents forming/pursuing goals | Is the primary intended consumer of this format |

## 8. Versioning

The metamodel is versioned semantically. v0.1 is intentionally minimal (the entities above). Backwards-compatible additions (new optional fields, new enum values) bump the minor version; breaking changes bump the major. The schema file carries the authoritative version in `$id` and `properties.version`. v0.2.0 adds the optional `criterion.metric` / `criterion.target` fields, rule R9, and the pointer registry `schema/metric-registry.json`; instances declaring `schemaVersion: "0.1.0"` remain valid.

## 9. Roadmap beyond v0.1

- Evidence objects with timestamps and sources (audit trail of verification).
- Probabilistic goal satisfaction (confidence, likelihood).
- Recurring goals (habits, SLAs) with cadence definitions.
- Executable criteria (URLs to CI jobs, queries, or assertions a machine can run directly).
- An LLM-assisted decomposition interface (text → candidate subgoal tree → validated model).
