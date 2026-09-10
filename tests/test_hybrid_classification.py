from types import SimpleNamespace

from hybrid_classification import hybrid_classification_report, install_hybrid_classification


POWER_TX = "400/275/33kV 1000MVA auto TX with OLTC price"


def fake_search(response=None, error=None):
    search = SimpleNamespace()
    search.get_settings = lambda: {"ollama_url": "http://ollama.invalid", "model": "test-model"}
    if error is not None:
        def raise_error(*args, **kwargs):
            raise error
        search.ollama_json = raise_error
    else:
        search.ollama_json = lambda *args, **kwargs: dict(response or {})
    return search


def test_high_confidence_semantic_choice_can_override_deterministic_baseline():
    search = fake_search({
        "category": "power-transformers",
        "confidence": 0.94,
        "reason": "The request describes a large autotransformer by voltage ratio, MVA and OLTC.",
    })

    result = hybrid_classification_report(search, POWER_TX)

    assert result["category"] == "power-transformers"
    assert result["method"] == "llm"
    assert result["confidence"] == 0.94
    assert result["search_profile"] == "hv-equipment"
    assert result["min_priced_sources"] == 2


def test_low_confidence_llm_choice_falls_back_to_deterministic_classifier():
    search = fake_search({
        "category": "power-transformers",
        "confidence": 0.41,
        "reason": "Possibly a transformer.",
    })

    result = hybrid_classification_report(search, "Lenovo ThinkPad X1 Carbon Gen 13 price")

    assert result["category"] == "consumer-retail"
    assert result["method"] == "deterministic-fallback"
    assert result["confidence"] == 0.41
    assert "below" in result["reason"].lower()


def test_unknown_llm_category_cannot_escape_configured_registry():
    search = fake_search({
        "category": "made-up-category",
        "confidence": 0.99,
        "reason": "Invented category.",
    })

    result = hybrid_classification_report(search, "Lenovo ThinkPad X1 Carbon Gen 13 price")

    assert result["category"] == "consumer-retail"
    assert result["method"] == "deterministic-fallback"
    assert "unknown or disabled" in result["reason"].lower()


def test_llm_failure_uses_deterministic_classifier():
    search = fake_search(error=RuntimeError("ollama unavailable"))

    result = hybrid_classification_report(search, "132/33kV 90MVA power transformer price")

    assert result["category"] == "power-transformers"
    assert result["method"] == "deterministic-fallback"
    assert result["llm_proposal"]["error"]


def test_runtime_context_locks_selected_category_for_followup_queries():
    events = []
    seen = []
    search = fake_search({
        "category": "power-transformers",
        "confidence": 0.96,
        "reason": "Large power transformer request.",
    })
    search.pricing_category = lambda query: "general-product"
    search.event = lambda *args, **kwargs: events.append((args, kwargs))

    def inner_run(app, job_id, query, history, model, allowed_only, uploaded_context=""):
        seen.append(search.pricing_category(query))
        seen.append(search.pricing_category("tender award price search child query"))
        return "ok"

    search._run = inner_run
    install_hybrid_classification(search)

    result = search._run(None, "job-1", "132/33kV 90MVA power transformer price", [], "test-model", False, "")

    assert result == "ok"
    assert seen == ["power-transformers", "power-transformers"]
    assert search.pricing_category("unrelated query after job") == "general-product"
    assert any("Classification: Power Transformers" in call[0][3] for call in events)
