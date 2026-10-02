import json

from price_index_catalog import select_price_index


CATALOG = [
    {
        "id": "global-industrial",
        "name": "Global industrial equipment",
        "categories": ["industrial equipment", "hv equipment"],
        "regions": ["global"],
        "equipment_terms": ["switchgear", "transformer", "circuit breaker"],
        "points": [
            {"date": "2020-01-01", "value": 90, "source": "global-source"},
            {"date": "2026-12-31", "value": 120, "source": "global-source"},
        ],
    },
    {
        "id": "uk-switchgear",
        "name": "UK switchgear equipment",
        "categories": ["hv equipment"],
        "regions": ["united kingdom"],
        "equipment_terms": ["switchgear"],
        "points": [
            {"date": "2020-01-01", "value": 100, "source": "uk-source-a"},
            {"date": "2026-12-31", "value": 130, "source": "uk-source-b"},
        ],
    },
]


def test_selector_prefers_specific_category_equipment_and_region_match():
    result = select_price_index(
        CATALOG,
        source_date="2022-01-01",
        target_date="2026-10-02",
        equipment_type="11 kV AIS switchgear",
        category="hv-equipment",
        region="United Kingdom",
    )

    assert result["status"] == "selected"
    assert result["index_id"] == "uk-switchgear"
    assert "category match" in result["reasons"]
    assert "equipment term match" in result["reasons"]
    assert "region match" in result["reasons"]
    assert result["source_references"] == ["uk-source-a", "uk-source-b"]


def test_selector_uses_global_region_fallback_when_specific_index_is_not_applicable():
    result = select_price_index(
        CATALOG,
        source_date="2022-01-01",
        target_date="2026-10-02",
        equipment_type="Power transformer",
        category="industrial equipment",
        region="Germany",
    )

    assert result["status"] == "selected"
    assert result["index_id"] == "global-industrial"
    assert "global region fallback" in result["reasons"]


def test_selector_refuses_series_without_required_date_coverage():
    result = select_price_index(
        CATALOG,
        source_date="2018-01-01",
        target_date="2026-10-02",
        equipment_type="Power transformer",
        category="industrial equipment",
        region="Germany",
    )

    assert result["status"] == "unavailable"
    assert "covers the requested dates" in result["reason"]



def test_currentisation_endpoint_automatically_selects_catalog_index(monkeypatch):
    monkeypatch.setenv("PRICE_INDEX_CATALOG_JSON", json.dumps({"indexes": CATALOG}))
    import app as app_module

    client = app_module.app.test_client()
    response = client.post("/api/pricing/currentise", json={
        "source_date": "2022-01-01",
        "target_date": "2026-10-02",
        "equipment_type": "11 kV AIS switchgear",
        "category": "hv-equipment",
        "region": "United Kingdom",
        "price": {"low": 800000, "expected": 1000000, "high": 1200000, "currency": "USD"},
    })

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["status"] == "completed"
    assert result["index_selection"]["status"] == "selected"
    assert result["index_selection"]["index_id"] == "uk-switchgear"
    assert result["index_name"] == "UK switchgear equipment"


def test_currentisation_endpoint_manual_index_overrides_catalog(monkeypatch):
    monkeypatch.setenv("PRICE_INDEX_CATALOG_JSON", json.dumps({"indexes": CATALOG}))
    import app as app_module

    client = app_module.app.test_client()
    response = client.post("/api/pricing/currentise", json={
        "source_date": "2022-01-01",
        "target_date": "2026-10-02",
        "equipment_type": "11 kV AIS switchgear",
        "category": "hv-equipment",
        "region": "United Kingdom",
        "price": {"low": 800000, "expected": 1000000, "high": 1200000, "currency": "USD"},
        "index": {
            "name": "Manual governed index",
            "points": [
                {"date": "2022-01-01", "value": 100, "source": "manual-source"},
                {"date": "2026-10-02", "value": 110, "source": "manual-source"},
            ],
        },
    })

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["status"] == "completed"
    assert result["index_name"] == "Manual governed index"
    assert result["index_selection"]["status"] == "manual_override"
    assert result["sources"] == ["manual-source"]
