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
CATEGORY_ORDER = ["hv-equipment", "service-project", "consumer-retail", "industrial", "general-product"]

DEFAULT_RULES = {
    "version": 1,
    "categories": {
        "hv-equipment": {
            "label": "HV equipment",
            "keywords": ["switchgear", "transformer", "disconnector", "isolator", "substation", "circuit-breaker", "breaker", "busbar", "bushing", "arrester", "earthing", "relay", "protection", "gis", "ais", "vcb"],
            "phrases": ["vacuum circuit breaker", "medium voltage switchgear", "mv switchgear", "metal clad switchgear", "metal-clad switchgear", "ring main unit"],
            "patterns": [r"\b\d+(?:\.\d+)?\s*k\s*v\b"],
            "min_priced_sources": 2,
            "require_independent_domains": True,
            "strategy": "Prioritise utility procurement, awards, frameworks, BOQs, transaction/import-export evidence and cost schedules; compare voltage class, ratings, configuration and supply-versus-installed scope.",
            "evidence_notes": "Prefer line-item or equipment-level prices. Technical-only sources can validate comparability but do not count toward the priced-source stopping threshold.",
            "stopping_notes": "Do not stop merely because technical evidence is strong. Continue until the priced-source threshold is met or the configured research/page limits are exhausted.",
            "fallback_notes": "Web pricing is primary. Model knowledge may supplement accessories/package allowances; a model-based headline equipment price is final fallback only.",
            "future_notes": "Good home for future voltage-class mappings, equipment-family aliases, rating tolerances and category-specific source weighting.",
        },
        "service-project": {
            "label": "Service / project",
            "keywords": ["service", "services", "installation", "install", "maintenance", "repair", "consultancy", "consulting", "commissioning", "construction", "labour", "labor", "hire", "rental"],
            "phrases": ["day rate", "labour rate", "labor rate", "installed cost"],
            "patterns": [],
            "min_priced_sources": 2,
            "require_independent_domains": True,
            "strategy": "Prioritise schedules of rates, labour/day rates, tender awards and installed project costs; compare geography, quantities and inclusions.",
            "evidence_notes": "Prefer rate cards, schedules of rates, contract awards and clearly scoped installed-project values.",
            "stopping_notes": "Seek more than one independent commercial benchmark where possible because labour and project scope vary materially by region and inclusion.",
            "fallback_notes": "Use model knowledge only to explain typical cost structure or allowances when the web evidence is incomplete; label it separately.",
            "future_notes": "Future sections could hold geography rules, labour categories, mobilisation, travel and installed-scope normalization.",
        },
        "consumer-retail": {
            "label": "Consumer / retail",
            "keywords": ["laptop", "monitor", "computer", "desktop", "phone", "smartphone", "tablet", "printer", "television", "camera", "headphone", "headphones", "keyboard", "mouse", "router", "watch", "bottle", "bottles", "can", "cans", "pack", "drink", "drinks", "beverage", "beverages", "cola", "soda", "grocery", "groceries", "food", "snack", "snacks", "litre", "litres", "liter", "liters", "notebook", "ultrabook", "thinkpad", "thinkbook", "macbook", "chromebook", "latitude", "elitebook", "probook", "zenbook", "vivobook", "ideapad", "surface"],
            "phrases": ["x1 carbon", "thinkpad x1 carbon", "macbook air", "macbook pro", "surface laptop", "surface pro", "dell latitude", "hp elitebook", "hp probook", "lenovo thinkbook", "lenovo ideapad", "lenovo yoga", "asus zenbook", "asus vivobook"],
            "patterns": [],
            "min_priced_sources": 3,
            "require_independent_domains": True,
            "strategy": "Prioritise exact model/specification retailer listings and visible current prices; reject generic category pages and different models. Seek multiple independent priced listings before declaring a market benchmark.",
            "evidence_notes": "Count only matching product/model/specification listings with a visible usable price. Currency-only sources never count as priced products.",
            "stopping_notes": "Default: require three independent priced sources before stopping. This prevents one retailer plus technical pages and FX data from being mistaken for a market comparison.",
            "fallback_notes": "If current retail prices cannot be found, a model-based price is a final fallback only. Model knowledge may still explain accessory or bundle allowances separately.",
            "future_notes": "Future sections could hold family aliases, generation/model matching, minimum specification match, stock-state rules and marketplace exclusions.",
        },
        "industrial": {
            "label": "Industrial equipment",
            "keywords": ["generator", "motor", "pump", "compressor", "chiller", "boiler", "inverter", "drive", "valve", "cable", "machine", "machinery", "crane", "ups", "battery", "panel"],
            "phrases": ["industrial equipment", "industrial machine"],
            "patterns": [],
            "min_priced_sources": 2,
            "require_independent_domains": True,
            "strategy": "Prioritise manufacturer/distributor catalogues, quotations and procurement benchmarks; compare capacity, rating, configuration and scope.",
            "evidence_notes": "Prefer quoted/catalogue prices tied to capacity, rating and configuration; use technical sources to judge comparability.",
            "stopping_notes": "Require multiple independent priced sources by default rather than accepting the first commercially priced result.",
            "fallback_notes": "Model knowledge can supply clearly labelled accessory, freight, installation or contingency allowances after web pricing has been used first.",
            "future_notes": "Future sections could hold category-specific rating parsers, sizing attributes, regional multipliers and supplier/source preferences.",
        },
        "general-product": {
            "label": "General product",
            "keywords": [], "phrases": [], "patterns": [],
            "min_priced_sources": 3,
            "require_independent_domains": True,
            "strategy": "Prioritise exact-description supplier, distributor and catalogue prices before broader comparable-product evidence. Treat this as a catch-all category and seek multiple independent priced listings before stopping.",
            "evidence_notes": "This catch-all should still count actual price-bearing product evidence rather than retained technical/background sources or FX references.",
            "stopping_notes": "Default: require three independent priced sources. A single supplier price must not be described as a market comparison.",
            "fallback_notes": "Use model knowledge only after web price research is exhausted; it may supplement accessories or cost breakdowns when clearly labelled.",
            "future_notes": "Use this category to identify recurring uncategorised families. When a family becomes important, add a dedicated category rather than endlessly expanding the catch-all.",
        },
    },
}


