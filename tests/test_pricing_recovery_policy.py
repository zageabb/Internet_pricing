from __future__ import annotations

import search
from pricing_recovery_policy import (
    _deterministic_hv_price_evidence,
    _needs_indicative_budget,
    hv_price_recovery_queries,
    install_pricing_recovery_policy,
)
from pricing_runtime import install_hv_runtime
from research_core_adapter import install_research_core_pricing


QUESTION = "11kV AIS 3000A switchboard, 25kA, 2 incomers 2000A, 8 x feeders 630A"


def setup_module():
    install_research_core_pricing()
    install_hv_runtime(search)
    install_pricing_recovery_policy(search)


def test_price_recovery_queries_prioritise_commercial_sources_and_components():
    queries = hv_price_recovery_queries(QUESTION)

    assert any("TenderKart" in item and "630A" in item and "25kA" in item for item in queries)
    assert any("Volza" in item and "2000A" in item and "25kA" in item for item in queries)
    assert any("BOQ" in item and "unit price" in item for item in queries)
    assert any("import export customs price" in item for item in queries)


def test_obvious_hv_tender_price_is_retained_without_llm_source_judgement():
    query = '"11kV" "630A" VCB panel BOQ winning bid unit price'
    content = (
        "11kV indoor AIS VCB feeder panel, 630A, 25kA. Bill of quantities line item. "
        "Quantity 3 outgoing panels. Winning bid INR 1,207,629; unit price INR 402,543 per panel."
    )

    useful, claims = _deterministic_hv_price_evidence(
        search,
        query,
        "11kV VCB feeder panel tender award",
        "https://tenderkart.in/example-11kv-switchgear",
        content,
    )

    assert useful is True
    assert claims


def test_whole_project_total_is_not_deterministically_promoted_as_switchgear_price():
    query = '"11kV" switchgear tender price'
    content = (
        "11kV switchgear included in substation project. Total contract value INR 969,000,000. "
        "Project also includes transformer, diesel generator, cables and civil works."
    )

    useful, claims = _deterministic_hv_price_evidence(
        search,
        query,
        "Substation turnkey project contract award",
        "https://example.com/substation-project",
        content,
    )

    assert useful is False
    assert claims == []


def test_fx_is_not_added_to_technical_only_evidence():
    evidence = [{
        "title": "11kV switchgear technical specification",
        "text": "11kV AIS switchgear rated 2000A and 25kA. No commercial price is disclosed.",
        "claims": [],
        "passages": [],
    }]

    assert search.currency_conversion_evidence(evidence) is None


def test_missing_headline_price_requires_model_fallback_budget():
    technical_only_answer = (
        "The sources confirm an 11kV 2000A 25kA switchgear configuration, "
        "but no publicly available price was found."
    )
    assert _needs_indicative_budget(technical_only_answer) is True


def test_existing_explicit_model_fallback_is_not_duplicated():
    answer = (
        "## Indicative budget — NOT WEB-VERIFIED\n"
        "Low USD 80,000 / Base USD 110,000 / High USD 150,000."
    )
    assert _needs_indicative_budget(answer) is False
