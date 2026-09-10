from __future__ import annotations

import re
from urllib.parse import urlparse

from research_core import __version__ as research_core_version, best_passages
from research_core.ranking import cosine_similarity


_ORIGINAL_PRICING_QUERIES = None
_ORIGINAL_BROWSER_RENDER_RULE = None
_ORIGINAL_BENCHMARK_CHECK = None
_ORIGINAL_EVIDENCE_LEDGER = None


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


def _context_current(value: str, words: tuple[str, ...]) -> str:
    """Return a current explicitly attached to a named equipment role."""
    text = _compact(value)
    for word in words:
        after = re.search(rf"\b{re.escape(word)}s?\b[^,;:.]{{0,28}}?\b(\d+(?:[.,]\d+)?\s*A)\b", text, re.I)
        if after:
            return re.sub(r"\s+", "", after.group(1))
        before = re.search(rf"\b(\d+(?:[.,]\d+)?\s*A)\b\s+(?:rated\s+)?{re.escape(word)}s?\b", text, re.I)
        if before:
            return re.sub(r"\s+", "", before.group(1))
    return ""


def _item_corpus(item: dict) -> str:
    return "\n".join([
        str(item.get("title") or ""),
        str(item.get("text") or ""),
        "\n".join(map(str, item.get("claims") or [])),
        "\n".join(map(str, item.get("passages") or [])),
    ])


def _voltage_values_kv(value: str) -> list[float]:
    values = []
    for amount, unit in re.findall(r"\b(\d+(?:[.,]\d+)?)\s*(kV|V)\b", str(value or ""), re.I):
        number = float(amount.replace(",", "."))
        values.append(number if unit.lower() == "kv" else number / 1000.0)
    return values


def _evidence_role(browser_fetch, item: dict) -> str:
    corpus = _item_corpus(item)
    lower = corpus.lower()
    roles = []
    if browser_fetch.has_price_signal(corpus):
        roles.append("PRICE_EVIDENCE")
    spec_hits = len(re.findall(r"\b\d+(?:[.,]\d+)?\s*(?:kV|kA|A|MVA|kVA|MW|kW)\b", corpus, re.I))
    if spec_hits >= 2 or any(token in lower for token in ("iec ", "ieee ", "ais", "gis", "busbar", "short-time withstand")):
        roles.append("SPEC_EVIDENCE")
    if not roles and any(token in lower for token in ("supplier", "framework", "manufacturer", "distributor")):
        roles.append("SUPPLIER_EVIDENCE")
    return " + ".join(roles) if roles else "BACKGROUND_EVIDENCE"


def _hv_commercial_benchmark(browser_fetch, item: dict, question: str) -> bool:
    """Reject project totals and wrong voltage classes as sufficient HV price benchmarks."""
    corpus = _item_corpus(item)
    if not browser_fetch.has_price_signal(corpus):
        return False
    lower = corpus.lower()

    target_voltages = _voltage_values_kv(question)
    result_voltages = _voltage_values_kv(corpus)
    if target_voltages and result_voltages and min(target_voltages) >= 3 and max(result_voltages) < 1:
        return False

    normalized = re.sub(r"\s+", "", lower)
    target_ratings = [*_rating_tokens(question, "kV"), *_rating_tokens(question, "kA"), *_rating_tokens(question, "A")]
    rating_hits = sum(1 for token in target_ratings if token.lower() in normalized)
    subject_hit = any(token in lower for token in ("switchgear", "switchboard", "vcb", "panel", "ais", "gis", "disconnector", "isolator"))

    line_level_hints = (
        "unit price", "unit rate", "per panel", "each panel", "line item", "boq", "bill of quantities",
        "winning bid", "commercial offer", "quotation", "shipment", "transaction", "customs", "import", "export",
    )
    line_level = any(token in lower for token in line_level_hints)

    unrelated_project_parts = sum(1 for token in (
        "transformer", "dg set", "diesel generator", "lt panel", "low voltage board", "civil works", "cables",
    ) if token in lower)
    if unrelated_project_parts >= 2 and not line_level:
        return False

    host = (urlparse(str(item.get("url") or "")).hostname or "").lower().removeprefix("www.")
    strong_transaction_hosts = {"tenderkart.in", "volza.com", "zauba.com"}
    if host in strong_transaction_hosts and subject_hit and rating_hits >= 2:
        return True
    return subject_hit and rating_hits >= 2 and line_level


