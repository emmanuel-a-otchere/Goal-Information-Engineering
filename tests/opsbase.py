import copy
import json
from pathlib import Path

from test_rules import BASE

from goal_model.runtime import RuntimeContext


def write_model(tmp_path: Path, raw=None) -> Path:
    raw = raw if raw is not None else copy.deepcopy(BASE)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "model.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def make_ctx(tmp_path: Path, raw=None, agents=()) -> RuntimeContext:
    model_path = write_model(tmp_path, raw)
    ctx = RuntimeContext(model_path, tmp_path / "ops")
    for agent in agents:
        ctx.registry.register(**agent)
    return ctx
