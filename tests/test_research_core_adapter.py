from __future__ import annotations

from unittest.mock import patch

import research_core
from research_core import best_passages
from research_core.ranking import cosine_similarity

import browser_fetch
import search
from research_core_adapter import _hv_layered_queries, install_research_core_pricing


TARGET = "11kV AIS 3200A switchboard, 25kA, 2 incomers 2000A, 8 feeders 630A"


def test_research_core_dependency_is_v02():
    assert research_core.__version__ == "0.2.0"


def test_pricing_adapter_installs_shared_mechanics():
    install_research_core_pricing()
    assert search.best_passages is best_passages
    assert search.cosine_similarity is cosine_similarity
    assert search.RESEARCH_CORE_VERSION == "0.2.0"


def test_hv_queries_split_complex_board_into_evidence_layers():
    queries = _hv_layered_queries(f"Find pricing for {TARGET}", [])
    joined = "\n".join(queries)
    assert len(queries) >= 6
    assert '"11kV" "2000A" "25kA" incomer' in joined
    assert '"11kV" "630A" "25kA" feeder' in joined
    assert '"11kV" "3200A" busbar' in joined
    assert "TenderKart" in joined
    assert "Volza" in joined
    assert not all("3200A" in query and "2000A" in query and "630A" in query for query in queries)


def test_adapter_allows_bounded_rendering_for_strong_hv_evidence_page():
    install_research_core_pricing()
    candidate = {
        "title": "11kV 630A 25kA VCB tender award",
        "url": "https://tenderkart.in/tender/example",
        "snippet": "Tender result for 11kV VCB panels; detailed value loads in the page application.",
        "query": '"11kV" "630A" "25kA" feeder VCB panel tender award unit price',
        "rank": 1,
    }
    page = {"text": "Tender detail page without a visible value in lightweight HTML", "content_type": "text/html"}
    with patch("search.public_url", return_value=True), \
            patch("browser_fetch.browser_fallback_enabled", return_value=True), \
            patch("browser_fetch.browser_page_limit", return_value=3):
        assert browser_fetch.should_render_candidate(candidate, page) is True


def test_hv_project_total_does_not_end_research():
    install_research_core_pricing()
    evidence = [{
        "title": "Large substation project tender",
        "url": "https://eprocure.example/project",
        "text": "11kV switchgear with transformers, DG set, LT panel, cables and civil works. Project value INR 969,000,000.",
        "claims": [],
        "passages": [],
    }]
    assert search.has_sufficient_commercial_benchmark(evidence, TARGET, "hv-equipment") is False


def test_hv_panel_award_can_end_research_and_is_role_labelled():
    install_research_core_pricing()
    evidence = [{
        "source_id": 1,
        "title": "11kV 630A 25kA VCB panel tender award",
        "url": "https://tenderkart.in/tender/example",
        "query": "11kV 630A 25kA VCB panel award price",
        "text": "Seven 11kV 630A 25kA AIS panels. Winning bid INR 4,663,359 for the panel job.",
        "claims": ["Winning bid INR 4,663,359"],
        "passages": ["Seven 11kV 630A 25kA AIS panels. Winning bid INR 4,663,359 for the panel job."],
        "published_at": "2026-09-10",
        "obtained_at": "2026-09-10",
    }]
    assert search.has_sufficient_commercial_benchmark(evidence, TARGET, "hv-equipment") is True
    ledger = search.evidence_ledger(evidence)
    assert "Evidence role: PRICE_EVIDENCE + SPEC_EVIDENCE" in ledger
