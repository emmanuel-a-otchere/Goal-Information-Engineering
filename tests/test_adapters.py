import copy
import csv
import io

from goal_model.adapters import CsvExport, StdoutSink, Update
from goal_model.model import load_dict
from goal_model.rules import find_issues

from test_rules import BASE


def model():
    return load_dict(copy.deepcopy(BASE))


def test_stdout_sink_pushes_all_goals(capsys):
    mapping = StdoutSink().push(model())
    assert mapping == {"g1": "stdout:g1", "g2": "stdout:g2"}
    out = capsys.readouterr().out
    assert "Top goal." in out


def test_stdout_sink_respects_goal_ids(capsys):
    mapping = StdoutSink().push(model(), ["g2"])
    assert set(mapping) == {"g2"}


def test_csv_export_round_trips():
    export = CsvExport().export(model())
    rows = list(csv.reader(io.StringIO(export)))
    assert rows[0][:2] == ["id", "statement"]
    assert {r[0] for r in rows[1:]} == {"g1", "g2"}
    assert "Top goal." in export


def test_update_applies_and_validates():
    m = model()
    update = Update(goal_id="g1", field="status", value="achieved", reason="demo")
    new = update.apply(m)
    assert new.goals["g1"].status == "achieved"
    assert m.goals["g1"].status == "active"  # original untouched
    assert not [i for i in find_issues(new) if i.severity == "error"]


def test_update_rejects_invalidating_change():
    m = model()
    update = Update(goal_id="g1", field="status", value="abandoned")  # needs abandonReason
    try:
        update.apply(m)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "abandonReason" in str(exc)
