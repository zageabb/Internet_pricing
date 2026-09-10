from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
RULES_FILE = ROOT / "classification_rules.json"
LOCK = threading.Lock()
FALLBACK_CATEGORY = "general-product"
RULES_VERSION = 3
SEARCH_PROFILES = ("general-product", "consumer-retail", "industrial", "service-project", "hv-equipment")


def _default_rule(label, order, search_profile, keywords=None, phrases=None, patterns=None,
                  min_priced_sources=2, strategy="", evidence_notes="", stopping_notes="",
                  fallback_notes="", future_notes="", enabled=True):
    return {
        "label": label,
        "enabled": enabled,
        "order": order,
        "search_profile": search_profile,
        "keywords": list(keywords or []),
        "phrases": list(phrases or []),
        "patterns": list(patterns or []),
        "min_priced_sources": min_priced_sources,
        "require_independent_domains": True,
        "strategy": strategy,
        "evidence_notes": evidence_notes,
        "stopping_notes": stopping_notes,
        "fallback_notes": fallback_notes,
        "future_notes": future_notes,
    }


DEFAULT_RULES = {
    "version": RULES_VERSION,
    "categories": {
        "power-transformers": _default_rule(
            "Power Transformers", 5, "hv-equipment",
            keywords=["autotransformer", "gsu"],
            phrases=[
                "power transformer", "grid transformer", "generator step-up transformer",
                "generator step up transformer", "gsu transformer", "step-up transformer",
                "step up transformer", "step-down transformer", "step down transformer",
                "large power transformer",
            ],
            patterns=[
                r"\b\d+(?:[.,]\d+)?\s*mva\b.{0,100}\btransformer\b",
                r"\btransformer\b.{0,100}\b\d+(?:[.,]\d+)?\s*mva\b",
            ],
            min_priced_sources=2,
            strategy="Prioritise power-transformer tender awards, BOQs, purchase orders, framework values, OEM technical data and import/export transactions. Compare MVA rating, HV/LV voltage ratio, phases, frequency, impedance, vector group, cooling class, tap changer/OLTC, losses, accessories and supply-versus-installed scope before normalising prices.",
            evidence_notes="Prefer transformer-level or line-item prices tied to MVA and voltage ratio. Technical-only OEM sources validate comparability but do not count toward the priced-source threshold. Treat transport, oil, bushings, radiators, fans/pumps, OLTC, marshalling kiosk, protection/control, installation and commissioning as separable scope where possible.",
            stopping_notes="Require at least two independent qualifying priced transformer benchmarks by default. Do not let a complete substation/EPC project total count as a transformer price unless the transformer line item is separately identifiable.",
            fallback_notes="Use web-backed transformer pricing first. Model knowledge may supplement accessory/package allowances and explain typical price drivers; a model-only headline transformer price remains the final fallback and must be clearly labelled.",
            future_notes="Future structured fields: MVA, HV/LV/tertiary voltages, vector group, impedance, ONAN/ONAF/ODAF cooling, OLTC range/steps, no-load/load losses, BIL/insulation levels, noise, oil type, transport mass, accessories, spares, installation, testing and commissioning.",
        ),
        "hv-equipment": _default_rule(
            "HV equipment", 10, "hv-equipment",
            keywords=["switchgear", "transformer", "disconnector", "isolator", "substation", "circuit-breaker", "breaker", "busbar", "bushing", "arrester", "earthing", "relay", "protection", "gis", "ais", "vcb"],
            phrases=["vacuum circuit breaker", "medium voltage switchgear", "mv switchgear", "metal clad switchgear", "metal-clad switchgear", "ring main unit"],
            patterns=[r"\b\d+(?:\.\d+)?\s*k\s*v\b"],
            min_priced_sources=2,
            strategy="Prioritise utility procurement, awards, frameworks, BOQs, transaction/import-export evidence and cost schedules; compare voltage class, ratings, configuration and supply-versus-installed scope.",
            evidence_notes="Prefer line-item or equipment-level prices. Technical-only sources can validate comparability but do not count toward the priced-source stopping threshold.",
            stopping_notes="Do not stop merely because technical evidence is strong. Continue until the priced-source threshold is met or the configured research/page limits are exhausted.",
            fallback_notes="Web pricing is primary. Model knowledge may supplement accessories/package allowances; a model-based headline equipment price is final fallback only.",
            future_notes="Good home for future voltage-class mappings, equipment-family aliases, rating tolerances and category-specific source weighting.",
        ),
        "service-project": _default_rule(
            "Service / project", 20, "service-project",
            keywords=["service", "services", "installation", "install", "maintenance", "repair", "consultancy", "consulting", "commissioning", "construction", "labour", "labor", "hire", "rental"],
            phrases=["day rate", "labour rate", "labor rate", "installed cost"],
            min_priced_sources=2,
            strategy="Prioritise schedules of rates, labour/day rates, tender awards and installed project costs; compare geography, quantities and inclusions.",
            evidence_notes="Prefer rate cards, schedules of rates, contract awards and clearly scoped installed-project values.",
            stopping_notes="Seek more than one independent commercial benchmark where possible because labour and project scope vary materially by region and inclusion.",
            fallback_notes="Use model knowledge only to explain typical cost structure or allowances when the web evidence is incomplete; label it separately.",
            future_notes="Future sections could hold geography rules, labour categories, mobilisation, travel and installed-scope normalization.",
        ),
        "consumer-retail": _default_rule(
            "Consumer / retail", 30, "consumer-retail",
            keywords=["laptop", "monitor", "computer", "desktop", "phone", "smartphone", "tablet", "printer", "television", "camera", "headphone", "headphones", "keyboard", "mouse", "router", "watch", "bottle", "bottles", "can", "cans", "pack", "drink", "drinks", "beverage", "beverages", "cola", "soda", "grocery", "groceries", "food", "snack", "snacks", "litre", "litres", "liter", "liters", "notebook", "ultrabook", "thinkpad", "thinkbook", "macbook", "chromebook", "latitude", "elitebook", "probook", "zenbook", "vivobook", "ideapad", "surface"],
            phrases=["x1 carbon", "thinkpad x1 carbon", "macbook air", "macbook pro", "surface laptop", "surface pro", "dell latitude", "hp elitebook", "hp probook", "lenovo thinkbook", "lenovo ideapad", "lenovo yoga", "asus zenbook", "asus vivobook"],
            min_priced_sources=3,
            strategy="Prioritise exact model/specification retailer listings and visible current prices; reject generic category pages and different models. Seek multiple independent priced listings before declaring a market benchmark.",
            evidence_notes="Count only matching product/model/specification listings with a visible usable price. Currency-only sources never count as priced products.",
            stopping_notes="Default: require three independent priced sources before stopping. This prevents one retailer plus technical pages and FX data from being mistaken for a market comparison.",
            fallback_notes="If current retail prices cannot be found, a model-based price is a final fallback only. Model knowledge may still explain accessory or bundle allowances separately.",
            future_notes="Future sections could hold family aliases, generation/model matching, minimum specification match, stock-state rules and marketplace exclusions.",
        ),
        "industrial": _default_rule(
            "Industrial equipment", 40, "industrial",
            keywords=["generator", "motor", "pump", "compressor", "chiller", "boiler", "inverter", "drive", "valve", "cable", "machine", "machinery", "crane", "ups", "battery", "panel"],
            phrases=["industrial equipment", "industrial machine"],
            min_priced_sources=2,
            strategy="Prioritise manufacturer/distributor catalogues, quotations and procurement benchmarks; compare capacity, rating, configuration and scope.",
            evidence_notes="Prefer quoted/catalogue prices tied to capacity, rating and configuration; use technical sources to judge comparability.",
            stopping_notes="Require multiple independent priced sources by default rather than accepting the first commercially priced result.",
            fallback_notes="Model knowledge can supply clearly labelled accessory, freight, installation or contingency allowances after web pricing has been used first.",
            future_notes="Future sections could hold category-specific rating parsers, sizing attributes, regional multipliers and supplier/source preferences.",
        ),
        FALLBACK_CATEGORY: _default_rule(
            "General product", 1000, "general-product",
            min_priced_sources=3,
            strategy="Prioritise exact-description supplier, distributor and catalogue prices before broader comparable-product evidence. Treat this as a catch-all category and seek multiple independent priced listings before stopping.",
            evidence_notes="This catch-all should still count actual price-bearing product evidence rather than retained technical/background sources or FX references.",
            stopping_notes="Default: require three independent priced sources. A single supplier price must not be described as a market comparison.",
            fallback_notes="Use model knowledge only after web price research is exhausted; it may supplement accessories or cost breakdowns when clearly labelled.",
            future_notes="Use this category to identify recurring uncategorised families. When a family becomes important, add a dedicated category rather than endlessly expanding the catch-all.",
        ),
    },
}


