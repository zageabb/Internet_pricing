from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class IndexPoint:
    date: date
    value: Decimal
    source: str = ""


class CurrentisationError(ValueError):
    pass


def currentise_price(payload: dict[str, Any]) -> dict[str, Any]:
    """Currentise a price range from an evidence-backed index series.

    The function never extrapolates beyond supplied index evidence. If either the
    source or target date falls outside the series, the result is unavailable.
    """

    source_date = _date(payload.get("source_date"), "source_date")
    target_date = _date(payload.get("target_date"), "target_date")
    if target_date < source_date:
        raise CurrentisationError("target_date must be on or after source_date.")

    price = payload.get("price") or {}
    currency = str(price.get("currency") or "USD").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise CurrentisationError("price.currency must be a three-letter currency code.")
    low = _decimal(price.get("low"), "price.low")
    expected = _decimal(price.get("expected"), "price.expected")
    high = _decimal(price.get("high"), "price.high")
    if low < 0 or expected < 0 or high < 0 or not low <= expected <= high:
        raise CurrentisationError("price range must satisfy 0 <= low <= expected <= high.")

    index = payload.get("index") or {}
    name = str(index.get("name") or "").strip()
    if not name:
        raise CurrentisationError("index.name is required.")
    points = _points(index.get("points") or [])
    if len(points) < 2:
        return {
            "status": "unavailable",
            "reason": "At least two dated index points are required.",
            "index_name": name,
        }

    source_index = _interpolated_index(points, source_date)
    target_index = _interpolated_index(points, target_date)
    if source_index is None or target_index is None:
        return {
            "status": "unavailable",
            "reason": "The supplied index does not cover both the source and target dates; extrapolation is disabled.",
            "index_name": name,
            "coverage": {
                "from": points[0].date.isoformat(),
                "to": points[-1].date.isoformat(),
            },
        }
    if source_index <= 0:
        raise CurrentisationError("The source-date index value must be greater than zero.")

    factor = target_index / source_index
    adjusted = {
        "low": str((low * factor).quantize(Decimal("0.000001"))),
        "expected": str((expected * factor).quantize(Decimal("0.000001"))),
        "high": str((high * factor).quantize(Decimal("0.000001"))),
        "currency": currency,
    }
    sources = list(dict.fromkeys(point.source for point in points if point.source))
    return {
        "status": "completed",
        "method": "index_ratio",
        "index_name": name,
        "source_date": source_date.isoformat(),
        "target_date": target_date.isoformat(),
        "source_index": str(source_index.quantize(Decimal("0.000001"))),
        "target_index": str(target_index.quantize(Decimal("0.000001"))),
        "factor": str(factor.quantize(Decimal("0.00000001"))),
        "original_price": {
            "low": str(low),
            "expected": str(expected),
            "high": str(high),
            "currency": currency,
        },
        "adjusted_price": adjusted,
        "sources": sources,
        "audit": {
            "interpolation": "linear_between_neighbouring_index_points",
            "extrapolation": False,
            "point_count": len(points),
            "coverage_from": points[0].date.isoformat(),
            "coverage_to": points[-1].date.isoformat(),
        },
    }


def _points(values) -> list[IndexPoint]:
    points = []
    for row in values:
        if not isinstance(row, dict):
            continue
        try:
            point = IndexPoint(
                date=_date(row.get("date"), "index.points[].date"),
                value=_decimal(row.get("value"), "index.points[].value"),
                source=str(row.get("source") or "")[:1000],
            )
        except CurrentisationError:
            continue
        if point.value <= 0:
            continue
        points.append(point)
    dedup = {}
    for point in points:
        dedup[point.date] = point
    return sorted(dedup.values(), key=lambda item: item.date)


def _interpolated_index(points: list[IndexPoint], target: date) -> Decimal | None:
    if target < points[0].date or target > points[-1].date:
        return None
    for point in points:
        if point.date == target:
            return point.value
    for left, right in zip(points, points[1:]):
        if left.date < target < right.date:
            span = Decimal((right.date - left.date).days)
            offset = Decimal((target - left.date).days)
            return left.value + (right.value - left.value) * (offset / span)
    return None


def _date(value, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError as exc:
        raise CurrentisationError(f"{field} must be an ISO date.") from exc


def _decimal(value, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CurrentisationError(f"{field} must be numeric.") from exc
