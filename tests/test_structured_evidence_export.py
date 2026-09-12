from __future__ import annotations

import threading
from types import SimpleNamespace

from classification_coverage import _install_structured_evidence_export, structured_evidence_records


def _evidence():
    return [
        {
            "source_id": 1,
            "title": "Pepsi Max 3L",
            "url": "https://shop.example/pepsi-max-3l",
            "query": "3 litre Pepsi Max price",
            "passages": ["Pepsi Max 3 L bottle £2.50"],
            "claims": ["Visible retailer price £2.50"],
            "text": "Pepsi Max 3 L bottle. Price £2.50. In stock.",
            "relevance": 4.2,
            "published_at": "2026-09-12",
            "obtained_at": "2026-09-12",
            "content_type": "text/html",
        },
        {
            "source_id": 2,
            "title": "Reference exchange rates",
            "url": "https://fx.example/rates&quotes=GBP,USD",
            "query": "currency conversion",
            "passages": ["Reference rates dated 2026-09-12. 1 GBP ≈ 1.35 USD"],
            "claims": ["1 GBP ≈ 1.35 USD"],
            "text": "1 GBP ≈ 1.35 USD",
            "obtained_at": "2026-09-12",
            "content_type": "application/json",
        },
    ]


def test_structured_evidence_records_preserve_retained_source_text_and_mark_fx():
    fake_search = SimpleNamespace(FX_URL="https://fx.example/rates")

    rows = structured_evidence_records(fake_search, _evidence())

    assert rows[0]["kind"] == "market_source"
    assert rows[0]["title"] == "Pepsi Max 3L"
    assert "£2.50" in rows[0]["text"]
    assert rows[0]["passages"] == ["Pepsi Max 3 L bottle £2.50"]
    assert rows[1]["kind"] == "currency_reference"


def test_completed_job_receives_structured_evidence_and_pricing_summary():
    fake_search = SimpleNamespace()
    fake_search.FX_URL = "https://fx.example/rates"
    fake_search.JOBS = {}
    fake_search.LOCK = threading.Lock()
    fake_search.evidence_ledger = lambda evidence: "ledger"
    fake_search.pricing_category = lambda query: "consumer-retail"
    fake_search.pricing_profile = lambda category: category
    fake_search.pricing_intent = lambda left, right: True
    fake_search.implicit_product_pricing = lambda query: True
    fake_search.has_commercial_price = lambda evidence: bool(evidence)
    fake_search.has_sufficient_commercial_benchmark = lambda evidence, question, category: bool(evidence)
    fake_search.exact_priced_product_candidate = lambda candidate, question, content="": "3 L" in content and "£2.50" in content

    def run(app, job_id, query, history, model, allowed_only, uploaded_context=""):
        fake_search.JOBS[job_id] = {"status": "running"}
        fake_search.evidence_ledger(_evidence())
        fake_search.JOBS[job_id]["status"] = "completed"

    fake_search._run = run

    _install_structured_evidence_export(fake_search)
    fake_search._run(None, "job-1", "3 litre Pepsi Max price", [], None, False, "")

    job = fake_search.JOBS["job-1"]
    assert job["retained_evidence"][0]["url"] == "https://shop.example/pepsi-max-3l"
    assert job["retained_evidence"][0]["benchmark_eligible"] is True
    assert job["retained_evidence"][1]["kind"] == "currency_reference"
    assert job["retained_evidence"][1]["benchmark_eligible"] is False
    assert job["pricing_evidence"]["is_pricing"] is True
    assert job["pricing_evidence"]["commercial_price_found"] is True
    assert job["pricing_evidence"]["retained_market_sources"] == 1
    assert job["pricing_evidence"]["benchmark_eligible_sources"] == 1
