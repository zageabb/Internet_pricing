from __future__ import annotations

from types import SimpleNamespace

from pricing_research_policy import (
    classify_price_scope,
    layered_pricing_queries,
    should_render_specialist_candidate,
)


def _search_stub():
    def terms(value):
        import re
        return set(re.findall(r"[a-z0-9][a-z0-9_-]{1,}", str(value).lower()))

    return SimpleNamespace(
        pricing_category=lambda _query: "hv-equipment",
        terms=terms,
    )


def test_hv_queries_are_decomposed_into_component_evidence_searches():
    request = "11kV AIS 3200A switchboard, 25kA, 2 incomers 2000A, 8 feeders 630A"
    queries = layered_pricing_queries(_search_stub(), request, [], "hv-equipment")
    joined = "\n".join(queries).lower()

    assert "630a vcb feeder panel" in joined
    assert "2000a incomer switchgear" in joined
    assert "3200a busbar switchgear" in joined
    assert "invoice customs import export transaction value" in joined
    assert "iec 62271-200 technical data" in joined


def test_hv_planner_query_can_explore_partial_component_match():
    request = "11kV AIS 3200A switchboard, 25kA, 2 incomers 2000A, 8 feeders 630A"
    planned = ["11kV 630A VCB panel TenderKart award", "unrelated office chair price"]
    queries = layered_pricing_queries(_search_stub(), request, planned, "hv-equipment")

    assert "11kV 630A VCB panel TenderKart award" in queries
    assert "unrelated office chair price" not in queries


def test_scope_classifier_rejects_whole_substation_value():
    project = (
        "Contract value INR 969000000 for complete substation including transformers, DG generators, "
        "LT boards, cables, civil buildings, installation and commissioning."
    )
    equipment = "BOQ unit price INR 402543 each for 11kV 630A outgoing VCB panel."

    assert classify_price_scope(project) == "project"
    assert classify_price_scope(equipment) == "equipment"


def test_specialist_browser_rendering_is_allowed_for_thin_tender_page():
    search = SimpleNamespace(
        pricing_category=lambda _query: "hv-equipment",
        terms=lambda value: set(str(value).lower().replace("/", " ").split()),
    )
    candidate = {
        "title": "11kV switchgear tender award",
        "url": "https://example.com/tender",
        "snippet": "Procurement tender for 11kV AIS switchgear; commercial schedule available online",
        "query": "11kV AIS switchgear tender award price",
        "rank": 2,
    }
    page = {"text": "Tender page", "content_type": "text/html"}

    assert should_render_specialist_candidate(search, lambda *_: False, candidate, page) is True
