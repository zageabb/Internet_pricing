from __future__ import annotations

import math
import re
from urllib.parse import urlparse

import classification_policy


COMMERCIAL_HINTS = (
    "unit price", "unit rate", "per transformer", "each transformer", "line item", "boq",
    "bill of quantities", "winning bid", "award value", "awarded value", "purchase order",
    "commercial offer", "quotation", "shipment", "transaction", "customs", "import", "export",
)
UNIT_SCOPE_HINTS = (
    "unit price", "unit rate", "per transformer", "each transformer", "line item",
    "boq", "bill of quantities",
)
STRONG_TRANSACTION_HOSTS = {"tenderkart.in", "volza.com", "zauba.com"}
MAJOR_PRICE_RE = re.compile(
    r"(?P<currency>GBP|USD|EUR|£|€|\$)\s*(?P<amount>\d[\d,.]*)(?:\s*(?P<scale>million|billion|thousand|[kmb]))?|"
    r"(?P<amount2>\d[\d,.]*)(?:\s*(?P<scale2>million|billion|thousand|[kmb]))?\s*(?P<currency2>GBP|USD|EUR)",
    re.I,
)


def _compact(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _ratings(value: str, unit: str) -> list[str]:
    matches = []
    for amount in re.findall(rf"\b(\d+(?:[.,]\d+)?)\s*{re.escape(unit)}\b", str(value or ""), re.I):
        token = f"{amount.replace(',', '.')}{unit}"
        if token.lower() not in {item.lower() for item in matches}:
            matches.append(token)
    return matches


def _numeric_ratings(value: str, unit: str) -> list[float]:
    rows = []
    for amount in re.findall(rf"\b(\d+(?:[.,]\d+)?)\s*{re.escape(unit)}\b", str(value or ""), re.I):
        try:
            number = float(amount.replace(",", "."))
        except ValueError:
            continue
        if number not in rows:
            rows.append(number)
    return rows


def _voltage_values(value: str) -> list[float]:
    text = str(value or "")
    rows = _numeric_ratings(text, "kV")
    # A transformer ratio is commonly written 400/132/33kV, where only the final
    # number carries the unit. Capture every level in that ratio explicitly.
    for match in re.finditer(r"\b(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?){1,3})\s*k\s*v\b", text, re.I):
        for amount in re.split(r"\s*/\s*", match.group(1)):
            try:
                number = float(amount)
            except ValueError:
                continue
            if number not in rows:
                rows.append(number)
    return rows


def _voltage_ratio(value: str) -> str:
    match = re.search(r"\b(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?){1,2})\s*k\s*v\b", str(value or ""), re.I)
    if match:
        return re.sub(r"\s+", "", match.group(1)) + "kV"
    voltages = _voltage_values(value)
    if len(voltages) >= 2:
        return "/".join(f"{number:g}" for number in voltages[:2]) + "kV"
    return f"{voltages[0]:g}kV" if voltages else ""


def _active_target(search, fallback: str) -> str:
    getter = getattr(search, "active_request_query", None)
    if callable(getter):
        value = _compact(getter())
        if value:
            return value
    return _compact(fallback)


def _mva_comparables(target: float) -> tuple[int, int]:
    if target <= 0:
        return 0, 0
    step = 10 if target >= 50 else 5
    low = max(step, int(round((target * 0.67) / step) * step))
    high = max(low + step, int(round((target * 1.33) / step) * step))
    return low, high


def power_transformer_queries(question: str, planned=None) -> list[str]:
    base = _compact(question)
    mva = (_ratings(base, "MVA") or [""])[0]
    ratio = _voltage_ratio(base)
    values = [
        f'"{mva}" "{ratio}" power transformer tender award price' if mva and ratio else f'"{base}" power transformer tender award price',
        f'{mva} {ratio} power transformer BOQ unit price'.strip(),
        f'{mva} power transformer {ratio} purchase order award'.strip(),
        f'TenderKart {mva} {ratio} power transformer award price'.strip(),
        f'Volza {mva} {ratio} power transformer transaction value'.strip(),
    ]
    for item in planned or []:
        clean = _compact(item)
        if clean and "transformer" in clean.lower() and (not mva or mva.lower() in clean.lower()):
            values.append(clean)
            break
    return list(dict.fromkeys(_compact(value)[:300] for value in values if _compact(value)))


def power_transformer_relaxed_queries(question: str, round_number: int) -> list[str]:
    """Progressively broaden discovery while retaining the original target for validation."""
    base = _compact(question)
    mva_values = _numeric_ratings(base, "MVA")
    mva = mva_values[0] if mva_values else 0.0
    ratio = _voltage_ratio(base)
    voltages = _voltage_values(base)
    high_side = f"{voltages[0]:g}kV" if voltages else ""
    low_mva, high_mva = _mva_comparables(mva)

    if round_number <= 2:
        values = [
            f"{mva:g}MVA power transformer tender award price" if mva else "power transformer tender award price",
            f"{ratio} power transformer BOQ unit price" if ratio else "power transformer BOQ unit price",
            f"{mva:g}MVA power transformer purchase order price" if mva else "power transformer purchase order price",
            f"{high_side} power transformer quotation price" if high_side else "large power transformer quotation price",
        ]
    elif round_number == 3:
        values = [
            f"{low_mva}MVA {high_side} power transformer tender price" if low_mva and high_side else "large power transformer tender price",
            f"{high_mva}MVA {high_side} power transformer tender price" if high_mva and high_side else "large power transformer BOQ price",
            f"{mva:g}MVA transformer import export transaction value" if mva else "large power transformer import export transaction value",
            f"{high_side} power transformer contract award value" if high_side else "power transformer contract award value",
        ]
    else:
        values = [
            f"{low_mva}MVA power transformer BOQ price" if low_mva else "large power transformer BOQ unit price",
            f"{high_mva}MVA power transformer purchase order" if high_mva else "large power transformer purchase order price",
            f"{high_side} large power transformer import export customs value" if high_side else "large power transformer import export customs value",
            "large power transformer commercial offer quotation price",
        ]
    return list(dict.fromkeys(_compact(value)[:300] for value in values if _compact(value)))


def _transformer_corpus(item: dict) -> str:
    return "\n".join([
        str(item.get("title") or ""), str(item.get("snippet") or ""), str(item.get("text") or ""),
        "\n".join(map(str, item.get("claims") or [])),
        "\n".join(map(str, item.get("passages") or [])),
    ])


def _voltage_compatible(targets: list[float], results: list[float]) -> tuple[bool, str]:
    if not targets:
        return True, "No target voltage specified"
    if not results:
        return False, "MISSING_VOLTAGE_RATING"
    # For a ratio request, high and low side are both identity-bearing. Tertiary is
    # useful but not mandatory for a commercial comparator unless separately priced.
    required = targets[:2] if len(targets) >= 2 else targets[:1]
    missing = []
    for target in required:
        if not any(abs(result - target) / max(target, 1.0) <= 0.15 for result in results):
            missing.append(target)
    if missing:
        return False, "VOLTAGE_MISMATCH: " + ", ".join(f"{value:g}kV" for value in missing)
    return True, "Voltage rating comparable"


def _mva_compatible(targets: list[float], results: list[float]) -> tuple[bool, str]:
    if not targets:
        return True, "No target MVA specified"
    if not results:
        return False, "MISSING_MVA_RATING"
    target = targets[0]
    nearest = min(results, key=lambda value: abs(value - target))
    relative = abs(nearest - target) / max(target, 1.0)
    if relative > 0.50:
        return False, f"MVA_OUT_OF_RANGE: target {target:g}MVA, source {nearest:g}MVA"
    return True, f"MVA comparable: target {target:g}MVA, source {nearest:g}MVA"


def transformer_relevance_verdict(item: dict, question: str) -> tuple[bool, str, dict]:
    corpus = _transformer_corpus(item)
    lower = corpus.lower()
    if "transformer" not in lower and "autotransformer" not in lower:
        return False, "WRONG_EQUIPMENT_FAMILY", {}

    target_mva = _numeric_ratings(question, "MVA")
    result_mva = _numeric_ratings(corpus, "MVA")
    mva_ok, mva_reason = _mva_compatible(target_mva, result_mva)
    if not mva_ok:
        return False, mva_reason, {"target_mva": target_mva, "result_mva": result_mva}

    target_kv = _voltage_values(question)
    result_kv = _voltage_values(corpus)
    voltage_ok, voltage_reason = _voltage_compatible(target_kv, result_kv)
    if not voltage_ok:
        return False, voltage_reason, {
            "target_mva": target_mva, "result_mva": result_mva,
            "target_kv": target_kv, "result_kv": result_kv,
        }
    return True, f"{mva_reason}; {voltage_reason}", {
        "target_mva": target_mva, "result_mva": result_mva,
        "target_kv": target_kv, "result_kv": result_kv,
    }


def _quantity_hint(corpus: str) -> int:
    values = []
    patterns = (
        r"\b(?:qty|quantity)\s*[:=-]?\s*(\d+)\b",
        r"\b(\d+)\s*(?:x|×)\s*\d+(?:\.\d+)?\s*mva\b",
        r"\b(\d+)\s+(?:power\s+)?transformers?\b",
        r"\b(\d+)\s+(?:nos?\.?|units?)\b[^.]{0,40}\btransformers?\b",
    )
    for pattern in patterns:
        for value in re.findall(pattern, corpus, re.I):
            try:
                values.append(int(value))
            except ValueError:
                pass
    return max(values or [1])


def _major_currency_values(corpus: str) -> list[float]:
    values = []
    multipliers = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000,
                   "b": 1_000_000_000, "billion": 1_000_000_000}
    for match in MAJOR_PRICE_RE.finditer(corpus):
        raw = match.group("amount") or match.group("amount2") or ""
        scale = (match.group("scale") or match.group("scale2") or "").lower()
        try:
            amount = float(raw.replace(",", "")) * multipliers.get(scale, 1)
        except ValueError:
            continue
        values.append(amount)
    return values


