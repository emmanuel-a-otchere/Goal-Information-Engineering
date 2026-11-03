import copy
import json

import pytest

from goal_model.decompose import (
    DecompositionError,
    LLMDecomposer,
    TemplateDecomposer,
    apply_decomposition,
)
from goal_model.model import load_dict
from goal_model.rules import find_issues

from test_rules import BASE


def model_with_orstacle():
    raw = copy.deepcopy(BASE)
    raw["obstacles"] = [
        {"id": "o1", "description": "pipeline is flaky", "threatens": "g1"}
    ]
    return load_dict(raw)


# -- TemplateDecomposer -----------------------------------------------------


def test_template_decomposer_proposes_obstacle_and_criteria_subgoals():
    model = model_with_orstacle()
    candidates = TemplateDecomposer().decompose(model, "g1")
    statements = [c["statement"] for c in candidates]
    assert any("pipeline is flaky" in s for s in statements)
    assert any("criterion one" in s for s in statements)
    assert any(s.startswith("Prepare:") for s in statements)
    # candidates inherit owner
    assert all(c["owner"] == "a1" for c in candidates)


def test_template_decomposer_rejects_unknown_goal():
    with pytest.raises(DecompositionError):
        TemplateDecomposer().decompose(load_dict(copy.deepcopy(BASE)), "nope")


# -- apply_decomposition -----------------------------------------------------


def test_apply_produces_valid_model():
    model = model_with_orstacle()
    candidates = TemplateDecomposer().decompose(model, "g1")[:3]
    raw = apply_decomposition(model, "g1", candidates)
    new_model = load_dict(raw)
    assert set(new_model.goals["g1"].subgoals) == {"g2", "g1-sub1", "g1-sub2", "g1-sub3"}
    assert new_model.goals["g1"].refinement == "and"
    errors = [i for i in find_issues(new_model) if i.severity == "error"]
    assert errors == []


def test_apply_rejects_id_collision():
    model = load_dict(copy.deepcopy(BASE))
    cand = {"id": "g2", "statement": "collide", "owner": "a1"}
    with pytest.raises(DecompositionError):
        apply_decomposition(model, "g1", [cand])


def test_apply_does_not_mutate_original():
    model = model_with_orstacle()
    before = json.dumps(model.raw, sort_keys=True)
    candidates = TemplateDecomposer().decompose(model, "g1")
    apply_decomposition(model, "g1", candidates)
    assert json.dumps(model.raw, sort_keys=True) == before


# -- LLMDecomposer ------------------------------------------------------------


def test_llm_decomposer_parses_clean_json():
    def fake_llm(prompt: str) -> str:
        assert "Top goal." in prompt
        return json.dumps(
            [
                {"statement": "Do the research.", "successCriteria": ["Notes exist."]},
                {"statement": "Run the pilot."},
            ]
        )

    model = load_dict(copy.deepcopy(BASE))
    candidates = LLMDecomposer(fake_llm).decompose(model, "g1")
    assert [c["id"] for c in candidates] == ["g1-sub1", "g1-sub2"]
    assert candidates[0]["successCriteria"][0]["description"] == "Notes exist."
    assert candidates[1]["successCriteria"][0]["description"].startswith("Subgoal")
    assert all(c["owner"] == "a1" for c in candidates)


def test_llm_decomposer_handles_chatty_output():
    def fake_llm(prompt: str) -> str:
        return "Sure! Here you go:\n[{\"statement\": \"Sub A.\"}]\nHope that helps!"

    model = load_dict(copy.deepcopy(BASE))
    candidates = LLMDecomposer(fake_llm).decompose(model, "g1")
    assert candidates[0]["statement"] == "Sub A."


def test_llm_decomposer_rejects_garbage():
    def fake_llm(prompt: str) -> str:
        return "not json at all"

    model = load_dict(copy.deepcopy(BASE))
    with pytest.raises(DecompositionError):
        LLMDecomposer(fake_llm).decompose(model, "g1")


def test_llm_candidates_apply_validly():
    def fake_llm(prompt: str) -> str:
        return json.dumps([{"statement": f"Subgoal {i}."} for i in range(3)])

    model = load_dict(copy.deepcopy(BASE))
    candidates = LLMDecomposer(fake_llm).decompose(model, "g1")
    raw = apply_decomposition(model, "g1", candidates)
    new_model = load_dict(raw)
    errors = [i for i in find_issues(new_model) if i.severity == "error"]
    assert errors == []
