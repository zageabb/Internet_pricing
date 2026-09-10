from __future__ import annotations

import math
import re
from urllib.parse import urlparse


EVIDENCE_SOURCE_TERMS = {
    "award", "awarded", "tender", "procurement", "boq", "invoice", "quotation", "quote",
    "commercial", "offer", "contract", "framework", "schedule", "rates", "rate", "customs",
    "import", "export", "transaction", "purchase", "order", "unit", "price", "value",
}
PRICE_SIGNAL_RE = re.compile(
    r"(?:GBP|USD|EUR|JPY|INR|CNY|AUD|CAD|CHF|BDT|NPR|NGN|£|€|\$|₹|¥|৳)\s*"
    r"\d[\d,.]*(?:\s*(?:million|billion|thousand|[kmb]))?|"
    r"\d[\d,.]*(?:\s*(?:million|billion|thousand|[kmb]))?\s*"
    r"(?:GBP|USD|EUR|JPY|INR|CNY|AUD|CAD|CHF|BDT|NPR|NGN)",
    re.I,
)
PROJECT_SCOPE_TERMS = {
    "substation", "transformer", "transformers", "cable", "cables", "civil", "civils", "building",
    "buildings", "dg", "generator", "generators", "installation", "erection", "commissioning",
}
EQUIPMENT_SCOPE_TERMS = {
    "panel", "panels", "switchgear", "switchboard", "incomer", "incomers", "feeder", "feeders",
    "busbar", "bus-coupler", "coupler", "cubicle", "cubicles", "vcb",
}


