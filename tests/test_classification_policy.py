from types import SimpleNamespace

import search
from classification_coverage import install_classification_coverage_guard
from classification_policy import benchmark_status, classify_query, install_classification_policy


X1_QUERY = "Lenovo ThinkPad X1 Carbon Gen 13 Aura Edition 32GB 1TB price"


def test_x1_carbon_is_consumer_retail_not_general_product():
    category, reason = classify_query(X1_QUERY)
    assert category == "consumer-retail"
    assert "thinkpad" in reason.lower() or "x1 carbon" in reason.lower()


def test_11kv_switchgear_is_hv_equipment():
    category, _ = classify_query("11kV AIS 3000A switchboard, 25kA, 2 incomers 2000A")
    assert category == "hv-equipment"


def test_unknown_item_uses_general_product_catchall():
    category, reason = classify_query("Acme ZXQ-440 widget price")
    assert category == "general-product"
    assert "catch-all" in reason


def test_consumer_threshold_counts_only_priced_product_sources_not_fx_or_technical_pages():
    evidence = [
        {
            "title": "Lenovo ThinkPad X1 Carbon Gen 13 Aura Edition",
            "url": "https://shop.example/x1-carbon",
            "text": "Lenovo ThinkPad X1 Carbon Gen 13 Aura Edition 32GB 1TB. GBP 2,014.88",
            "claims": [], "passages": [],
        },
        {
            "title": "Amazon product information",
            "url": "https://amazon.example/x1-carbon",
            "text": "ThinkPad X1 Carbon Gen 13 technical details; price unavailable",
            "claims": [], "passages": [],
        },
        {
            "title": "Frankfurter dated reference exchange rates",
            "url": "https://api.frankfurter.dev/v2/rates?base=EUR",
            "query": "reference exchange rates",
            "text": "1 EUR = 1.16 USD; 1 EUR = 0.86 GBP",
            "claims": [], "passages": [],
        },
    ]
    status = benchmark_status(search, evidence, X1_QUERY, "consumer-retail")
    assert status["qualifying_priced_sources"] == 1
    assert status["minimum_priced_sources"] == 3
    assert status["sufficient"] is False


def test_independent_domain_requirement_prevents_three_pages_on_one_shop_counting_as_three():
    evidence = [
        {"title": f"X1 listing {i}", "url": f"https://same.example/item-{i}",
         "text": f"Lenovo ThinkPad X1 Carbon Gen 13 Aura Edition 32GB 1TB GBP {2000 + i}",
         "claims": [], "passages": []}
        for i in range(3)
    ]
    status = benchmark_status(search, evidence, X1_QUERY, "consumer-retail")
    assert status["qualifying_priced_sources"] == 1
    assert status["sufficient"] is False


def test_three_independent_matching_prices_satisfy_consumer_default():
    evidence = [
        {"title": f"X1 listing {i}", "url": f"https://shop{i}.example/item",
         "text": f"Lenovo ThinkPad X1 Carbon Gen 13 Aura Edition 32GB 1TB GBP {2000 + i}",
         "claims": [], "passages": []}
        for i in range(3)
    ]
    status = benchmark_status(search, evidence, X1_QUERY, "consumer-retail")
    assert status["qualifying_priced_sources"] == 3
    assert status["sufficient"] is True


def test_editable_hv_threshold_keeps_specialist_scope_validator():
    def has_price(evidence):
        return any("GBP" in str(item.get("text", "")) for item in evidence)

    def old_hv_benchmark(evidence, question, category):
        return any("VALID_LINE_ITEM" in str(item.get("text", "")) for item in evidence)

    fake = SimpleNamespace(
        exact_priced_product_candidate=lambda *args, **kwargs: False,
        has_sufficient_commercial_benchmark=old_hv_benchmark,
        has_commercial_price=has_price,
    )
    install_classification_policy(fake)

    project_total = {"title": "Turnkey project", "url": "https://a.example/project", "text": "GBP 10,000,000 PROJECT_TOTAL"}
    valid_one = {"title": "VCB panel", "url": "https://b.example/panel", "text": "GBP 20,000 VALID_LINE_ITEM"}
    valid_two = {"title": "VCB panel award", "url": "https://c.example/panel", "text": "GBP 21,000 VALID_LINE_ITEM"}

    assert fake.has_sufficient_commercial_benchmark([project_total, valid_one], "11kV switchgear price", "hv-equipment") is False
    assert fake.has_sufficient_commercial_benchmark([project_total, valid_one, valid_two], "11kV switchgear price", "hv-equipment") is True


def test_coverage_guard_overrides_llm_complete_until_threshold_is_met():
    fake = SimpleNamespace()
    fake.assess_coverage = lambda *args, **kwargs: {"complete": True, "covered": ["product"], "gaps": [], "queries": []}
    fake.pricing_category = lambda question: "consumer-retail"
    fake.pricing_request = lambda question: True
    fake.implicit_product_pricing = lambda question: True
    fake.has_commercial_price = lambda evidence: True
    fake.benchmark_status = lambda evidence, question, category=None: {
        "sufficient": False,
        "qualifying_priced_sources": 1,
        "minimum_priced_sources": 3,
        "require_independent_domains": True,
    }
    fake.clean_items = lambda values, limit: list(values)[:limit]
    fake.clean_queries = lambda values: list(dict.fromkeys(values))

    install_classification_coverage_guard(fake)
    result = fake.assess_coverage(None, None, None, X1_QUERY, [], [], [], [{"text": "GBP 2014"}])

    assert result["complete"] is False
    assert "1/3 independent priced sources" in result["gaps"][0]
    assert result["queries"]
