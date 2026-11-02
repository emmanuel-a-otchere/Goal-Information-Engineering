# Contributing to Goal-Information-Engineering

Thanks for your interest! This project builds a machine-native model for goals — the earlier the community shapes it, the better the metamodel will be.

## Ground rules

1. **Metamodel changes are design decisions.** Schema and type changes go through a discussion issue first. Changes must respect the design rules (R1–R8) in [`docs/GOAL-METAMODEL.md`](docs/GOAL-METAMODEL.md) and the versioning policy (§8): additive optional fields bump the minor version; breaking changes bump the major and need a migration note.
2. **Adapters stay out of the core.** Integrations with external systems implement the `Sink`/`Source` protocols in `src/goal_model/adapters.py` and must not require schema changes.
3. **No network calls in tests.** Anything needing an LLM or external API takes an injected callable/connection.

## Development setup

```bash
git clone https://github.com/emmanuel-a-otchere/Goal-Information-Engineering
cd Goal-Information-Engineering
pip install -e .[dev]
pytest
```

## Before you open a PR

- `pytest` passes (CI runs Python 3.9 and 3.12).
- `goal validate examples/business-okr.json` and `goal validate examples/fitness-goal.json` still pass.
- New rules/checks come with tests, including a failing-model fixture that triggers them.
- If you changed `schema/goal.schema.json`, update `bindings/typescript/goal-model.d.ts` in the same commit and bump both versions.
- Docs live in `docs/`; keep the metamodel doc and the README in sync with behavior changes.

## PR checklist

- [ ] Tests added or updated
- [ ] Schema and TypeScript bindings updated together (if touched)
- [ ] `pytest` green locally
- [ ] Commit messages explain *why*, not just *what*

## Reporting issues

Use the bug or proposal templates in `.github/ISSUE_TEMPLATE/`. For metamodel proposals, include: the concept, why existing entities can't express it, and a JSON example.
