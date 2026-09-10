from __future__ import annotations

import re
from urllib.parse import urlparse

import classification_policy


COMMERCIAL_HINTS = (
    "unit price", "unit rate", "per transformer", "each transformer", "line item", "boq",
    "bill of quantities", "winning bid", "award value", "awarded value", "purchase order",
    "commercial offer", "quotation", "shipment", "transaction", "customs", "import", "export",
)
STRONG_TRANSACTION_HOSTS = {"tenderkart.in", "volza.com", "zauba.com"}


def _compact(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _ratings(value: str, unit: str) -> list[str]:
    matches = []
    for amount in re.findall(rf"\b(\d+(?:[.,]\d+)?)\s*{re.escape(unit)}\b", str(value or ""), re.I):
        token = f"{amount.replace(',', '.')}{unit}"
        if token.lower() not in {item.lower() for item in matches}:
            matches.append(token)
    return matches


def _voltage_ratio(value: str) -> str:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*k\s*v\b", str(value or ""), re.I)
    if match:
        return f"{match.group(1)}/{match.group(2)}kV"
    voltages = _ratings(value, "kV")
    return "/".join(item[:-2] for item in voltages[:2]) + "kV" if len(voltages) >= 2 else (voltages[0] if voltages else "")


def power_transformer_queries(question: str, planned=None) -> list[str]:
    base = _compact(question)
    mva = (_ratings(base, "MVA") or [""])[0]
    ratio = _voltage_ratio(base)
    rating = " ".join(item for item in (mva, ratio) if item)
    values = [
        f'"{rating}" power transformer tender award price' if rating else f'"{base}" power transformer tender award price',
        f'"{rating}" power transformer BOQ unit price' if rating else f'"{base}" power transformer BOQ unit price',
        f'"{rating}" power transformer purchase order award value' if rating else f'"{base}" power transformer purchase order award value',
        f'Volza "{rating}" power transformer transaction value' if rating else f'Volza "{base}" transformer transaction value',
        f'TenderKart "{rating}" power transformer award price' if rating else f'TenderKart "{base}" transformer award price',
        f'"{rating}" power transformer quotation commercial offer' if rating else f'"{base}" transformer quotation commercial offer',
        f'"{rating}" power transformer technical data OEM' if rating else f'"{base}" power transformer technical data OEM',
    ]
    for item in planned or []:
        clean = _compact(item)
        if clean and ("transformer" in clean.lower() or (mva and mva.lower() in clean.lower())):
            values.append(clean)
    return list(dict.fromkeys(_compact(value)[:300] for value in values if _compact(value)))


def power_transformer_relaxed_queries(question: str, round_number: int) -> list[str]:
    base = _compact(question)
    mva = (_ratings(base, "MVA") or [""])[0]
    ratio = _voltage_ratio(base)
    if round_number <= 2:
        values = [
            f'"{mva}" power transformer unit price tender' if mva else "power transformer unit price tender",
            f'"{ratio}" power transformer award price' if ratio else "power transformer award price",
            f'"{mva}" transformer import export transaction value' if mva else "power transformer import export transaction value",
            f'power transformer {ratio} quotation price'.strip(),
        ]
    else:
        values = [
            "power transformer tender BOQ price per MVA",
            "power transformer purchase order contract award value",
            "large power transformer import export customs value",
            "power transformer commercial offer quotation price",
        ]
    return list(dict.fromkeys(_compact(value)[:300] for value in values if _compact(value)))


def _transformer_price_evidence(search, item: dict, question: str) -> bool:
    if not search.has_commercial_price([item]):
        return False
    corpus = "\n".join([
        str(item.get("title") or ""), str(item.get("text") or ""),
        "\n".join(map(str, item.get("claims") or [])),
        "\n".join(map(str, item.get("passages") or [])),
    ])
    lower = corpus.lower()
    if "transformer" not in lower and "autotransformer" not in lower:
        return False

    target_mva = _ratings(question, "MVA")
    result_mva = _ratings(corpus, "MVA")
    target_kv = _ratings(question, "kV")
    result_kv = _ratings(corpus, "kV")
    rating_context = bool((target_mva and result_mva) or (target_kv and result_kv))

    line_level = any(hint in lower for hint in COMMERCIAL_HINTS)
    unrelated_scope = sum(1 for token in (
        "civil works", "switchgear", "cable system", "cables", "substation construction",
        "building works", "protection panels", "control building", "complete substation",
    ) if token in lower)
    if unrelated_scope >= 2 and not line_level:
        return False

    host = (urlparse(str(item.get("url") or "")).hostname or "").lower().removeprefix("www.")
    if host in STRONG_TRANSACTION_HOSTS and rating_context:
        return True
    return rating_context and line_level


def install_power_transformer_policy(search) -> None:
    if getattr(search, "_power_transformer_policy_installed", False):
        return

    original_pricing_queries = search.pricing_queries
    original_relaxed_queries = getattr(search, "hv_relaxed_queries", None)
    original_benchmark_status = search.benchmark_status
    original_has_sufficient = search.has_sufficient_commercial_benchmark

    def pricing_queries(query, planned, category=None):
        resolved = category or search.pricing_category(query)
        if resolved == "power-transformers":
            return search.clean_queries(power_transformer_queries(query, planned))
        return original_pricing_queries(query, planned, resolved)

    def hv_relaxed_queries(question, round_number):
        if search.pricing_category(question) == "power-transformers":
            return power_transformer_relaxed_queries(question, round_number)
        if callable(original_relaxed_queries):
            return original_relaxed_queries(question, round_number)
        return []

    def benchmark_status(evidence, question, category=None):
        resolved = category or search.pricing_category(question)
        if resolved != "power-transformers":
            return original_benchmark_status(evidence, question, resolved)
        return classification_policy.benchmark_status(
            search, evidence, question, resolved,
            item_qualifier=lambda item: _transformer_price_evidence(search, item, question),
        )

    def has_sufficient_commercial_benchmark(evidence, question, category):
        if category == "power-transformers":
            return benchmark_status(evidence, question, category)["sufficient"]
        return original_has_sufficient(evidence, question, category)

    search.pricing_queries = pricing_queries
    search.hv_relaxed_queries = hv_relaxed_queries
    search.benchmark_status = benchmark_status
    search.has_sufficient_commercial_benchmark = has_sufficient_commercial_benchmark
    search.power_transformer_queries = power_transformer_queries
    search._power_transformer_policy_installed = True