def _clean_list(value, *, max_items=100, max_length=160):
    values = re.split(r"[\n,]+", value) if isinstance(value, str) else value if isinstance(value, list) else []
    rows, seen = [], set()
    for item in values:
        text = " ".join(str(item or "").split()).strip()[:max_length]
        key = text.casefold()
        if text and key not in seen:
            seen.add(key); rows.append(text)
        if len(rows) >= max_items:
            break
    return rows


def _validated_rules(payload):
    current = deepcopy(DEFAULT_RULES)
    incoming_categories = payload.get("categories", {}) if isinstance(payload, dict) else {}
    for category in CATEGORY_ORDER:
        incoming = incoming_categories.get(category, {}) if isinstance(incoming_categories, dict) else {}
        if not isinstance(incoming, dict):
            continue
        rule = current["categories"][category]
        if category != "general-product":
            rule["keywords"] = _clean_list(incoming.get("keywords", rule["keywords"]))
            rule["phrases"] = _clean_list(incoming.get("phrases", rule["phrases"]))
            patterns = _clean_list(incoming.get("patterns", rule["patterns"]), max_items=20, max_length=240)
            valid_patterns = []
            for pattern in patterns:
                try:
                    re.compile(pattern, re.I)
                except re.error:
                    continue
                valid_patterns.append(pattern)
            rule["patterns"] = valid_patterns
        try:
            minimum = int(incoming.get("min_priced_sources", rule["min_priced_sources"]))
        except (TypeError, ValueError):
            minimum = rule["min_priced_sources"]
        rule["min_priced_sources"] = max(1, min(10, minimum))
        if "require_independent_domains" in incoming:
            rule["require_independent_domains"] = bool(incoming.get("require_independent_domains"))
        for key in ("strategy", "evidence_notes", "stopping_notes", "fallback_notes", "future_notes"):
            rule[key] = str(incoming.get(key, rule[key]) or "").strip()[:6000]
    return current


def get_classification_rules():
    if not RULES_FILE.exists():
        return deepcopy(DEFAULT_RULES)
    try:
        return _validated_rules(json.loads(RULES_FILE.read_text()))
    except (OSError, json.JSONDecodeError):
        return deepcopy(DEFAULT_RULES)


def save_classification_rules(payload):
    rules = _validated_rules(payload)
    with LOCK:
        RULES_FILE.write_text(json.dumps(rules, indent=2) + "\n")
    return rules


def reset_classification_rules():
    with LOCK:
        try: RULES_FILE.unlink()
        except FileNotFoundError: pass
    return deepcopy(DEFAULT_RULES)


def _tokens(value: str):
    return set(re.findall(r"[a-z0-9][a-z0-9.+-]*", str(value or "").lower()))


def classify_query(query: str, rules=None):
    rules = rules or get_classification_rules()
    text = " ".join(str(query or "").lower().split()); tokens = _tokens(text)
    for category in CATEGORY_ORDER:
        if category == "general-product": continue
        rule = rules["categories"][category]
        for phrase in rule.get("phrases", []):
            if phrase.casefold() in text.casefold(): return category, f"Matched phrase: {phrase}"
        for keyword in rule.get("keywords", []):
            if keyword.casefold() in tokens: return category, f"Matched keyword: {keyword}"
        for pattern in rule.get("patterns", []):
            try:
                if re.search(pattern, text, re.I): return category, f"Matched pattern: {pattern}"
            except re.error: continue
    return "general-product", "No configured specialist rule matched; using catch-all category"


