from __future__ import annotations

import search
from pricing_runtime import (
    _fallback_state,
    _hv_candidate_relevance,
    _hv_relaxed_queries,
    _merge_candidate,
    install_hv_runtime,
)
from research_core_adapter import install_research_core_pricing


QUESTION = "11kV AIS 3000A switchboard, 25kA, 2 incomers 2000A, 8 x feeders 630A"


def setup_module():
    # Match the application startup order: shared evidence mechanics first,
    # then the Internet Pricing HV relevance/queue policy.
    install_research_core_pricing()
    install_hv_runtime(search)


def test_hv_gate_rejects_commercially_rich_unrelated_tender():
    bad = {
        "title": "Aquarium refurbishment contract award",
        "snippet": "Winning bid GBP 4,200,000. Procurement contract award and lot value.",
        "url": "https://example.com/aquarium-award",
        "query": QUESTION,
    }
    good = {
        "title": "11kV VCB switchgear feeder panel tender",
        "snippet": "630A feeder, 25kA vacuum circuit breaker panel. Unit price INR 402,543.",
        "url": "https://example.com/11kv-vcb-panel",
        "query": QUESTION,
    }

    assert _hv_candidate_relevance(bad, QUESTION)[0] is False
    assert _hv_candidate_relevance(good, QUESTION)[0] is True

    filtered = search.subject_relevant_candidates([bad, good], QUESTION, "hv-equipment")
    assert [item["url"] for item in filtered] == [good["url"]]


def test_hv_gate_returns_empty_instead_of_restoring_irrelevant_candidates():
    rows = [{
        "title": "Public aquarium mechanical services tender",
        "snippet": "Contract value GBP 8,000,000; award notice and procurement details.",
        "url": "https://example.com/aquarium",
        "query": QUESTION,
    }]
    assert search.subject_relevant_candidates(rows, QUESTION, "hv-equipment") == []


def test_hv_gate_accepts_12kv_equipment_class_for_11kv_system():
    candidate = {
        "title": "12kV AIS metal-clad switchgear",
        "snippet": "630A VCB feeder panel, 25kA short-circuit rating, withdrawable breaker.",
        "url": "https://example.com/12kv-ais-switchgear",
        "query": QUESTION,
    }
    ok, reason, score = _hv_candidate_relevance(candidate, QUESTION)
    assert ok is True
    assert reason == "RELEVANT_EQUIPMENT"
    assert score > 1.0


def test_commercial_evidence_bonus_cannot_revive_unrelated_hv_result():
    bad = {
        "title": "Aquarium construction tender award",
        "snippet": "Award value GBP 19,500,000; winning bid; BOQ and contract value.",
        "url": "https://example.com/very-commercial-but-wrong",
        "query": QUESTION,
    }
    good = {
        "title": "11kV AIS switchgear VCB feeder panel",
        "snippet": "630A 25kA feeder panel technical specification.",
        "url": "https://example.com/relevant-switchgear",
        "query": QUESTION,
    }

    ranked = search.rank_candidates([bad, good], QUESTION, [], [], "hv-equipment")
    assert [item["url"] for item in ranked] == [good["url"]]


def test_hv_search_backends_continue_when_first_engines_are_irrelevant(monkeypatch):
    calls = []

    class FakeDDGS:
        def __init__(self, timeout=12):
            self.timeout = timeout

        def text(self, query, region, safesearch, max_results, backend):
            calls.append(backend)
            if backend in {"duckduckgo", "mojeek"}:
                return [{
                    "title": f"{backend} aquarium award",
                    "href": f"https://{backend}.example/aquarium",
                    "body": "Contract award GBP 4,000,000 procurement lot value.",
                }]
            return [{
                "title": f"{backend} 11kV VCB switchgear panel",
                "href": f"https://{backend}.example/switchgear",
                "body": "630A feeder panel 25kA AIS switchgear tender unit price.",
            }]

    monkeypatch.setattr(search, "DDGS", FakeDDGS)
    rows, status = search.search_web(
        '"11kV" "630A" VCB feeder panel unit price',
        "duckduckgo,mojeek,startpage,yahoo",
        6,
    )

    assert calls == ["duckduckgo", "mojeek", "startpage", "yahoo"]
    assert any("duckduckgo: 1 / 0 relevant" in item for item in status)
    assert any("mojeek: 1 / 0 relevant" in item for item in status)
    assert any("startpage: 1 / 1 relevant" in item for item in status)
    assert any("yahoo: 1 / 1 relevant" in item for item in status)
    assert len(rows) == 4


def test_relaxed_queries_drop_the_full_board_monolith_but_keep_key_components():
    queries = _hv_relaxed_queries(QUESTION, 2)
    assert any("630A" in item and "VCB" in item for item in queries)
    assert any("2000A" in item and "incomer" in item.lower() for item in queries)
    assert any("25kA" in item and "BOQ" in item for item in queries)
    assert any("12kV" in item for item in queries)
    assert not all("3000A" in item and "2000A" in item and "630A" in item for item in queries)


def test_candidate_queue_keeps_distinct_unattempted_urls():
    pool = {}
    first = {"url": "https://example.com/1", "snippet": "first"}
    second = {"url": "https://example.com/2", "snippet": "second"}
    richer_first = {"url": "https://example.com/1", "snippet": "first with richer evidence"}

    _merge_candidate(pool, first)
    _merge_candidate(pool, second)
    _merge_candidate(pool, richer_first)

    assert set(pool) == {first["url"], second["url"]}
    assert pool[first["url"]]["snippet"] == richer_first["snippet"]


def test_fallback_message_distinguishes_rejected_evidence_from_web_outage():
    label, detail = _fallback_state(47, 9, 8, 8)
    assert "Web searched successfully" in label
    assert "Web unavailable" not in label
    assert "47 search results" in detail
    assert "9 equipment-relevant" in detail
    assert "8 pages attempted" in detail
