from unittest.mock import patch

import generic_expansion_policy as expansion
from app import search_module as search
import pricing_runtime


def _settings():
    return {"ollama_url": "http://ollama.invalid", "model": "test-model"}


def _plan():
    return {
        "canonical": [
            {"query": "Google Pixel 11 Pro Fold retailer price", "reason": "Possible official naming expansion"},
        ],
        "near": [
            {"query": "160MVA 220/132kV power transformer award price", "reason": "Nearby MVA transformer comparator"},
        ],
        "adjacent": [
            {"query": "200MVA 400/132kV power transformer BOQ price", "reason": "Same voltage class, different MVA"},
        ],
        "broad": [
            {"query": "large power transformer tender unit price", "reason": "Broad family benchmark"},
        ],
    }


def _prepare(query, category):
    expansion._reset_state(query)
    with patch.object(search, "ollama_json", return_value=_plan()):
        return search.prepare_expansion_plan(query, "test-model", _settings(), category)


def test_expansion_plan_has_canonical_and_comparator_levels():
    plan = _prepare("Pixel 11 Fold price", "consumer-retail")
    assert plan["canonical"][0]["query"] == "Google Pixel 11 Pro Fold retailer price"
    assert plan["near"][0]["label"] == "near-spec comparator"
    assert plan["adjacent"][0]["label"] == "adjacent-family comparator"
    assert plan["broad"][0]["label"] == "broad family benchmark"


def test_consumer_canonical_expansion_can_reach_source_review_without_becoming_exact_by_default():
    _prepare("Pixel 11 Fold price", "consumer-retail")
    candidate = {
        "title": "Google Pixel 11 Pro Fold - Buy now",
        "snippet": "Google Pixel 11 Pro Fold from GBP 1,799",
        "url": "https://store.example/pixel-11-pro-fold",
        "query": "Google Pixel 11 Pro Fold retailer price",
    }
    accepted = search.subject_relevant_candidates([candidate], "Pixel 11 Fold price", "consumer-retail")
    assert len(accepted) == 1
    assert accepted[0].get("expansion_candidate") is True or "expansion" in str(accepted[0].get("identity_match_reason", "")).lower()
    assert search.exact_priced_product_candidate(candidate, "Pixel 11 Fold price", candidate["snippet"]) is False


def test_near_comparator_price_does_not_satisfy_exact_consumer_threshold():
    query = "Pixel 11 Fold price"
    expansion._reset_state(query)
    with patch.object(search, "ollama_json", return_value={
        "canonical": [],
        "near": [{"query": "Pixel 10 Pro Fold retailer price", "reason": "Previous-generation comparator"}],
        "adjacent": [],
        "broad": [],
    }):
        search.prepare_expansion_plan(query, "test-model", _settings(), "consumer-retail")
    evidence = [{
        "title": "Pixel 10 Pro Fold",
        "url": "https://shop.example/pixel-10-pro-fold",
        "query": "Pixel 10 Pro Fold retailer price",
        "text": "Pixel 10 Pro Fold price GBP 1,699",
        "claims": ["GBP 1,699"],
        "passages": [],
    }]
    status = search.benchmark_status(evidence, query, "consumer-retail")
    assert status["qualifying_priced_sources"] == 0
    assert status["sufficient"] is False


def test_transformer_comparator_bypasses_exact_rating_pre_gate_for_llm_review():
    query = "150MVA 400/132kV power transformer price"
    expansion._reset_state(query)
    with patch.object(search, "ollama_json", return_value={
        "canonical": [],
        "near": [{"query": "160MVA 220/132kV power transformer award price", "reason": "Nearby market comparator"}],
        "adjacent": [],
        "broad": [],
    }):
        search.prepare_expansion_plan(query, "test-model", _settings(), "power-transformers")

    candidate = {
        "title": "Award for 160MVA 220/132kV power transformer",
        "snippet": "Supply of 160MVA 220/132kV autotransformer - INR 161,600,000 per transformer",
        "url": "https://procurement.example/160mva-award",
        "query": "160MVA 220/132kV power transformer award price",
    }
    accepted, rejected = pricing_runtime._collect_relevance(search, [candidate], query, "power-transformers")
    assert len(accepted) == 1
    assert accepted[0]["expansion_candidate"] is True
    assert not rejected


def test_hv_followup_filter_keeps_tagged_comparator_even_when_exact_query_gate_would_reject_it():
    query = "150MVA 400/132kV power transformer price"
    expansion._reset_state(query)
    with patch.object(search, "ollama_json", return_value={
        "canonical": [],
        "near": [{"query": "160MVA 220/132kV power transformer award price", "reason": "Nearby market comparator"}],
        "adjacent": [],
        "broad": [],
    }):
        search.prepare_expansion_plan(query, "test-model", _settings(), "power-transformers")
    rows = pricing_runtime._safe_hv_followups(
        search, ["160MVA 220/132kV power transformer award price"], query
    )
    assert rows == ["160MVA 220/132kV power transformer award price"]


def test_expanded_source_is_judged_by_llm_and_relation_is_visible_in_prompt():
    query = "150MVA 400/132kV power transformer price"
    expansion._reset_state(query)
    expanded_query = "160MVA 220/132kV power transformer award price"
    with patch.object(search, "ollama_json", return_value={
        "canonical": [],
        "near": [{"query": expanded_query, "reason": "Nearby market comparator"}],
        "adjacent": [],
        "broad": [],
    }):
        search.prepare_expansion_plan(query, "test-model", _settings(), "power-transformers")

    captured = {}

    def fake_json(_url, _model, prompt):
        captured["prompt"] = prompt
        return {"verdict": "useful", "reason": "Useful price comparator with different voltage ratio", "claims": ["INR 161.6m per unit"]}

    prompts = {"source_review": "QUERY={{query}}\nTITLE={{title}}\nURL={{url}}\nCONTENT={{content}}"}
    with patch.object(search, "ollama_json", side_effect=fake_json):
        verdict, reason, claims = search.analyse_source(
            prompts, _settings(), "test-model", expanded_query,
            "160MVA transformer award", "https://procurement.example/a",
            "160MVA 220/132kV transformer. Unit price INR 161,600,000.",
        )
    assert verdict == "useful"
    assert "different voltage" in reason.lower()
    assert claims == ["INR 161.6m per unit"]
    assert "Original request: 150MVA 400/132kV power transformer price" in captured["prompt"]
    assert "near-spec comparator" in captured["prompt"]
    assert "not as proof of equivalence" in captured["prompt"]


def test_priced_comparator_ledger_is_visible_to_final_answer_review():
    assert expansion._has_priced_expansion_text(
        "query | near-spec comparator | equivalence not assumed\nPrice: INR 161,600,000"
    ) is True