def _clean(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalise_units(value: str) -> str:
    value = _clean(value)
    return re.sub(r"(?<=\d)\s+(?=(?:kV|kA|A|MVA|kVA|MW|kW|GB|TB)\b)", "", value, flags=re.I)


def _first(pattern: str, value: str) -> str:
    match = re.search(pattern, value, re.I)
    return _clean(match.group(1)) if match else ""


def _all_currents(value: str) -> list[str]:
    values = []
    for amount in re.findall(r"\b(\d{2,5})\s*A\b", value, re.I):
        token = f"{amount}A"
        if token not in values:
            values.append(token)
    return values


def _component_current(value: str, component: str) -> str:
    patterns = [
        rf"\b(\d{{2,5}})\s*A\b[^\n,;]{{0,30}}\b{component}s?\b",
        rf"\b{component}s?\b[^\n,;]{{0,30}}\b(\d{{2,5}})\s*A\b",
    ]
    for pattern in patterns:
        found = _first(pattern, value)
        if found:
            return f"{found}A"
    return ""


def _base_hv_description(query: str) -> str:
    base = _clean(query)
    base = re.sub(r"\bpricing\s+for\b", "", base, flags=re.I).strip()
    base = re.sub(r"\b(?:price|pricing|cost)\s*$", "", base, flags=re.I).strip(" ,;:-")
    base = re.sub(r"\bwith\s+earthing\b", "with earth switch", base, flags=re.I)
    return _normalise_units(base)


def _dedupe(values: list[str], limit: int = 12) -> list[str]:
    result = []
    seen = set()
    for value in values:
        value = _clean(value)[:300]
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
        if len(result) >= limit:
            break
    return result


def layered_pricing_queries(search_module, query, planned, category=None):
    """Generate layered pricing searches; HV requests are decomposed into price and spec components."""
    category = category or search_module.pricing_category(query)
    if category != "hv-equipment":
        return _legacy_pricing_queries(search_module, query, planned, category)

    base = _base_hv_description(query)
    voltage = _first(r"\b(\d+(?:[.,]\d+)?)\s*k\s*V\b", base)
    fault = _first(r"\b(\d+(?:[.,]\d+)?)\s*k\s*A\b", base)
    voltage_token = f"{voltage}kV" if voltage else ""
    fault_token = f"{fault}kA" if fault else ""
    ais = "AIS" if re.search(r"\bAIS\b|air[- ]insulated", base, re.I) else ""

    incomer_current = _component_current(base, "incomer")
    feeder_current = _component_current(base, "feeder")
    busbar_current = _component_current(base, "busbar")
    if not busbar_current:
        busbar_current = _first(r"\b(\d{2,5})\s*A\b[^\n,;]{0,25}\bbusbar\b", base)
        busbar_current = f"{busbar_current}A" if busbar_current else ""

    currents = _all_currents(base)
    if not incomer_current and currents:
        incomer_current = next((item for item in currents if item != busbar_current), "")
    if not feeder_current and len(currents) > 1:
        feeder_current = currents[-1]
    if not busbar_current and currents:
        busbar_current = currents[0]

    common = " ".join(item for item in (voltage_token, ais, fault_token) if item)
    exact = f'{base} tender award BOQ price'
    queries = [exact]

    if feeder_current:
        queries.append(f'{common} {feeder_current} VCB feeder panel tender award BOQ unit price')
    if incomer_current:
        queries.append(f'{common} {incomer_current} incomer switchgear invoice customs import export transaction value')
    if busbar_current:
        queries.append(f'{common} {busbar_current} busbar switchgear commercial offer quotation')

    queries.append(f'{common} switchgear schedule of rates purchase order contract award')
    queries.append(f'{common} switchgear IEC 62271-200 technical data')

    # Planner searches are useful when they explore a different evidence role. Do not
    # require them to repeat every rating from the original request.
    base_terms = search_module.terms(base)
    for item in planned or []:
        item_terms = search_module.terms(item)
        subject_overlap = len(base_terms & item_terms)
        evidence_overlap = bool(item_terms & EVIDENCE_SOURCE_TERMS)
        if subject_overlap >= 2 or (subject_overlap >= 1 and evidence_overlap):
            queries.append(item)

    return _dedupe(queries, 12)


def _legacy_pricing_queries(search_module, query, planned, category):
    base = _clean(query)
    equipment = re.sub(r"\bpricing\s+for\b", "", base, flags=re.I).strip()
    equipment = re.sub(r"\b(?:price|pricing|cost)\s*$", "", equipment, flags=re.I).strip(" ,;:-")
    equipment = re.sub(r"\bwith\s+earthing\b", "with earth switch", equipment, flags=re.I)
    normalized = _normalise_units(equipment)
    if category == "industrial":
        additions = [f"{equipment} manufacturer distributor price", f"{equipment} catalogue price pdf",
                     f"{equipment} quotation tender award"]
    elif category == "service-project":
        additions = [f"{equipment} schedule of rates", f"{equipment} labour day rate price",
                     f"{equipment} tender contract award value"]
    elif category == "consumer-retail":
        additions = [f"{normalized} price", f"{normalized} supermarket price", f'"{normalized}" retailer price']
    else:
        additions = [f"{normalized} price", f"{normalized} supplier distributor", f"{normalized} catalogue price"]

    anchors = {term for term in search_module.terms(normalized) if term not in {"price", "pricing", "cost"}}
    kept = [item for item in planned or [] if len(anchors & search_module.terms(item)) >= max(1, min(2, len(anchors)))]
    return _dedupe(additions + kept, 12)


def evidence_candidate_bonus(search_module, candidate, category: str) -> float:
    """Boost candidate pages that look like actual commercial evidence before the fetch shortlist is cut."""
    if category not in {"hv-equipment", "industrial", "service-project"}:
        return 0.0
    text = f"{candidate.get('title', '')} {candidate.get('snippet', '')}".lower()
    terms = search_module.terms(text)
    bonus = 0.0
    if PRICE_SIGNAL_RE.search(text):
        bonus += 2.5
    bonus += min(2.0, len(terms & EVIDENCE_SOURCE_TERMS) * 0.35)
    host = search_module.hostname(candidate.get("url", ""))
    if any(token in host for token in ("tender", "procure", "volza", "zauba", "etender")):
        bonus += 1.0
    path = urlparse(candidate.get("url", "")).path.lower()
    if path.endswith(".pdf") or "download" in path or "document" in path:
        bonus += 0.5
    return bonus


def evidence_aware_rank(search_module, original_rank, candidates, question, requirements=None, subquestions=None,
                        category="general-product"):
    ranked = original_rank(candidates, question, requirements, subquestions, category)
    rescored = []
    for item in ranked:
        item = dict(item)
        item["score"] = round(float(item.get("score") or 0.0) + evidence_candidate_bonus(search_module, item, category), 3)
        rescored.append(item)
    rescored.sort(key=lambda item: (-item["score"], item.get("title", "").lower()))
    return search_module.diversify(rescored)


def _evidence_text(item) -> str:
    return " ".join([
        str(item.get("title", "")), str(item.get("text", "")),
        " ".join(map(str, item.get("claims", []))), " ".join(map(str, item.get("passages", []))),
    ])


def classify_price_scope(text: str) -> str:
    """Coarsely classify whether a commercial value is equipment-level or whole-project scope."""
    terms = {word.lower() for word in re.findall(r"[a-z][a-z-]{2,}", str(text or ""), re.I)}
    project_hits = len(terms & PROJECT_SCOPE_TERMS)
    equipment_hits = len(terms & EQUIPMENT_SCOPE_TERMS)
    unit_language = bool(re.search(r"\b(?:per\s+(?:panel|unit|cubicle)|unit\s+(?:price|rate)|each|qty|quantity|boq)\b", text, re.I))
    if unit_language or equipment_hits >= 2 and project_hits <= 1:
        return "equipment"
    if project_hits >= 3 and project_hits > equipment_hits:
        return "project"
    return "unknown"


def has_sufficient_benchmark(search_module, evidence, question, category):
    """Require comparable/scope-usable commercial evidence before ending specialist research."""
    if not search_module.has_commercial_price(evidence):
        return False
    if category == "consumer-retail":
        return any(search_module.exact_priced_product_candidate(item, question, item.get("text", "")) for item in evidence)
    if category not in {"hv-equipment", "industrial", "service-project"}:
        return True

    question_terms = search_module.terms(question)
    subject_terms = question_terms - EVIDENCE_SOURCE_TERMS - {"current", "global", "market", "find", "pricing"}
    price_records = []
    spec_records = []
    for item in evidence:
        text = _evidence_text(item)
        item_terms = search_module.terms(text)
        overlap = len(subject_terms & item_terms)
        has_price = bool(PRICE_SIGNAL_RE.search(text))
        scope = classify_price_scope(text)
        if has_price and overlap >= 2 and scope != "project":
            price_records.append(item)
        if overlap >= 2 and re.search(r"\b\d+(?:[.,]\d+)?\s*(?:kV|kA|A|MVA|kVA|MW|kW)\b", text, re.I):
            spec_records.append(item)

    # A single source may legitimately provide both roles; otherwise require a
    # priced comparator plus separate technical context before stopping early.
    return bool(price_records and spec_records)


def should_render_specialist_candidate(search_module, original_should_render, candidate, page):
    """Allow bounded Chromium rendering for promising specialist pages when light fetch is thin or price-free."""
    query = str(candidate.get("query") or "")
    category = search_module.pricing_category(query)
    if category not in {"hv-equipment", "service-project"}:
        return original_should_render(candidate, page)

    if not str(candidate.get("url") or "").startswith(("http://", "https://")):
        return False
    content_type = str(page.get("content_type") or "").lower()
    if "pdf" in content_type or "+rendered" in content_type:
        return False
    if str(page.get("error") or "").startswith("Blocked non-public"):
        return False

    title = str(candidate.get("title") or "")
    snippet = str(candidate.get("snippet") or "")
    page_text = str(page.get("text") or "")
    corpus = f"{title} {snippet} {page_text}"
    if PRICE_SIGNAL_RE.search(corpus):
        return False

    candidate_terms = search_module.terms(f"{title} {snippet}")
    evidence_hint = bool(candidate_terms & EVIDENCE_SOURCE_TERMS)
    thin_page = len(page_text.strip()) < 1200
    top_ranked = int(candidate.get("rank") or 99) <= 3
    return evidence_hint and (thin_page or top_ranked)