def transformer_price_verdict(search, item: dict, question: str) -> tuple[bool, str, dict]:
    if not search.has_commercial_price([item]):
        return False, "NO_PRICE", {}

    relevance_ok, relevance_reason, details = transformer_relevance_verdict(item, question)
    if not relevance_ok:
        return False, relevance_reason, details

    corpus = _transformer_corpus(item)
    lower = corpus.lower()
    line_level = any(hint in lower for hint in COMMERCIAL_HINTS)
    unit_scope = any(hint in lower for hint in UNIT_SCOPE_HINTS)
    host = (urlparse(str(item.get("url") or "")).hostname or "").lower().removeprefix("www.")

    project_scope = any(token in lower for token in (
        "complete substation", "turnkey substation", "epc project", "engineering procurement construction",
    ))
    unrelated_scope = sum(1 for token in (
        "civil works", "switchgear", "cable system", "cables", "substation construction",
        "building works", "protection panels", "control building",
    ) if token in lower)
    if (project_scope or unrelated_scope >= 2) and not unit_scope:
        return False, "PROJECT_TOTAL_NOT_TRANSFORMER_PRICE", details

    quantity = _quantity_hint(corpus)
    details["quantity_hint"] = quantity
    if quantity > 1 and not unit_scope:
        return False, f"MULTI_UNIT_TOTAL_WITHOUT_UNIT_PRICE: quantity {quantity}", details

    if not line_level and host not in STRONG_TRANSACTION_HOSTS:
        return False, "INSUFFICIENT_COMMERCIAL_SCOPE", details

    target_mva = details.get("target_mva") or []
    major_values = _major_currency_values(corpus)
    if target_mva and target_mva[0] >= 50 and major_values and max(major_values) < 25_000:
        return False, f"IMPLAUSIBLE_LPT_PRICE_SCOPE: largest visible major-currency amount {max(major_values):,.0f}", details

    details["commercial_scope"] = "unit/line item" if unit_scope else "transaction/award"
    return True, f"Transformer price passed rating and scope validation ({relevance_reason})", details


