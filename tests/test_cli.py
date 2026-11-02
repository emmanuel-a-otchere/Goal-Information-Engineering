import json
import subprocess
import sys
from pathlib import Path

import pytest

from goal_model.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def run(args):
    return main(args)


def test_init_creates_valid_model(tmp_path, capsys):
    out = tmp_path / "model.json"
    assert run(["init", str(out)]) == 0
    assert json.loads(out.read_text())["id"] == "my-goal-model"
    # the starter model must itself validate
    assert run(["validate", str(out)]) == 0


def test_init_refuses_overwrite(tmp_path):
    out = tmp_path / "model.json"
    out.write_text("{}")
    assert run(["init", str(out)]) == 2


def test_validate_passes_on_examples(capsys):
    assert run(["validate", str(EXAMPLES / "business-okr.json")]) == 0
    assert "VALID" in capsys.readouterr().out


def test_validate_fails_on_broken_model(tmp_path, capsys):
    model = {
        "id": "m",
        "name": "Broken",
        "version": "0.1.0",
        "agents": [{"id": "a1", "name": "A", "type": "human"}],
        "goals": [{"id": "g1", "statement": "x", "owner": "ghost"}],
    }
    p = tmp_path / "broken.json"
    p.write_text(json.dumps(model))
    assert run(["validate", str(p)]) == 1
    out = capsys.readouterr().out
    assert "INVALID" in out


def test_lint_reports_warnings_and_strict(tmp_path, capsys):
    model = {
        "id": "m",
        "name": "Lints",
        "version": "0.1.0",
        "schemaVersion": "0.1.0",
        "agents": [{"id": "a1", "name": "A", "type": "human"}],
        "goals": [
            {
                "id": "g1",
                "statement": "x",
                "owner": "a1",
                "successCriteria": [{"description": "c"}],
            },
            {
                "id": "g2",
                "statement": "orphan",
                "owner": "a1",
                "successCriteria": [{"description": "c"}],
            },
        ],
    }
    p = tmp_path / "lint.json"
    p.write_text(json.dumps(model))
    assert run(["lint", str(p)]) == 0  # warnings don't fail by default
    out = capsys.readouterr().out
    assert "R7" in out
    assert run(["lint", "--strict", str(p)]) == 1  # warnings fail in strict mode


def test_report_renders_tree_and_summary(capsys):
    assert run(["report", str(EXAMPLES / "fitness-goal.json")]) == 0
    out = capsys.readouterr().out
    assert "Half Marathon" in out
    assert "Well-formed: YES" in out
    assert "Status summary" in out


def test_tree_renders_tops(capsys):
    run(["tree", str(EXAMPLES / "business-okr.json")])
    out = capsys.readouterr().out
    assert "goal-churn" in out
    assert "goal-onboarding" in out


def test_cli_entrypoint_via_python_m():
    res = subprocess.run(
        [sys.executable, "-m", "goal_model.cli", "validate", str(EXAMPLES / "fitness-goal.json")],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "VALID" in res.stdout


def test_decompose_suggests_without_applying(tmp_path, capsys):
    model = json.loads((EXAMPLES / "business-okr.json").read_text())
    p = tmp_path / "m.json"
    p.write_text(json.dumps(model))
    assert run(["decompose", str(p), "goal-churn"]) == 0
    out = capsys.readouterr().out
    assert "candidateSubgoals" in out
    # nothing written
    assert json.loads(p.read_text()) == model


def test_decompose_apply_writes_backup_and_subgoals(tmp_path, capsys):
    model = json.loads((EXAMPLES / "fitness-goal.json").read_text())
    p = tmp_path / "m.json"
    p.write_text(json.dumps(model))
    assert run(["decompose", str(p), "goal-nutrition", "--apply"]) == 0
    updated = json.loads(p.read_text())
    new_ids = {g["id"] for g in updated["goals"]} - {g["id"] for g in model["goals"]}
    assert new_ids
    parent = next(g for g in updated["goals"] if g["id"] == "goal-nutrition")
    assert set(parent["subgoals"]) & new_ids
    backup = json.loads((tmp_path / "m.json.bak").read_text())
    assert backup == model


def test_decompose_unknown_goal_fails(tmp_path, capsys):
    p = tmp_path / "m.json"
    p.write_text((EXAMPLES / "business-okr.json").read_text())
    assert run(["decompose", str(p), "nope"]) == 1


def test_plan_renders_ready_and_blocked(capsys):
    assert run(["plan", str(EXAMPLES / "fitness-goal.json")]) == 0
    out = capsys.readouterr().out
    assert "READY" in out and "BLOCKED" in out
    assert "blocked by: goal-base" in out
    assert "Progress: 0%" in out


def test_plan_json_output(capsys):
    import json as _json
    assert run(["plan", "--json", str(EXAMPLES / "fitness-goal.json")]) == 0
    out = _json.loads(capsys.readouterr().out)
    assert out["progress"]["overall"] == 0.0
    assert any(s["goal"] == "goal-race" for s in out["plan"])
