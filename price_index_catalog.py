from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from price_currentisation import CurrentisationError, _date, _points


def load_price_index_catalog() -> list[dict[str, Any]]:
    """Load governed evidence-backed index series from JSON env or file.

    No built-in index values are invented. Deployments must provide explicit
    evidence series and source references.
    """
    raw = str(os.environ.get("PRICE_INDEX_CATALOG_JSON") or "").strip()
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return _normalise_catalog(payload)

    filename = str(os.environ.get("PRICE_INDEX_CATALOG_FILE") or "").strip()
    if not filename:
        return []
    try:
        payload = json.loads(Path(filename).read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return _normalise_catalog(payload)


def select_price_index(
    catalog: list[dict[str, Any]],
    *,
    source_date: str | date,
    target_date: str | date,
    equipment_type: str = "",
    category: str = "",
    region: str = "",
) -> dict[str, Any]:
    """Select the best dated series that covers both requested dates."""
    source = _date(source_date, "source_date")
    target = _date(target_date, "target_date")
    if target < source:
        raise CurrentisationError("target_date must be on or after source_date.")

    equipment = _norm(equipment_type)
    category_key = _norm(category)
    region_key = _norm(region)
    candidates = []

    for row in catalog:
        points = _points(row.get("points") or [])
        if len(points) < 2:
            continue
        if source < points[0].date or target > points[-1].date:
            continue

        categories = {_norm(item) for item in row.get("categories") or [] if _norm(item)}
        regions = {_norm(item) for item in row.get("regions") or [] if _norm(item)}
        terms = [_norm(item) for item in row.get("equipment_terms") or [] if _norm(item)]

        score = 0
        reasons = []
        if category_key and category_key in categories:
            score += 6
            reasons.append("category match")
        elif categories and "all" not in categories and "global" not in categories:
            # A governed category list is restrictive when supplied.
            continue

        matched_terms = [term for term in terms if term and term in equipment]
        if matched_terms:
            score += 4 + min(2, len(matched_terms) - 1)
            reasons.append("equipment term match")
        elif terms:
            continue

        if region_key:
            if region_key in regions:
                score += 3
                reasons.append("region match")
            elif regions.intersection({"global", "all", "worldwide"}):
                score += 1
                reasons.append("global region fallback")
            elif regions:
                continue
        elif regions.intersection({"global", "all", "worldwide"}):
            score += 1
            reasons.append("global index")

        # Prefer narrower date coverage when otherwise equivalent: it tends to
        # represent a more purpose-built governed series.
        coverage_days = (points[-1].date - points[0].date).days
        candidates.append((
            -score,
            coverage_days,
            str(row.get("id") or row.get("name") or ""),
            row,
            reasons,
            points,
        ))

    if not candidates:
        return {
            "status": "unavailable",
            "reason": "No configured evidence-backed price index covers the requested dates and context.",
        }

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    neg_score, _coverage, _identifier, selected, reasons, points = candidates[0]
    index = {
        "name": str(selected.get("name") or selected.get("id") or "Price index"),
        "points": [
            {
                "date": point.date.isoformat(),
                "value": str(point.value),
                "source": point.source,
            }
            for point in points
        ],
    }
    return {
        "status": "selected",
        "index_id": str(selected.get("id") or ""),
        "index": index,
        "score": -neg_score,
        "reasons": reasons,
        "coverage": {
            "from": points[0].date.isoformat(),
            "to": points[-1].date.isoformat(),
        },
        "source_references": list(dict.fromkeys(
            point.source for point in points if point.source
        )),
    }


def _normalise_catalog(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("indexes") or []
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload[:100]:
        if not isinstance(item, dict):
            continue
        if not str(item.get("name") or item.get("id") or "").strip():
            continue
        if len(_points(item.get("points") or [])) < 2:
            continue
        rows.append({
            "id": str(item.get("id") or "")[:200],
            "name": str(item.get("name") or item.get("id") or "")[:500],
            "categories": [str(v)[:200] for v in (item.get("categories") or [])[:30]],
            "regions": [str(v)[:200] for v in (item.get("regions") or [])[:30]],
            "equipment_terms": [str(v)[:200] for v in (item.get("equipment_terms") or [])[:50]],
            "points": list(item.get("points") or [])[:1000],
        })
    return rows


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").replace("-", " ").split())