def _clean_list(value, *, max_items=100, max_length=160):
    values = re.split(r"[\n,]+", value) if isinstance(value, str) else value if isinstance(value, list) else []
    rows, seen = [], set()
    for item in values:
        text = " ".join(str(item or "").split()).strip()[:max_length]
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            rows.append(text)
        if len(rows) >= max_items:
            break
    return rows


def _category_id(value):
    raw = str(value or "").strip().lower().replace("_", "-")
    raw = re.sub(r"[^a-z0-9-]+", "-", raw)
    return re.sub(r"-+", "-", raw).strip("-")[:80]


def _clean_text(value, fallback="", limit=6000):
    text = str(value if value is not None else fallback).strip()
    return text[:limit]


def _category_order_from_rules(rules, include_disabled=True):
    rows = []
    for category_id, rule in (rules.get("categories") or {}).items():
        if category_id == FALLBACK_CATEGORY:
            continue
        if not include_disabled and not bool(rule.get("enabled", True)):
            continue
        rows.append((int(rule.get("order", 500)), category_id))
    rows.sort(key=lambda item: (item[0], item[1]))
    ordered = [category_id for _order, category_id in rows]
    if FALLBACK_CATEGORY in (rules.get("categories") or {}):
        ordered.append(FALLBACK_CATEGORY)
    return ordered


