import json

from goal_model.cli import main
from opsbase import write_model

AGENT_ARGS = ["--id", "a1", "--name", "Agent One", "--type", "human"]


def test_agent_admin_and_ops_flow(tmp_path, capsys):
    model = write_model(tmp_path)
    store = str(tmp_path / "ops")

    assert main(["agent", "register", "--store", store, *AGENT_ARGS]) == 0
    assert main(["agent", "register", "--store", store, *AGENT_ARGS]) == 1  # duplicate
    assert main(["agent", "list", "--store", store]) == 0
    assert "a1" in capsys.readouterr().out
    assert main(["agent", "list", "--store", store, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["agents"][0]["id"] == "a1"
    assert main(["agent", "show", "--store", store, "a1"]) == 0
    capsys.readouterr()
    assert main(["agent", "show", "--store", store, "ghost"]) == 1
    capsys.readouterr()

    assert main(["accept", str(model), "--store", store, "--agent", "a1", "--goal", "g2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["goalId"] == "g2" and out["ticket"]

    assert main(["accept", str(model), "--store", store, "--agent", "ghost", "--goal", "g1"]) == 1

    assert main([
        "event", str(model), "--store", store, "--agent", "a1", "--goal", "g2",
        "--action", "wrote tests",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["type"] == "action.recorded"

    assert main([
        "assess", str(model), "--store", store, "--goal", "g2",
        "--evidence", "criterion two=log export",
    ]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "achieved" and out["score"] == 1.0

    assert main(["dashboard", str(model), "--store", store, "--json"]) == 0
    metrics = json.loads(capsys.readouterr().out)
    assert metrics["goals"]["g2"]["status"] == "active"
    assert metrics["goals"]["g2"]["latestAssessment"]["verdict"] == "achieved"

    assert main(["dashboard", str(model), "--store", store]) == 0
    text = capsys.readouterr().out
    assert "GOAL operations dashboard" in text and "g2" in text

    assert main([
        "transition", str(model), "--store", store, "--agent", "a1", "--goal", "g2",
        "--status", "achieved",
    ]) == 0
    assert main([
        "transition", str(model), "--store", store, "--agent", "a1", "--goal", "g2",
        "--status", "active",
    ]) == 1  # terminal state cannot move

    assert main(["agent", "retire", "--store", store, "a1"]) == 0
    assert main(["agent", "list", "--store", store, "--status", "retired"]) == 0
    assert "a1" in capsys.readouterr().out


def test_assess_with_goal_type_override(tmp_path, capsys):
    model = write_model(tmp_path)
    store = str(tmp_path / "ops")
    main(["agent", "register", "--store", store, *AGENT_ARGS])
    capsys.readouterr()
    assert main([
        "assess", str(model), "--store", store, "--goal", "g1", "--goal-type", "checklist",
    ]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["assessor"] == "checklist" and out["goalType"] == "checklist"


def test_assess_unknown_goal_fails(tmp_path, capsys):
    model = write_model(tmp_path)
    store = str(tmp_path / "ops")
    assert main(["assess", str(model), "--store", store, "--goal", "nope"]) == 1
    assert "unknown goal" in capsys.readouterr().err
