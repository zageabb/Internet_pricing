import search
import app as app_module  # noqa: F401 - installs runtime policies
from hybrid_classification import _set_context


PIXEL = "Pixel 11 Fold price"


def _consumer_context():
    return {
        "category": "consumer-retail",
        "label": "Consumer / retail",
        "query": PIXEL,
        "search_profile": "consumer-retail",
    }


def test_pixel_queries_keep_exact_identity_and_drop_alias_substitution():
    _set_context(_consumer_context(), PIXEL)
    try:
        queries = search.pricing_queries(
            PIXEL,
            ["Google Pixel Fold price", "Pixel 11 Fold expected price"],
            "consumer-retail",
        )
    finally:
        _set_context(None)

    joined = "\n".join(queries).lower()
    assert "pixel 11 fold" in joined
    assert "google pixel fold price" not in joined
    assert all("11" in query for query in queries)


def test_consumer_candidate_filter_rejects_related_model_missing_generation_token():
    _set_context(_consumer_context(), PIXEL)
    try:
        candidates = [
            {"title": "Google Pixel Fold deals", "snippet": "Current foldable Pixel phone prices", "url": "https://a.example/fold"},
            {"title": "Pixel 11 Fold retailer listing", "snippet": "Pixel 11 Fold product page", "url": "https://b.example/pixel11"},
        ]
        kept = search.subject_relevant_candidates(candidates, "Google Pixel Fold often referred to as Pixel 11 Fold", "consumer-retail")
    finally:
        _set_context(None)

    assert [item["url"] for item in kept] == ["https://b.example/pixel11"]


def test_consumer_source_review_rejects_alias_page_before_llm_review():
    _set_context(_consumer_context(), PIXEL)
    try:
        verdict, reason, claims = search.analyse_source(
            None, {}, "unused", PIXEL,
            "Google Pixel Fold specifications and price",
            "https://shop.example/pixel-fold",
            "Google Pixel Fold launched previously. Current price GBP 1,499. Technical specifications listed here.",
        )
    finally:
        _set_context(None)

    assert verdict == "unusable"
    assert "PRODUCT_IDENTITY_MISMATCH" in reason
    assert claims == []


def test_zero_evidence_consumer_fallback_does_not_invent_price_launch_or_specs():
    _set_context(_consumer_context(), PIXEL)
    try:
        answer = search.review_answer(
            "missing-job", None, {}, "unused", PIXEL,
            "Google Pixel Fold, often referred to as Pixel 11 Fold",
            [], [],
            "The Pixel 11 Fold launches in October for GBP 1,899 with a 7.6-inch display.",
            "No readable web evidence (knowledge fallback)",
            allow_indicative=False,
        )
    finally:
        _set_context(None)

    lower = answer.lower()
    assert "exact product price not verified" in lower
    assert "pixel 11 fold" in lower
    assert "not" in lower and "substitut" in lower
    assert "1,899" not in answer
    assert "october" not in lower
    assert "7.6" not in answer


def test_consumer_followups_progressively_remove_quotes_without_dropping_identity():
    queries = search.consumer_followup_queries(PIXEL, ['"pixel 11 fold" price'])
    assert queries
    assert all("pixel 11 fold" in query.lower() for query in queries)
    assert any('"' not in query for query in queries)