def get_category_order(rules=None, include_disabled=True):
    return _category_order_from_rules(rules or get_classification_rules(), include_disabled=include_disabled)


def _validated_rules(payload):
    incoming_categories = payload.get("categories", {}) if isinstance(payload, dict) else {}
    if not isinstance(incoming_categories, dict):
        incoming_categories = {}

    try:
        incoming_version = int(payload.get("version", 1)) if isinstance(payload, dict) else 1
    except (TypeError, ValueError):
        incoming_version = 1

    categories = {}
    for index, (raw_id, incoming) in enumerate(incoming_categories.items()):
        if not isinstance(incoming, dict):
            continue
        category_id = _category_id(incoming.get("id") or raw_id)
        if not category_id or category_id in categories:
            continue

        default = deepcopy(DEFAULT_RULES["categories"].get(category_id) or _default_rule(
            category_id.replace("-", " ").title(),
            (index + 1) * 10,
            "general-product",
            min_priced_sources=3,
            strategy="Prioritise exact-description supplier, distributor and catalogue prices before broader comparable-product evidence.",
            evidence_notes="Define which evidence should count for this category.",
            stopping_notes="Continue until the configured commercial-evidence threshold is met or research limits are exhausted.",
            fallback_notes="Use model knowledge only after web research is exhausted, and label it separately.",
            future_notes="Use this section for category-specific rules that are not yet implemented.",
        ))
        default["label"] = _clean_text(incoming.get("label"), default["label"], 120) or default["label"]
        default["enabled"] = bool(incoming.get("enabled", default.get("enabled", True)))
        try:
            default["order"] = max(0, min(9999, int(incoming.get("order", default.get("order", (index + 1) * 10)))))
        except (TypeError, ValueError):
            pass
        profile = str(incoming.get("search_profile") or default.get("search_profile") or "general-product")
        default["search_profile"] = profile if profile in SEARCH_PROFILES else "general-product"
        default["keywords"] = _clean_list(incoming.get("keywords", default.get("keywords", [])))
        default["phrases"] = _clean_list(incoming.get("phrases", default.get("phrases", [])))
        patterns = _clean_list(incoming.get("patterns", default.get("patterns", [])), max_items=30, max_length=240)
        default["patterns"] = []
        for pattern in patterns:
            try:
                re.compile(pattern, re.I)
            except re.error:
                continue
            default["patterns"].append(pattern)
        try:
            minimum = int(incoming.get("min_priced_sources", default["min_priced_sources"]))
        except (TypeError, ValueError):
            minimum = default["min_priced_sources"]
        default["min_priced_sources"] = max(1, min(10, minimum))
        default["require_independent_domains"] = bool(incoming.get("require_independent_domains", default.get("require_independent_domains", True)))
        for key in ("strategy", "evidence_notes", "stopping_notes", "fallback_notes", "future_notes"):
            default[key] = _clean_text(incoming.get(key), default.get(key, ""))
        categories[category_id] = default

    if not categories:
        categories = deepcopy(DEFAULT_RULES["categories"])

    # v3 introduced Power Transformers. Existing v1/v2 installations receive it once;
    # after they save as v3 they are free to delete/disable/reconfigure it like any other category.
    if incoming_version < RULES_VERSION and "power-transformers" not in categories:
        categories["power-transformers"] = deepcopy(DEFAULT_RULES["categories"]["power-transformers"])
    if incoming_version < 2:
        for category_id, default in DEFAULT_RULES["categories"].items():
            if category_id not in categories:
                categories[category_id] = deepcopy(default)

    fallback = categories.get(FALLBACK_CATEGORY) or deepcopy(DEFAULT_RULES["categories"][FALLBACK_CATEGORY])
    fallback["enabled"] = True
    fallback["search_profile"] = "general-product"
    fallback["keywords"] = []
    fallback["phrases"] = []
    fallback["patterns"] = []
    fallback["order"] = 1000
    categories[FALLBACK_CATEGORY] = fallback

    ordered = sorted(
        ((int(rule.get("order", 500)), category_id) for category_id, rule in categories.items() if category_id != FALLBACK_CATEGORY),
        key=lambda item: (item[0], item[1]),
    )
    for index, (_old_order, category_id) in enumerate(ordered, 1):
        categories[category_id]["order"] = index * 10

    return {"version": RULES_VERSION, "categories": categories}