def _hv_layered_queries(query: str, planned: list[str]) -> list[str]:
    """Create one exact HV search plus complementary evidence-layer searches."""
    base = _compact(query)
    equipment_text = re.sub(r"^\s*(?:find\s+)?(?:current\s+)?(?:pricing|price|cost)\s+(?:for\s+)?", "", base, flags=re.I)
    equipment_text = re.sub(r"\bwith\s+earthing\b", "with earth switch", equipment_text, flags=re.I).strip(" ,;:-")

    voltages = _rating_tokens(base, "kV")
    faults = _rating_tokens(base, "kA")
    currents = _rating_tokens(base, "A")
    voltage = voltages[0] if voltages else ""
    fault = faults[0] if faults else ""

    lower = base.lower()
    insulation = "GIS" if re.search(r"\bgis\b", lower) else "AIS" if re.search(r"\bais\b", lower) else ""
    if "disconnector" in lower or "disconnectors" in lower or "isolator" in lower or "isolators" in lower:
        equipment = "disconnector"
    elif "switchgear" in lower:
        equipment = "switchgear"
    elif "switchboard" in lower:
        equipment = "switchboard"
    else:
        equipment = "switchgear"
    breaker = "VCB panel" if "vcb" in lower or (voltage and float(re.sub(r"[^0-9.]", "", voltage) or 0) <= 36 and equipment in {"switchgear", "switchboard"}) else "panel"

    incomer_current = _context_current(base, ("incomer", "incoming"))
    feeder_current = _context_current(base, ("feeder", "outgoing"))
    busbar_current = _context_current(base, ("busbar", "bus bar", "main bus"))
    if not busbar_current and currents and equipment in {"switchgear", "switchboard"}:
        try:
            busbar_current = max(currents, key=lambda token: float(re.sub(r"[^0-9.]", "", token)))
        except ValueError:
            busbar_current = currents[0]

    queries = []

    def add(value: str):
        value = _compact(value)
        if value and value.lower() not in {item.lower() for item in queries}:
            queries.append(value[:300])

    # Preserve one complete exact-description search. The remaining searches are
    # deliberately decomposed so a useful component benchmark is not excluded
    # merely because it does not repeat the entire board configuration.
    add(f"{equipment_text} tender award BOQ price")

    # Retain the established 132 kV -> 145 kV equipment-class alias used for
    # disconnectors/isolators, including the earth-switch terminology.
    if re.search(r"\b132\s*k\s*v\b", base, re.I) and equipment == "disconnector":
        add("132 kV 145 kV disconnector earth switch tender award procurement price")

    if incomer_current:
        add(f'"{voltage}" "{incomer_current}" "{fault}" incomer {equipment} import export customs price')
    if feeder_current:
        add(f'"{voltage}" "{feeder_current}" "{fault}" feeder {breaker} tender award unit price')
    if busbar_current:
        add(f'"{voltage}" "{busbar_current}" busbar {insulation} {equipment} technical data')

    # Source-focused discovery based on sources that repeatedly expose useful
    # tender or transaction values for difficult HV equipment searches.
    add(f"TenderKart {voltage} {fault} {breaker if equipment != 'disconnector' else equipment} award price")
    add(f"Volza {voltage} {incomer_current or busbar_current} {fault} {equipment} transaction")

    base_terms = {term for term in re.findall(r"[a-z0-9][a-z0-9_.-]+", lower)
                  if term not in {"price", "pricing", "cost", "find", "current", "market", "for", "with", "and", "the"}}
    for item in planned:
        item_text = _compact(item)
        item_terms = set(re.findall(r"[a-z0-9][a-z0-9_.-]+", item_text.lower()))
        overlap = len(base_terms & item_terms)
        if overlap >= 2 or (voltage and voltage.lower() in item_text.lower()):
            add(item_text)

    return queries


