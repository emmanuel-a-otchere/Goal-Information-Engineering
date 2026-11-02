"""Command-line interface: goal init|validate|lint|report|tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .model import GoalModel, load, load_dict
from .report import full_report, goal_tree, issues_report
from .rules import find_issues

MINIMAL_MODEL = {
    "id": "my-goal-model",
    "name": "My Goal Model",
    "version": "0.1.0",
    "schemaVersion": "0.1.0",
    "description": "A new GOAL model. Edit me!",
    "agents": [{"id": "me", "name": "Me", "type": "human"}],
    "goals": [
        {
            "id": "goal-1",
            "statement": "Describe the state of the world you want here.",
            "owner": "me",
            "successCriteria": [
                {
                    "description": "Describe how to check that the goal is achieved.",
                    "verification": "manual",
                }
            ],
            "status": "proposed",
            "priority": "medium",
        }
    ],
}


def _load(path: str) -> GoalModel:
    p = Path(path)
    if not p.exists():
        print(f"error: no such file: {path}", file=sys.stderr)
        sys.exit(2)
    if p.suffix == ".json":
        return load(p)
    if p.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            print("error: PyYAML required for YAML files (pip install pyyaml)", file=sys.stderr)
            sys.exit(2)
        return load_dict(yaml.safe_load(p.read_text(encoding="utf-8")))
    print(f"error: unsupported file type: {p.suffix}", file=sys.stderr)
    sys.exit(2)


def cmd_init(args: argparse.Namespace) -> int:
    out = Path(args.file)
    if out.exists() and not args.force:
        print(f"error: {out} exists (use --force to overwrite)", file=sys.stderr)
        return 2
    if out.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore

            out.write_text(yaml.safe_dump(MINIMAL_MODEL, sort_keys=False), encoding="utf-8")
        except ImportError:
            print("error: PyYAML required for YAML files", file=sys.stderr)
            return 2
    else:
        out.write_text(json.dumps(MINIMAL_MODEL, indent=2) + "\n", encoding="utf-8")
    print(f"Created {out}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    model = _load(args.file)
    issues = find_issues(model)
    errors = [i for i in issues if i.severity == "error"]
    if args.quiet:
        return 1 if errors else 0
    if errors:
        print(issues_report(errors))
        print(f"INVALID: {len(errors)} error(s)")
        return 1
    print("VALID")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    model = _load(args.file)
    issues = find_issues(model)
    print(issues_report(issues if not args.quiet else [i for i in issues if i.severity == "error"]))
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    if not args.quiet:
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if (errors or (warnings and args.strict)) else 0


def cmd_report(args: argparse.Namespace) -> int:
    model = _load(args.file)
    print(full_report(model))
    return 0


def cmd_tree(args: argparse.Namespace) -> int:
    model = _load(args.file)
    print(goal_tree(model))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="goal",
        description="Machine-native goal models: validate, query, and report on GOAL models.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create a starter GOAL model file")
    p_init.add_argument("file", nargs="?", default="goal-model.json")
    p_init.add_argument("--force", action="store_true", help="overwrite existing file")
    p_init.set_defaults(func=cmd_init)

    p_val = sub.add_parser("validate", help="validate a model (schema + rules R1-R8)")
    p_val.add_argument("file")
    p_val.add_argument("-q", "--quiet", action="store_true")
    p_val.set_defaults(func=cmd_validate)

    p_lint = sub.add_parser("lint", help="list all issues, including warnings")
    p_lint.add_argument("file")
    p_lint.add_argument("--strict", action="store_true", help="treat warnings as errors")
    p_lint.add_argument("-q", "--quiet", action="store_true")
    p_lint.set_defaults(func=cmd_lint)

    p_rep = sub.add_parser("report", help="full human-readable report")
    p_rep.add_argument("file")
    p_rep.set_defaults(func=cmd_report)

    p_tree = sub.add_parser("tree", help="render the goal refinement tree")
    p_tree.add_argument("file")
    p_tree.set_defaults(func=cmd_tree)

    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
