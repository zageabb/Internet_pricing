from __future__ import annotations

import re

from research_core import __version__ as research_core_version, best_passages
from research_core.ranking import cosine_similarity


_ORIGINAL_PRICING_QUERIES = None


def _compact(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _rating_tokens(value: str, unit: str) -> list[str]:
    pattern = rf"\b\d+(?:[.,]\d+)?\s*{re.escape(unit)}\b"
    found = []
    for match in re.finditer(pattern, str(value or ""), re.I):
        token = re.sub(r"\s+", "", match.group(0))
        token = token[:-len(unit)] + unit
        if token.lower() not in {item.lower() for item in found}:
            found.append(token)
    return found


def _nearest_current(value: str, words: tuple[str, ...]) -> str:
    text = _compact(value)
    matches = list(re.finditer(r"\b\d+(?:[.,]\d+)?\s*A\b", text, re.I))
    if not matches:
        return ""
    best = None
    lowered = text.lower()
    for match in matches:
        centre = match.start()
        distance = min((abs(centre - lowered.find(word)) for word in words if lowered.find(word) >= 0), default=10_000)
        if best is None or distance < best[0]:
            best = (distance, re.sub(r"\s+", "", match.group(0)))
    return best[1] if best and best[0] < 80 else ""


def _hv_layered_queries(query: str, planned: list[str]) -> list[str]:
    """Create complementary HV searches instead of requiring every rating in every query."""
    base = _compact(query)
    voltages = _rating_tokens(base, "kV")
    faults = _rating_tokens(base, "kA")
    currents = _rating_tokens(base, "A")
    voltage = voltages[0] if voltages else ""
    fault = faults[0] if faults else ""

    lower = base.lower()
    insulation = "GIS" if re.search(r"\bgis\b", lower) else "AIS" if re.search(r"\bais\b", lower) else ""
    equipment = "switchgear" if "switchgear" in lower else "switchboard" if "switchboard" in lower else "switchgear"
    breaker = "VCB panel" if "vcb" in lower or (voltage and float(re.sub(r"[^0-9.]", "", voltage) or 0) <= 36) else "panel"

    incomer_current = _nearest_current(base, ("incomer", "incoming"))
    feeder_current = _nearest_current(base, ("feeder", "outgoing"))
    busbar_current = _nearest_current(base, ("busbar", "bus bar", "main bus"))
    if not busbar_current and currents:
        try:
            busbar_current = max(currents, key=lambda token: float(re.sub(r"[^0-9.]", "", token)))
        except ValueError:
            busbar_current = currents[0]

    identity = " ".join(part for part in (voltage, insulation, equipment, fault) if part)
    queries = []

    def add(value: str):
        value = _compact(value)
        if value and value.lower() not in {item.lower() for item in queries}:
            queries.append(value[:300])

    # Layer 1: broad award/BOQ evidence for the equipment class.
    add(f'"{voltage}" "{fault}" {insulation} {equipment} tender award BOQ unit price' if voltage and fault
        else f"{identity} tender award BOQ unit price")

    # Layer 2: high-current incomer / transaction evidence.
    if incomer_current:
        add(f'"{voltage}" "{incomer_current}" "{fault}" incomer {equipment} import export customs price')

    # Layer 3: feeder/outgoing panel line-item evidence.
    if feeder_current:
        add(f'"{voltage}" "{feeder_current}" "{fault}" feeder {breaker} tender award unit price')

    # Layer 4: technical validation of the busbar/platform rating. This is allowed
    # to be technical-only evidence; the final composer can pair it with price evidence.
    if busbar_current:
        add(f'"{voltage}" "{busbar_current}" busbar {insulation} {equipment} technical data')

    # Layer 5/6: source-focused discovery based on sources that repeatedly expose
    # award/transaction values in difficult HV searches. These are source names,
    # not manufacturer restrictions.
    add(f"TenderKart {voltage} {fault} {breaker} award price")
    add(f"Volza {voltage} {incomer_current or busbar_current} {fault} {equipment} transaction")

    # Preserve genuinely complementary planner searches. Unlike the old logic,
    # they only need meaningful subject/rating overlap; they do not need every
    # original anchor, quantity and rating repeated verbatim.
    base_terms = {term for term in re.findall(r"[a-z0-9][a-z0-9_.-]+", lower)
                  if term not in {"price", "pricing", "cost", "find", "current", "market", "for", "with", "and", "the"}}
    for item in planned:
        item_text = _compact(item)
        item_terms = set(re.findall(r"[a-z0-9][a-z0-9_.-]+", item_text.lower()))
        overlap = len(base_terms & item_terms)
        if overlap >= 2 or (voltage and voltage.lower() in item_text.lower()):
            add(item_text)

    return queries


def install_research_core_pricing() -> None:
    """Adopt shared research mechanics while keeping pricing policy in this application."""
    global _ORIGINAL_PRICING_QUERIES
    import search

    if getattr(search, "_research_core_v02_installed", False):
        return

    search.best_passages = best_passages
    search.cosine_similarity = cosine_similarity
    search.RESEARCH_CORE_VERSION = research_core_version

    if _ORIGINAL_PRICING_QUERIES is None:
        _ORIGINAL_PRICING_QUERIES = search.pricing_queries

    def pricing_queries_with_layers(query, planned, category=None):
        resolved_category = category or search.pricing_category(query)
        if resolved_category == "hv-equipment":
            return search.clean_queries(_hv_layered_queries(query, list(planned or [])))
        return _ORIGINAL_PRICING_QUERIES(query, planned, resolved_category)

    search.pricing_queries = pricing_queries_with_layers
    search._research_core_v02_installed = True
