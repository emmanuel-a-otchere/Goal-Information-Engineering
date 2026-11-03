"""Command-line interface: goal init|validate|lint|report|tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters import CsvExport
from .assess import AssessmentError
from .dashboard import render_dashboard_text
from .decompose import DecompositionError, LLMDecomposer, TemplateDecomposer, apply_decomposition
from .interface import GoalRejection
from .model import GoalModel, load, load_dict
from .planner import Planner
from .registry import AgentRegistry, GoalInterface, RegistryError
from .report import full_report, goal_tree, issues_report
from .rules import find_issues
from .runtime import DEFAULT_STORE_DIR, RuntimeContext

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


def cmd_decompose(args: argparse.Namespace) -> int:
    model = _load(args.file)
    decomposer = TemplateDecomposer()
    try:
        candidates = decomposer.decompose(model, args.goal_id)
        result = apply_decomposition(model, args.goal_id, candidates, validate=False)
    except DecompositionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.apply:
        out = Path(args.file)
        backup = out.with_suffix(out.suffix + ".bak")
        backup.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"Applied {len(candidates)} subgoals to '{args.goal_id}' (backup at {backup})")
        return 0
    print(json.dumps({"goal": args.goal_id, "candidateSubgoals": candidates}, indent=2))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    model = _load(args.file)
    planner = Planner()
    if args.json:
        out = {"plan": planner.plan(model).as_dict(), "progress": planner.progress(model)}
        print(json.dumps(out, indent=2))
        return 0
    print("Pursuit plan (dependencies first):")
    for step in planner.plan(model).steps:
        marker = "READY " if step.ready else "BLOCKED"
        blocked = f" (blocked by: {', '.join(step.blocked_by)})" if step.blocked_by else ""
        print(f"  [{marker}] {step.goal_id}: {step.statement}{blocked}")
    progress = planner.progress(model)
    print(f"\nProgress: {progress['overall'] * 100:.0f}% overall")
    for top, frac in progress["byTopLevel"].items():
        print(f"  {top}: {frac * 100:.0f}%")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    model = _load(args.file)
    csv_out = CsvExport().export(model)
    if args.output:
        Path(args.output).write_text(csv_out, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(csv_out, end="")
    return 0


# -- operations layer: agents, goal ingestion, telemetry, assessment -----


def _ctx(args: argparse.Namespace) -> RuntimeContext:
    return RuntimeContext(args.file, getattr(args, "store", DEFAULT_STORE_DIR))


def _registry(args: argparse.Namespace):
    """Registry-only access (agent admin commands do not need a model file)."""
    from .store import OperationsStore
    from .telemetry import EventLog

    store = OperationsStore(getattr(args, "store", DEFAULT_STORE_DIR))
    events = EventLog(store)
    return AgentRegistry(store, events)


def _parse_evidence(pairs: list) -> dict:
    evidence = {}
    for pair in pairs or []:
        if "=" not in pair:
            print(f"error: --evidence expects key=value, got: {pair}", file=sys.stderr)
            sys.exit(2)
        key, value = pair.split("=", 1)
        evidence[key] = value
    return evidence


def cmd_agent_register(args: argparse.Namespace) -> int:
    interface = GoalInterface(
        version=args.interface_version,
        schema_versions=args.schema_version or ["0.1.0"],
        goal_types=args.goal_type or ["*"],
        capabilities=args.capability or ["accept-goals"],
        max_active_goals=args.max_active_goals,
    )
    try:
        record = _registry(args).register(args.id, args.name, args.type, interface=interface)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_agent_list(args: argparse.Namespace) -> int:
    agents = [a.to_dict() for a in _registry(args).list(status=args.status)]
    if args.json:
        print(json.dumps({"agents": agents}, indent=2))
    else:
        for a in agents:
            iface = a["interface"]
            print(
                f"{a['id']} [{a['status']}] {a['name']} ({a['type']}) "
                f"goalTypes={iface['goalTypes']} maxActiveGoals={iface['maxActiveGoals']}"
            )
        if not agents:
            print("(no agents registered)")
    return 0


def cmd_agent_show(args: argparse.Namespace) -> int:
    try:
        print(json.dumps(_registry(args).get(args.id).to_dict(), indent=2))
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_agent_retire(args: argparse.Namespace) -> int:
    try:
        record = _registry(args).retire(args.id)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Retired {record.id}")
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    try:
        acceptance = ctx.accept_goal(args.agent, args.goal)
    except GoalRejection as exc:
        print("REJECTED:", file=sys.stderr)
        for reason in exc.reasons:
            print(f"  - {reason}", file=sys.stderr)
        return 1
    print(json.dumps(acceptance.to_dict(), indent=2))
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    try:
        event = ctx.record_action(
            args.agent, args.goal, args.action, detail=args.detail or ""
        )
    except GoalRejection as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(event.to_dict(), indent=2))
    return 0


def cmd_transition(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    try:
        event = ctx.transition(args.agent, args.goal, args.status, reason=args.reason or "")
    except GoalRejection as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(event.to_dict(), indent=2))
    return 0


def cmd_assess(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    try:
        assessment = ctx.assess_goal(
            args.goal, goal_type=args.goal_type, evidence=_parse_evidence(args.evidence)
        )
    except AssessmentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(assessment.to_dict(), indent=2))
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    metrics = ctx.metrics()
    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(render_dashboard_text(metrics))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    ctx = _ctx(args)
    serve(ctx, host=args.host, port=args.port)
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

    p_dec = sub.add_parser("decompose", help="suggest candidate subgoals for a goal")
    p_dec.add_argument("file")
    p_dec.add_argument("goal_id")
    p_dec.add_argument("--apply", action="store_true", help="write subgoals into the model file (a .bak backup is kept)")
    p_dec.set_defaults(func=cmd_decompose)

    p_plan = sub.add_parser("plan", help="pursuit plan and progress")
    p_plan.add_argument("file")
    p_plan.add_argument("--json", action="store_true")
    p_plan.set_defaults(func=cmd_plan)

    p_exp = sub.add_parser("export", help="export goals to CSV")
    p_exp.add_argument("file")
    p_exp.add_argument("-o", "--output", help="write to a file instead of stdout")
    p_exp.set_defaults(func=cmd_export)

    # -- operations layer ---------------------------------------------------

    def add_store(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--store",
            default=DEFAULT_STORE_DIR,
            help=f"operations store directory (default: {DEFAULT_STORE_DIR})",
        )

    p_agent = sub.add_parser("agent", help="administer registered agents")
    agent_sub = p_agent.add_subparsers(dest="agent_command", required=True)

    p_areg = agent_sub.add_parser("register", help="register an agent with its declared goal interface")
    add_store(p_areg)
    p_areg.add_argument("--id", required=True)
    p_areg.add_argument("--name", required=True)
    p_areg.add_argument("--type", required=True, choices=["human", "team", "organization", "system"])
    p_areg.add_argument("--interface-version", default="0.1.0")
    p_areg.add_argument("--schema-version", action="append", help="accepted GOAL schemaVersion (repeatable)")
    p_areg.add_argument("--goal-type", action="append", help="goal type the agent pursues (repeatable, default: *)")
    p_areg.add_argument("--capability", action="append", help="declared capability (repeatable)")
    p_areg.add_argument("--max-active-goals", type=int, default=10)
    p_areg.set_defaults(func=cmd_agent_register)

    p_alist = agent_sub.add_parser("list", help="list registered agents")
    add_store(p_alist)
    p_alist.add_argument("--status", choices=["active", "paused", "retired"])
    p_alist.add_argument("--json", action="store_true")
    p_alist.set_defaults(func=cmd_agent_list)

    p_ashow = agent_sub.add_parser("show", help="show one agent's record and interface")
    add_store(p_ashow)
    p_ashow.add_argument("id")
    p_ashow.set_defaults(func=cmd_agent_show)

    p_aret = agent_sub.add_parser("retire", help="retire an agent")
    add_store(p_aret)
    p_aret.add_argument("id")
    p_aret.set_defaults(func=cmd_agent_retire)

    p_acc = sub.add_parser("accept", help="offer a goal to an agent through its declared interface")
    p_acc.add_argument("file")
    add_store(p_acc)
    p_acc.add_argument("--agent", required=True)
    p_acc.add_argument("--goal", required=True)
    p_acc.set_defaults(func=cmd_accept)

    p_ev = sub.add_parser("event", help="record a goal-realizing action in the telemetry log")
    p_ev.add_argument("file")
    add_store(p_ev)
    p_ev.add_argument("--agent", required=True)
    p_ev.add_argument("--goal", required=True)
    p_ev.add_argument("--action", required=True)
    p_ev.add_argument("--detail", default="")
    p_ev.set_defaults(func=cmd_event)

    p_tr = sub.add_parser("transition", help="move a goal through its lifecycle (e.g. active -> achieved)")
    p_tr.add_argument("file")
    add_store(p_tr)
    p_tr.add_argument("--agent", required=True)
    p_tr.add_argument("--goal", required=True)
    p_tr.add_argument("--status", required=True, choices=["proposed", "active", "achieved", "abandoned"])
    p_tr.add_argument("--reason", default="")
    p_tr.set_defaults(func=cmd_transition)

    p_ass = sub.add_parser("assess", help="assess an agent against a goal (standard or goal-type assessor)")
    p_ass.add_argument("file")
    add_store(p_ass)
    p_ass.add_argument("--goal", required=True)
    p_ass.add_argument("--goal-type", help="override the goal's declared type for assessor dispatch")
    p_ass.add_argument("--evidence", action="append", help="criterion evidence as key=value (repeatable)")
    p_ass.set_defaults(func=cmd_assess)

    p_dash = sub.add_parser("dashboard", help="render the operations dashboard (activities, performance, adherence)")
    p_dash.add_argument("file")
    add_store(p_dash)
    p_dash.add_argument("--json", action="store_true")
    p_dash.set_defaults(func=cmd_dashboard)

    p_srv = sub.add_parser("serve", help="serve the REST API + HTML dashboard on loopback only")
    p_srv.add_argument("file")
    add_store(p_srv)
    p_srv.add_argument("--host", default="127.0.0.1", help="bind host (loopback only; default 127.0.0.1)")
    p_srv.add_argument("--port", type=int, default=8377)
    p_srv.set_defaults(func=cmd_serve)

    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
