import search
import app as app_module  # noqa: F401 - importing app installs all runtime policy layers


QUERY = "132/33kV 90MVA power transformer with OLTC price"


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