def classification_report(query: str):
    rules = get_classification_rules(); category, reason = classify_query(query, rules); rule = rules["categories"][category]
    return {"query": str(query or "").strip(), "category": category, "label": rule["label"], "reason": reason,
            "priority": CATEGORY_ORDER.index(category) + 1, "min_priced_sources": rule["min_priced_sources"],
            "require_independent_domains": rule["require_independent_domains"], "strategy": rule["strategy"]}


def _is_fx_evidence(item):
    return ("frankfurter" in str(item.get("url") or "").lower()
            or "exchange rate" in str(item.get("title") or "").lower()
            or "reference exchange rates" in str(item.get("query") or "").lower())


def _source_domain(item):
    host = (urlparse(str(item.get("url") or "")).hostname or "").lower().removeprefix("www.")
    return host or str(item.get("title") or item.get("source_id") or "unknown-source").casefold()


def _consumer_identity_price_match_without_original(search, item, question):
    if classify_query(question)[0] != "consumer-retail" or not search.has_commercial_price([item]): return False
    corpus = " ".join([str(item.get("title") or ""), str(item.get("snippet") or ""), str(item.get("text") or ""),
                       " ".join(map(str, item.get("claims", []))), " ".join(map(str, item.get("passages", [])))])
    generic = {"price", "prices", "pricing", "cost", "current", "new", "buy", "online", "retail", "retailer",
               "uk", "gb", "united", "kingdom", "with", "and", "for", "the", "a", "an"}
    category_words = {word.casefold() for word in get_classification_rules()["categories"]["consumer-retail"].get("keywords", [])}
    anchors = {token for token in _tokens(question) if token not in generic and token not in category_words and len(token) >= 2}
    corpus_tokens = _tokens(corpus)
    if not anchors: return bool(_tokens(question) & corpus_tokens)
    required = max(1, min(len(anchors), max(2, (len(anchors) + 1) // 2)))
    return len(anchors & corpus_tokens) >= required


def _consumer_identity_price_match(search, item, question):
    if search.exact_priced_product_candidate(item, question, item.get("text", "")): return True
    return _consumer_identity_price_match_without_original(search, item, question)


def benchmark_status(search, evidence, question, category=None, item_qualifier=None):
    category = category or classify_query(question)[0]
    rule = get_classification_rules()["categories"].get(category, get_classification_rules()["categories"]["general-product"])
    priced = []
    for item in evidence or []:
        if _is_fx_evidence(item) or not search.has_commercial_price([item]): continue
        if item_qualifier is not None and not item_qualifier(item): continue
        if category == "consumer-retail" and not _consumer_identity_price_match(search, item, question): continue
        priced.append(item)
    qualifying = len({_source_domain(item) for item in priced}) if rule.get("require_independent_domains", True) else len(priced)
    minimum = int(rule.get("min_priced_sources", 1))
    return {"category": category, "qualifying_priced_sources": qualifying, "minimum_priced_sources": minimum,
            "require_independent_domains": bool(rule.get("require_independent_domains", True)), "sufficient": qualifying >= minimum}


def install_classification_policy(search):
    """Make editable classification and stopping rules drive the live search module."""
    if getattr(search, "_classification_policy_installed", False): return
    original_exact = search.exact_priced_product_candidate
    original_benchmark = search.has_sufficient_commercial_benchmark

    def pricing_category(query): return classify_query(query)[0]

    def pricing_strategy_context(category):
        rule = get_classification_rules()["categories"].get(category)
        return rule["strategy"] if rule else "Use evidence appropriate to the requested product and scope."

    def exact_priced_product_candidate(candidate, question, content=""):
        if original_exact(candidate, question, content): return True
        item = dict(candidate); item["text"] = content
        return _consumer_identity_price_match_without_original(search, item, question)

    def live_benchmark_status(evidence, question, category=None):
        resolved = category or classify_query(question)[0]
        qualifier = None
        if resolved == "hv-equipment":
            # Keep the specialist HV scope/rating/project-total validator underneath
            # the editable minimum-source threshold.
            qualifier = lambda item: original_benchmark([item], question, resolved)
        return benchmark_status(search, evidence, question, resolved, qualifier)

    def has_sufficient_commercial_benchmark(evidence, question, category):
        return live_benchmark_status(evidence, question, category)["sufficient"]

    search.pricing_category = pricing_category
    search.pricing_strategy_context = pricing_strategy_context
    search.exact_priced_product_candidate = exact_priced_product_candidate
    search.has_sufficient_commercial_benchmark = has_sufficient_commercial_benchmark
    search.classification_report = classification_report
    search.benchmark_status = live_benchmark_status
    search._classification_policy_installed = True
