from decimal import Decimal

import pytest

from price_currentisation import CurrentisationError, currentise_price


def request_payload():
    return {
        "source_date": "2022-01-01",
        "target_date": "2026-01-01",
        "price": {
            "low": 800000,
            "expected": 1000000,
            "high": 1200000,
            "currency": "USD",
        },
        "index": {
            "name": "Industrial equipment index",
            "points": [
                {"date": "2022-01-01", "value": 100, "source": "index-source-a"},
                {"date": "2024-01-01", "value": 110, "source": "index-source-a"},
                {"date": "2026-01-01", "value": 125, "source": "index-source-b"},
            ],
        },
    }


def test_currentisation_uses_index_ratio_and_preserves_range():
    result = currentise_price(request_payload())

    assert result["status"] == "completed"
    assert Decimal(result["factor"]) == Decimal("1.25000000")
    assert Decimal(result["adjusted_price"]["expected"]) == Decimal("1250000.000000")
    assert Decimal(result["adjusted_price"]["low"]) == Decimal("1000000.000000")
    assert result["sources"] == ["index-source-a", "index-source-b"]
    assert result["audit"]["extrapolation"] is False


def test_currentisation_interpolates_between_supplied_points():
    payload = request_payload()
    payload["target_date"] = "2025-01-01"

    result = currentise_price(payload)

    assert result["status"] == "completed"
    factor = Decimal(result["factor"])
    assert Decimal("1.17") < factor < Decimal("1.18")


def test_currentisation_refuses_to_extrapolate_beyond_evidence():
    payload = request_payload()
    payload["target_date"] = "2027-01-01"

    result = currentise_price(payload)

    assert result["status"] == "unavailable"
    assert "extrapolation is disabled" in result["reason"]


def test_currentisation_rejects_invalid_range():
    payload = request_payload()
    payload["price"]["low"] = 120
    payload["price"]["expected"] = 100

    with pytest.raises(CurrentisationError, match="low <= expected <= high"):
        currentise_price(payload)