def _install_hv_browser_rule(search) -> None:
    """Permit bounded rendering for high-value HV evidence pages when light HTML is incomplete."""
    global _ORIGINAL_BROWSER_RENDER_RULE
    import browser_fetch

    if getattr(browser_fetch.should_render_candidate, "_hv_pricing_rule", False):
        return
    if _ORIGINAL_BROWSER_RENDER_RULE is None:
        _ORIGINAL_BROWSER_RENDER_RULE = browser_fetch.should_render_candidate

    def should_render_candidate_with_hv(candidate: dict, page: dict) -> bool:
        query = str(candidate.get("query") or "")
        if search.pricing_category(query) != "hv-equipment":
            return _ORIGINAL_BROWSER_RENDER_RULE(candidate, page)
        if not browser_fetch.browser_fallback_enabled() or browser_fetch.browser_page_limit() <= 0:
            return False
        url = str(candidate.get("url") or "")
        if not search.public_url(url):
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
        if browser_fetch.has_price_signal(corpus):
            return False

        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        strong_hosts = {"tenderkart.in", "volza.com", "zauba.com"}
        commercial_hints = (
            "tender", "award", "boq", "bill of quantities", "quotation", "commercial offer",
            "import", "export", "customs", "transaction", "unit price", "contract value",
        )
        lower_corpus = corpus.lower()
        strong_evidence_candidate = host in strong_hosts or any(hint in lower_corpus for hint in commercial_hints)
        return strong_evidence_candidate and int(candidate.get("rank") or 99) <= 4

    should_render_candidate_with_hv._hv_pricing_rule = True
    browser_fetch.should_render_candidate = should_render_candidate_with_hv


def install_research_core_pricing() -> None:
    """Adopt shared research mechanics while keeping pricing policy in this application."""
    global _ORIGINAL_PRICING_QUERIES, _ORIGINAL_BENCHMARK_CHECK, _ORIGINAL_EVIDENCE_LEDGER
    import browser_fetch
    import search

    if getattr(search, "_research_core_v02_installed", False):
        return

    search.best_passages = best_passages
    search.cosine_similarity = cosine_similarity
    search.RESEARCH_CORE_VERSION = research_core_version

    if _ORIGINAL_PRICING_QUERIES is None:
        _ORIGINAL_PRICING_QUERIES = search.pricing_queries
    if _ORIGINAL_BENCHMARK_CHECK is None:
        _ORIGINAL_BENCHMARK_CHECK = search.has_sufficient_commercial_benchmark
    if _ORIGINAL_EVIDENCE_LEDGER is None:
        _ORIGINAL_EVIDENCE_LEDGER = search.evidence_ledger

    def pricing_queries_with_layers(query, planned, category=None):
        resolved_category = category or search.pricing_category(query)
        if resolved_category == "hv-equipment":
            return search.clean_queries(_hv_layered_queries(query, list(planned or [])))
        return _ORIGINAL_PRICING_QUERIES(query, planned, resolved_category)

    def sufficient_benchmark_with_scope(evidence, question, category):
        if category != "hv-equipment":
            return _ORIGINAL_BENCHMARK_CHECK(evidence, question, category)
        return any(_hv_commercial_benchmark(browser_fetch, item, question) for item in evidence)

    def evidence_ledger_with_roles(evidence):
        ledger = _ORIGINAL_EVIDENCE_LEDGER(evidence)
        blocks = ledger.split("\n\n---\n\n") if ledger else []
        labelled = []
        for index, block in enumerate(blocks):
            role = _evidence_role(browser_fetch, evidence[index]) if index < len(evidence) else "BACKGROUND_EVIDENCE"
            labelled.append(block.replace("Extracted claims:\n", f"Evidence role: {role}\nExtracted claims:\n", 1))
        return "\n\n---\n\n".join(labelled)

    search.pricing_queries = pricing_queries_with_layers
    search.has_sufficient_commercial_benchmark = sufficient_benchmark_with_scope
    search.evidence_ledger = evidence_ledger_with_roles
    _install_hv_browser_rule(search)
    search._research_core_v02_installed = True