def get_classification_rules():
    if not RULES_FILE.exists():
        return deepcopy(DEFAULT_RULES)
    try:
        payload = json.loads(RULES_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return deepcopy(DEFAULT_RULES)
    return _validated_rules(payload)


def save_classification_rules(payload):
    rules = _validated_rules(payload)
    with LOCK:
        RULES_FILE.write_text(json.dumps(rules, indent=2) + "\n")
    return rules


def reset_classification_rules():
    with LOCK:
        try:
            RULES_FILE.unlink()
        except FileNotFoundError:
            pass
    return deepcopy(DEFAULT_RULES)


def _tokens(value: str):
    return set(re.findall(r"[a-z0-9][a-z0-9.+-]*", str(value or "").lower()))


def category_profile(category_id, rules=None):
    rules = rules or get_classification_rules()
    rule = (rules.get("categories") or {}).get(category_id) or {}
    profile = str(rule.get("search_profile") or category_id or "general-product")
    return profile if profile in SEARCH_PROFILES else "general-product"


def classify_query(query: str, rules=None):
    rules = rules or get_classification_rules()
    text = " ".join(str(query or "").lower().split())
    tokens = _tokens(text)
    for category_id in _category_order_from_rules(rules, include_disabled=False):
        if category_id == FALLBACK_CATEGORY:
            continue
        rule = rules["categories"][category_id]
        for phrase in rule.get("phrases", []):
            if phrase.casefold() in text.casefold():
                return category_id, f"Matched phrase: {phrase}"
        for keyword in rule.get("keywords", []):
            if keyword.casefold() in tokens:
                return category_id, f"Matched keyword: {keyword}"
        for pattern in rule.get("patterns", []):
            try:
                if re.search(pattern, text, re.I):
                    return category_id, f"Matched pattern: {pattern}"
            except re.error:
                continue
    return FALLBACK_CATEGORY, "No enabled specialist rule matched; using catch-all category"


def classification_report(query: str):
    rules = get_classification_rules()
    category_id, reason = classify_query(query, rules)
    rule = rules["categories"][category_id]
    active_order = get_category_order(rules, include_disabled=False)
    return {
        "query": str(query or "").strip(),
        "category": category_id,
        "label": rule["label"],
        "reason": reason,
        "priority": active_order.index(category_id) + 1 if category_id in active_order else None,
        "enabled": bool(rule.get("enabled", True)),
        "search_profile": category_profile(category_id, rules),
        "min_priced_sources": rule["min_priced_sources"],
        "require_independent_domains": rule["require_independent_domains"],
        "strategy": rule["strategy"],
    }


def _is_fx_evidence(item):
    return (
        "frankfurter" in str(item.get("url") or "").lower()
        or "exchange rate" in str(item.get("title") or "").lower()
        or "reference exchange rates" in str(item.get("query") or "").lower()
    )


def _source_domain(item):
    host = (urlparse(str(item.get("url") or "")).hostname or "").lower().removeprefix("www.")
    return host or str(item.get("title") or item.get("source_id") or "unknown-source").casefold()


def _consumer_identity_price_match_without_original(search, item, question, category_id=None):
    category_id = category_id or classify_query(question)[0]
    if category_profile(category_id) != "consumer-retail" or not search.has_commercial_price([item]):
        return False
    corpus = " ".join([
        str(item.get("title") or ""), str(item.get("snippet") or ""), str(item.get("text") or ""),
        " ".join(map(str, item.get("claims", []))), " ".join(map(str, item.get("passages", []))),
    ])
    generic = {
        "price", "prices", "pricing", "cost", "current", "new", "buy", "online", "retail", "retailer",
        "uk", "gb", "united", "kingdom", "with", "and", "for", "the", "a", "an",
    }
    rules = get_classification_rules()
    category_words = set()
    for candidate_id, rule in rules["categories"].items():
        if category_profile(candidate_id, rules) == "consumer-retail":
            category_words.update(word.casefold() for word in rule.get("keywords", []))
    anchors = {token for token in _tokens(question) if token not in generic and token not in category_words and len(token) >= 2}
    corpus_tokens = _tokens(corpus)
    if not anchors:
        return bool(_tokens(question) & corpus_tokens)
    required = max(1, min(len(anchors), max(2, (len(anchors) + 1) // 2)))
    return len(anchors & corpus_tokens) >= required


def _consumer_identity_price_match(search, item, question, category_id=None):
    if search.exact_priced_product_candidate(item, question, item.get("text", "")):
        return True
    return _consumer_identity_price_match_without_original(search, item, question, category_id)


def benchmark_status(search, evidence, question, category=None, item_qualifier=None):
    category_id = category or classify_query(question)[0]
    rules = get_classification_rules()
    rule = rules["categories"].get(category_id, rules["categories"][FALLBACK_CATEGORY])
    profile = category_profile(category_id, rules)
    priced = []
    for item in evidence or []:
        if _is_fx_evidence(item) or not search.has_commercial_price([item]):
            continue
        if item_qualifier is not None and not item_qualifier(item):
            continue
        if profile == "consumer-retail" and not _consumer_identity_price_match(search, item, question, category_id):
            continue
        priced.append(item)
    qualifying = len({_source_domain(item) for item in priced}) if rule.get("require_independent_domains", True) else len(priced)
    minimum = int(rule.get("min_priced_sources", 1))
    return {
        "category": category_id,
        "search_profile": profile,
        "qualifying_priced_sources": qualifying,
        "minimum_priced_sources": minimum,
        "require_independent_domains": bool(rule.get("require_independent_domains", True)),
        "sufficient": qualifying >= minimum,
    }


def install_classification_policy(search):
    """Make editable/dynamic classification and stopping rules drive the live search module."""
    if getattr(search, "_classification_policy_installed", False):
        return

    original_exact = search.exact_priced_product_candidate
    original_benchmark = search.has_sufficient_commercial_benchmark
    original_pricing_queries = search.pricing_queries
    original_subject_filter = search.subject_relevant_candidates
    original_rank = search.rank_candidates

    def pricing_category(query):
        return classify_query(query)[0]

    def pricing_profile(category_or_query):
        rules = get_classification_rules()
        if category_or_query in rules.get("categories", {}):
            return category_profile(category_or_query, rules)
        return category_profile(classify_query(str(category_or_query), rules)[0], rules)

    def pricing_strategy_context(category):
        rules = get_classification_rules()
        rule = rules["categories"].get(category)
        return rule["strategy"] if rule else rules["categories"][FALLBACK_CATEGORY]["strategy"]

    def pricing_queries(query, planned, category=None):
        resolved = category or pricing_category(query)
        return original_pricing_queries(query, planned, pricing_profile(resolved))

    def subject_relevant_candidates(candidates, question, category=None):
        resolved = category or pricing_category(question)
        return original_subject_filter(candidates, question, pricing_profile(resolved))

    def rank_candidates(candidates, question, requirements=None, subquestions=None, category="general-product"):
        return original_rank(candidates, question, requirements, subquestions, pricing_profile(category))

    def exact_priced_product_candidate(candidate, question, content=""):
        if original_exact(candidate, question, content):
            return True
        item = dict(candidate)
        item["text"] = content
        return _consumer_identity_price_match_without_original(search, item, question)

    def live_benchmark_status(evidence, question, category=None):
        resolved = category or pricing_category(question)
        profile = pricing_profile(resolved)
        qualifier = None
        if profile == "hv-equipment":
            qualifier = lambda item: original_benchmark([item], question, "hv-equipment")
        return benchmark_status(search, evidence, question, resolved, qualifier)

    def has_sufficient_commercial_benchmark(evidence, question, category):
        return live_benchmark_status(evidence, question, category)["sufficient"]

    search.pricing_category = pricing_category
    search.pricing_profile = pricing_profile
    search.pricing_strategy_context = pricing_strategy_context
    search.pricing_queries = pricing_queries
    search.subject_relevant_candidates = subject_relevant_candidates
    search.rank_candidates = rank_candidates
    search.exact_priced_product_candidate = exact_priced_product_candidate
    search.has_sufficient_commercial_benchmark = has_sufficient_commercial_benchmark
    search.classification_report = classification_report
    search.benchmark_status = live_benchmark_status
    search._classification_policy_installed = True
