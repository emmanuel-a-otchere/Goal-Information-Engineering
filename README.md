# Goal-Information-Engineering

**A machine-native model for goals: what a goal *is*, how goals relate to agents, states, obstacles, and each other — expressed as a strict, versioned data model that software can validate, query, decompose, and act on.**

As AI takes center stage, goal-oriented modeling is the key to software that can manage software. Existing goal-modeling traditions (KAOS, i*, GRL, OKRs) are human-drawn and human-read; this project turns the same ideas into computational models — information, data, and knowledge about goals that agents, planners, and automation can use directly.

## Status

Early stage. Current deliverables:

- [`docs/GOAL-METAMODEL.md`](docs/GOAL-METAMODEL.md) — the GOAL metamodel v0.1: core definition, entities, relationships, lifecycle, and machine-checkable design rules.
- [`schema/goal.schema.json`](schema/goal.schema.json) — the authoritative JSON Schema for GOAL model instances (v0.1.0).
- [`examples/`](examples/) — worked examples: a business OKR and a personal fitness goal, both fully valid instances of the schema.

## What a goal is here

> A **Goal** is a statement of a **desired state of the world**, owned by an agent, bounded by conditions of satisfaction, and reachable from a current state through a (possibly implicit) plan.

Consequences: goals are state-based (not action-based), ownership is mandatory, and success must be checkable. See the [metamodel doc](docs/GOAL-METAMODEL.md) for the full ontology — refinement (AND/OR), obstacles, constraints, dependencies, and the goal lifecycle.

## Quick start

A minimal valid GOAL model:

```json
{
  "id": "hello-goal",
  "name": "Hello Goal",
  "version": "1.0.0",
  "schemaVersion": "0.1.0",
  "agents": [{ "id": "me", "name": "Me", "type": "human" }],
  "goals": [
    {
      "id": "g1",
      "statement": "Publish the first release of this project.",
      "owner": "me",
      "successCriteria": [
        { "description": "A GitHub release marked v0.1.0 exists.", "verification": "automated" }
      ],
      "status": "active",
      "priority": "high"
    }
  ]
}
```

Validate any instance against the schema with [jsonschema](https://pypi.org/project/jsonschema/):

```bash
pip install jsonschema check-jsonschema
check-jsonschema --schemafile schema/goal.schema.json examples/business-okr.json
```

## Roadmap

- **Phase 1 — Definition** *(this repo's current focus)*: metamodel, JSON Schema, worked examples. ✅
- **Phase 2 — Automation**: a reference Python library (`goal-model`) for validation, goal-tree queries, refinement checking, conflict/orphan detection, and a CLI (`goal init/validate/lint/report`).
- **Phase 3 — Intelligence**: LLM-assisted goal decomposition (text → candidate subgoal tree → validated model) and a planner interface (current-state → target-state deltas).
- **Phase 4 — Ecosystem**: interchange bindings (generated TypeScript/Python types), adapters for issue trackers, OKR tools, CI pipelines, and community scaffolding.

## Positioning

This project builds on goal-oriented requirements engineering (KAOS, i*, GRL, Tropos), OKR practice, BDI agent theory, and goal reasoning in autonomous agents. The comparison table in the [metamodel doc](docs/GOAL-METAMODEL.md#7-positioning-relative-to-prior-art) details what it takes from each tradition and what it adds: a portable, machine-native interchange format with checkable satisfaction criteria.

## Contributing

Issues and PRs are welcome. Early-stage work should stay aligned with the metamodel: propose schema changes via the design rules in the metamodel doc rather than ad-hoc field additions.

## License

[BSD 3-Clause](LICENSE) © 2022–present emmanuel-a-otchere