def _transformer_price_evidence(search, item: dict, question: str) -> bool:
    return transformer_price_verdict(search, item, question)[0]


def install_power_transformer_policy(search) -> None:
    if getattr(search, "_power_transformer_policy_installed", False):
        return

    original_pricing_queries = search.pricing_queries
    original_relaxed_queries = getattr(search, "hv_relaxed_queries", None)
    original_benchmark_status = search.benchmark_status
    original_has_sufficient = search.has_sufficient_commercial_benchmark
    original_analyse_source = search.analyse_source

    def pricing_queries(query, planned, category=None):
        resolved = category or search.pricing_category(query)
        if resolved == "power-transformers":
            target = _active_target(search, query)
            return search.clean_queries(power_transformer_queries(target, planned))
        return original_pricing_queries(query, planned, resolved)

    def hv_relaxed_queries(question, round_number):
        if search.pricing_category(question) == "power-transformers":
            target = _active_target(search, question)
            return power_transformer_relaxed_queries(target, round_number)
        if callable(original_relaxed_queries):
            return original_relaxed_queries(question, round_number)
        return []

    def benchmark_status(evidence, question, category=None):
        resolved = category or search.pricing_category(question)
        if resolved != "power-transformers":
            return original_benchmark_status(evidence, question, resolved)
        target = _active_target(search, question)
        return classification_policy.benchmark_status(
            search, evidence, target, resolved,
            item_qualifier=lambda item: _transformer_price_evidence(search, item, target),
        )

    def has_sufficient_commercial_benchmark(evidence, question, category):
        if category == "power-transformers":
            return benchmark_status(evidence, question, category)["sufficient"]
        return original_has_sufficient(evidence, question, category)

    def analyse_source(prompts, settings, model, query, title, url, content):
        if search.pricing_category(query) != "power-transformers":
            return original_analyse_source(prompts, settings, model, query, title, url, content)
        target = _active_target(search, query)
        item = {"title": title, "url": url, "text": content, "claims": [], "passages": []}
        relevant, reason, _details = transformer_relevance_verdict(item, target)
        if not relevant:
            return "unusable", f"TRANSFORMER_RELEVANCE_REJECTED: {reason}", []
        if search.has_commercial_price([item]):
            valid_price, price_reason, _details = transformer_price_verdict(search, item, target)
            if not valid_price:
                return "unusable", f"TRANSFORMER_PRICE_REJECTED: {price_reason}", []
            claims = search.best_passages(
                content, f"{target} transformer unit price award BOQ purchase order transaction quotation",
                limit=4, max_chars=2200,
            )
            return "useful", price_reason, claims
        return original_analyse_source(prompts, settings, model, target, title, url, content)

    search.pricing_queries = pricing_queries
    search.hv_relaxed_queries = hv_relaxed_queries
    search.benchmark_status = benchmark_status
    search.has_sufficient_commercial_benchmark = has_sufficient_commercial_benchmark
    search.analyse_source = analyse_source
    search.power_transformer_queries = power_transformer_queries
    search.power_transformer_relaxed_queries = power_transformer_relaxed_queries
    search.power_transformer_relevance_verdict = transformer_relevance_verdict
    search.power_transformer_price_verdict = lambda item, question="": transformer_price_verdict(
        search, item, _active_target(search, question)
    )
    search._power_transformer_policy_installed = True
