# Goal-Information-Engineering

**A machine-native model for goals: what a goal *is*, how goals relate to agents, states, obstacles, and each other, expressed as a strict, versioned data model that software can validate, query, decompose, and act on.**

As AI takes center stage, goal-oriented modeling is the key to software that can manage software. Existing goal-modeling traditions (KAOS, i*, GRL, OKRs) are human-drawn and human-read; this project turns the same ideas into computational models — information, data, and knowledge about goals that agents, planners, and automation can use directly.

## Status

All four roadmap phases have first working versions:

- **Definition** — [`docs/GOAL-METAMODEL.md`](docs/GOAL-METAMODEL.md) (metamodel v0.1: entities, relationships, lifecycle, design rules R1–R8) and [`schema/goal.schema.json`](schema/goal.schema.json) (the authoritative JSON Schema).
- **Automation** — a reference Python library and CLI: schema + rules validation, tree reports, and pursuit planning. `pip install -e .` → `goal` command.
- **Intelligence** — decomposition (`TemplateDecomposer` for deterministic, `LLMDecomposer` for LLM-assisted via an injected callable) and a `Planner` (state gaps, ready/blocked pursuit order, progress).
- **Ecosystem** — TypeScript type bindings ([`bindings/typescript/`](bindings/typescript/)), a Sink/Source adapter framework with CSV export, and CI (Python 3.9 + 3.12).
- [`examples/`](examples/) — a business OKR and a personal fitness goal, both fully valid instances used in CI.

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

Validate any instance against the schema with the CLI:

```bash
pip install -e .            # installs the `goal` command and library
goal validate examples/business-okr.json   # schema + rules R1-R8
goal lint examples/business-okr.json        # includes warnings, --strict to fail on them
goal tree examples/fitness-goal.json        # refinement forest
goal plan examples/fitness-goal.json        # ready/blocked pursuit order + progress
goal decompose examples/business-okr.json goal-churn   # candidate subgoals
goal decompose examples/business-okr.json goal-churn --apply  # insert them (backup kept)
goal export examples/fitness-goal.json -o goals.csv
goal init my-goal-model.json               # starter model
```

## Roadmap

- **Phase 1 — Definition** ✅ metamodel, JSON Schema, worked examples.
- **Phase 2 — Automation** ✅ reference Python library and CLI (`validate/lint/report/tree/init/export`) implementing design rules R1–R8.
- **Phase 3 — Intelligence** ✅ deterministic and LLM-assisted decomposition, pursuit planner with state gaps and progress.
- **Phase 4 — Ecosystem** ✅ TypeScript bindings, Sink/Source adapter framework, CI, contributing guide.
- **Next:** evidence objects with timestamps (verification audit trail), recurring goals, executable criteria (URLs to checkable assertions), real adapters (GitHub Issues, Linear, OKR tools), and packaging the library to PyPI.

## Positioning

This project builds on goal-oriented requirements engineering (KAOS, i*, GRL, Tropos), OKR practice, BDI agent theory, and goal reasoning in autonomous agents. The comparison table in the [metamodel doc](docs/GOAL-METAMODEL.md#7-positioning-relative-to-prior-art) details what it takes from each tradition and what it adds: a portable, machine-native interchange format with checkable satisfaction criteria.

## Contributing

Issues and PRs are welcome. Early-stage work should stay aligned with the metamodel: propose schema changes via the design rules in the metamodel doc rather than ad-hoc field additions.

## License

[BSD 3-Clause](LICENSE) © 2022–present emmanuel-a-otchere
