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
