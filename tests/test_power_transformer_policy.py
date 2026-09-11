import search
import app as app_module  # noqa: F401 - importing app installs all runtime policy layers


QUERY = "132/33kV 90MVA power transformer with OLTC price"
LARGE_QUERY = "150MVA 400/132kV power transformer price"


def _evidence(url, price, extra=""):
    return {
        "title": "90MVA 132/33kV power transformer tender award",
        "url": url,
        "query": QUERY,
        "text": f"90MVA 132/33kV power transformer line item unit price USD {price}. {extra}",
        "claims": [f"Unit price USD {price}"],
        "passages": [f"90MVA 132/33kV power transformer line item unit price USD {price}."],
    }


def test_installed_classifier_routes_power_transformer_to_hv_profile():
    category = search.pricing_category(QUERY)
    assert category == "power-transformers"
    assert search.pricing_profile(category) == "hv-equipment"


def test_installed_power_transformer_queries_do_not_use_switchgear_templates():
    queries = search.pricing_queries(QUERY, [], "power-transformers")
    joined = "\n".join(queries)
    assert "power transformer" in joined.lower()
    assert "90MVA" in joined
    assert "132/33kV" in joined
    assert "switchgear" not in joined.lower()


def test_power_transformer_benchmark_requires_two_independent_qualifying_prices():
    first = _evidence("https://award-one.example/transformer", "1200000")
    second = _evidence("https://award-two.example/transformer", "1280000")
    assert search.has_sufficient_commercial_benchmark([first], QUERY, "power-transformers") is False
    assert search.has_sufficient_commercial_benchmark([first, second], QUERY, "power-transformers") is True


def test_complete_project_total_does_not_count_as_transformer_benchmark():
    project = {
        "title": "Complete substation EPC award",
        "url": "https://epc.example/award",
        "query": QUERY,
        "text": "90MVA 132/33kV transformer, switchgear, cables, civil works and control building. Total EPC project value USD 18,000,000.",
        "claims": [],
        "passages": [],
    }
    valid = _evidence("https://award.example/transformer", "1250000")
    assert search.has_sufficient_commercial_benchmark([project, valid], QUERY, "power-transformers") is False


def test_generic_defence_transformer_award_with_9200_value_is_rejected_before_benchmarking():
    defence = {
        "title": "Defence procurement transformer award",
        "url": "https://defence.example/award",
        "text": "Supply of transformers to defence facility. Award value USD 9,200.",
        "claims": [],
        "passages": [],
    }
    ok, reason, _details = search.power_transformer_price_verdict(defence, LARGE_QUERY)
    assert ok is False
    assert "MISSING_MVA_RATING" in reason


def test_wrong_rating_transformer_price_is_rejected_even_when_it_has_mva_and_voltage():
    wrong = {
        "title": "Distribution transformer purchase order",
        "url": "https://award.example/small-transformer",
        "text": "20MVA 33/11kV power transformer unit price USD 390,000.",
        "claims": [],
        "passages": [],
    }
    ok, reason, _details = search.power_transformer_price_verdict(wrong, LARGE_QUERY)
    assert ok is False
    assert "MVA_OUT_OF_RANGE" in reason or "VOLTAGE_MISMATCH" in reason


def test_comparable_large_transformer_line_item_is_accepted():
    valid = {
        "title": "150MVA 400/132kV transformer BOQ",
        "url": "https://award.example/large-transformer",
        "text": "150MVA 400/132kV power transformer BOQ line item unit price USD 4,800,000 per transformer.",
        "claims": [],
        "passages": [],
    }
    ok, reason, details = search.power_transformer_price_verdict(valid, LARGE_QUERY)
    assert ok is True
    assert "passed rating and scope validation" in reason
    assert details["target_mva"] == [150.0]
    assert 400.0 in details["result_kv"] and 132.0 in details["result_kv"]


def test_large_transformer_tiny_major_currency_price_is_rejected_as_wrong_scope():
    suspicious = {
        "title": "150MVA 400/132kV transformer award",
        "url": "https://award.example/suspicious",
        "text": "150MVA 400/132kV power transformer purchase order award value USD 9,200 per transformer.",
        "claims": [],
        "passages": [],
    }
    ok, reason, _details = search.power_transformer_price_verdict(suspicious, LARGE_QUERY)
    assert ok is False
    assert "IMPLAUSIBLE_LPT_PRICE_SCOPE" in reason


def test_transformer_relaxed_queries_broaden_beyond_exact_quoted_rating():
    round_three = search.power_transformer_relaxed_queries(LARGE_QUERY, 3)
    joined = "\n".join(round_three)
    assert '"150MVA 400/132kV"' not in joined
    assert "100MVA" in joined or "200MVA" in joined
    assert "power transformer" in joined.lower()
