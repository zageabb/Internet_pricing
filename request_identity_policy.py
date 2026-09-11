from __future__ import annotations

import math
import re

import classification_policy


DEVICE_CLASS_TERMS = {
    "laptop", "notebook", "ultrabook", "computer", "desktop", "phone", "smartphone", "mobile",
    "tablet", "monitor", "printer", "television", "tv", "camera", "headphone", "headphones",
    "keyboard", "mouse", "router", "watch", "device", "product",
}
GENERIC_REQUEST_TERMS = {
    "price", "prices", "pricing", "cost", "costs", "current", "currently", "latest", "new", "buy",
    "online", "retail", "retailer", "retailers", "supplier", "suppliers", "market", "markets", "find",
    "show", "much", "available", "availability", "stock", "in-stock", "instock", "quote", "quotation",
    "uk", "gb", "usa", "us", "europe", "european", "united", "kingdom", "states",
}
SPEC_TOKEN_RE = re.compile(r"^\d+(?:[.,]\d+)?(?:gb|tb|mb|mah|hz|ghz|w|wh|inch|inches|mp)$", re.I)
PRICE_RE = re.compile(
    r"(?:GBP|USD|EUR|CAD|AUD|INR|JPY|CNY|CHF|£|€|\$|₹|¥)\s*\d[\d,.]*|"
    r"\d[\d,.]*\s*(?:GBP|USD|EUR|CAD|AUD|INR|JPY|CNY|CHF)",
    re.I,
)
SAFE_FALLBACK_MARKER = "### Exact product price not verified"


def _compact(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _original_request(search, fallback: str = "") -> str:
    getter = getattr(search, "active_request_query", None)
    if callable(getter):
        value = _compact(getter())
        if value:
            return value
    return _compact(fallback)


def _consumer_category(search, value: str = "") -> tuple[bool, str]:
    category = search.pricing_category(value)
    profile = search.pricing_profile(category) if hasattr(search, "pricing_profile") else category
    return profile == "consumer-retail", category


def _identity_tokens(search, query: str) -> list[str]:
    rows, seen = [], set()
    for token in re.findall(r"[a-z0-9][a-z0-9.+_-]*", str(query or "").lower()):
        if token in GENERIC_REQUEST_TERMS or token in DEVICE_CLASS_TERMS or SPEC_TOKEN_RE.match(token):
            continue
        if token in getattr(search, "STOP_WORDS", set()):
            continue
        if len(token) < 2:
            continue
        if token not in seen:
            seen.add(token)
            rows.append(token)
    return rows


def _identity_phrase(search, query: str) -> str:
    tokens = _identity_tokens(search, query)
    return " ".join(tokens) if tokens else _compact(query)


def _identity_match(search, text: str, query: str) -> tuple[bool, str]:
    identity = _identity_tokens(search, query)
    if not identity:
        return True, "No distinctive product identity tokens were available"
    available = search.terms(text)
    critical = {token for token in identity if any(ch.isdigit() for ch in token)}
    missing_critical = sorted(critical - available)
    if missing_critical:
        return False, "Missing identity token(s): " + ", ".join(missing_critical)
    matches = sum(1 for token in identity if token in available)
    if len(identity) <= 4:
        required = len(identity)
    else:
        required = max(3, math.ceil(len(identity) * 0.72))
    if matches < required:
        return False, f"Only {matches}/{len(identity)} product identity tokens matched"
    return True, f"Matched {matches}/{len(identity)} product identity tokens"


def _candidate_identity_match(search, candidate: dict, query: str, content: str = "") -> tuple[bool, str]:
    corpus = "\n".join([
        str(candidate.get("title") or ""),
        str(candidate.get("snippet") or ""),
        str(content or candidate.get("text") or ""),
    ])
    return _identity_match(search, corpus, query)


def _visible_identity_price(search, candidate: dict, query: str, content: str = "") -> bool:
    matched, _reason = _candidate_identity_match(search, candidate, query, content)
    if not matched:
        return False
    corpus = "\n".join([
        str(candidate.get("title") or ""), str(candidate.get("snippet") or ""), str(content or "")
    ])
    return bool(PRICE_RE.search(corpus))


def _equipment_request(query: str) -> str:
    equipment = _compact(query)
    equipment = re.sub(r"^\s*(?:pricing|price|cost)\s+(?:for|of)\s+", "", equipment, flags=re.I)
    equipment = re.sub(r"\s+\b(?:price|prices|pricing|cost|costs)\b\s*$", "", equipment, flags=re.I)
    return equipment.strip(" ,;:-")


def consumer_initial_queries(search, query: str) -> list[str]:
    # Round one keeps the complete user-supplied product and requested attributes.
    # Only later rounds relax RAM/storage/etc.; the model identity is never relaxed.
    equipment = _equipment_request(query)
    values = [
        f'"{equipment}" price' if equipment else "",
        f"{equipment} retailer price" if equipment else "",
        f"{equipment} supplier price" if equipment else "",
    ]
    return search.clean_queries([item for item in values if item])


def consumer_followup_queries(search, query: str, attempted_queries=None) -> list[str]:
    original = _compact(query)
    identity = _identity_phrase(search, original)
    attempted = {_compact(item).casefold() for item in (attempted_queries or [])}
    values = [
        f"{identity} price",
        f"{identity} retailer listing",
        f"{identity} availability",
        f"{identity} official product",
        f"{identity} buy online",
        f"{identity} distributor price",
    ]
    return [item for item in search.clean_queries(values) if item.casefold() not in attempted][:4]


def _safe_unverified_answer(search, query: str, category: str, *, no_evidence: bool = False) -> str:
    rules = classification_policy.get_classification_rules()
    rule = rules.get("categories", {}).get(category, {})
    minimum = int(rule.get("min_priced_sources", 1))
    identity = _identity_phrase(search, query) or query
    first = (
        f"I could not retain a web source that verifies the exact requested identity **{identity}**."
        if no_evidence else
        f"The research did not retain enough qualifying price evidence to verify a current market price for the exact requested identity **{identity}**."
    )
    return (
        f"{SAFE_FALLBACK_MARKER}\n\n"
        f"{first}\n\n"
        f"I have **not** substituted a related model or product family, and I am **not** filling missing launch dates, specifications or headline pricing from model knowledge. "
        f"This category requires {minimum} qualifying independent priced source{'s' if minimum != 1 else ''} before a market price is treated as verified.\n\n"
        "Any retained related-product or technical sources should be treated only as diagnostics/supporting evidence until the exact product identity and price are verified."
    )


def install_request_identity_policy(search) -> None:
    """Keep consumer product identity invariant while leaving semantic classification to the LLM."""
    if getattr(search, "_request_identity_policy_installed", False):
        return

    original_pricing_queries = search.pricing_queries
    original_subject_filter = search.subject_relevant_candidates
    original_rank = search.rank_candidates
    original_exact_price = search.exact_priced_product_candidate
    original_analyse_source = search.analyse_source
    original_assess_coverage = search.assess_coverage
    original_review_answer = search.review_answer
    original_verify_citations = search.verify_citations

    def pricing_queries(query, planned, category=None):
        resolved = category or search.pricing_category(query)
        profile = search.pricing_profile(resolved) if hasattr(search, "pricing_profile") else resolved
        if profile != "consumer-retail":
            return original_pricing_queries(query, planned, resolved)
        original = _original_request(search, query)
        # Do not let an LLM-planned alias compete in round one. Deterministic searches
        # preserve the exact requested product and requested configuration.
        return consumer_initial_queries(search, original)[:3]

    def subject_relevant_candidates(candidates, question, category=None):
        resolved = category or search.pricing_category(question)
        profile = search.pricing_profile(resolved) if hasattr(search, "pricing_profile") else resolved
        if profile != "consumer-retail":
            return original_subject_filter(candidates, question, resolved)
        original = _original_request(search, question)
        accepted = []
        for candidate in candidates:
            matched, reason = _candidate_identity_match(search, candidate, original)
            if matched:
                item = dict(candidate)
                item["identity_match_reason"] = reason
                accepted.append(item)
        return accepted

    def rank_candidates(candidates, question, requirements=None, subquestions=None, category="general-product"):
        profile = search.pricing_profile(category) if hasattr(search, "pricing_profile") else category
        if profile == "consumer-retail":
            question = _original_request(search, question)
        return original_rank(candidates, question, requirements, subquestions, category)

    def exact_priced_product_candidate(candidate, question, content=""):
        is_consumer, _category = _consumer_category(search, question)
        if not is_consumer:
            return original_exact_price(candidate, question, content)
        original = _original_request(search, question)
        if _visible_identity_price(search, candidate, original, content):
            return True
        return False

    def analyse_source(prompts, settings, model, query, title, url, content):
        is_consumer, _category = _consumer_category(search, query)
        if not is_consumer:
            return original_analyse_source(prompts, settings, model, query, title, url, content)
        original = _original_request(search, query)
        matched, reason = _candidate_identity_match(
            search, {"title": title, "url": url, "snippet": ""}, original, content
        )
        if not matched:
            return "unusable", f"PRODUCT_IDENTITY_MISMATCH: {reason}", []
        return original_analyse_source(prompts, settings, model, original, title, url, content)

    def assess_coverage(prompts, settings, model, rewritten_question, requirements, subquestions, queries, evidence):
        result = original_assess_coverage(
            prompts, settings, model, rewritten_question, requirements, subquestions, queries, evidence
        )
        is_consumer, category = _consumer_category(search, rewritten_question)
        if not is_consumer:
            return result
        original = _original_request(search, rewritten_question)
        status = search.benchmark_status(evidence, original, category)
        if status.get("sufficient"):
            return result
        result = dict(result or {})
        result["complete"] = False
        gaps = search.clean_items(result.get("gaps", []), 6)
        gap = (
            f"Exact product price threshold not met: {status.get('qualifying_priced_sources', 0)}/"
            f"{status.get('minimum_priced_sources', 1)} qualifying priced sources"
        )
        result["gaps"] = [gap] + [item for item in gaps if item.casefold() != gap.casefold()]
        followups = consumer_followup_queries(search, original, queries)
        llm_safe = []
        for item in search.clean_queries(result.get("queries", [])):
            matched, _reason = _identity_match(search, item, original)
            if matched:
                llm_safe.append(item)
        result["queries"] = search.clean_queries(followups + llm_safe)[:4]
        return result

    def review_answer(job_id, prompts, settings, model, query, rewritten_question, requirements, subquestions,
                      answer, evidence, allow_indicative=False):
        is_consumer, category = _consumer_category(search, rewritten_question)
        if not is_consumer:
            return original_review_answer(
                job_id, prompts, settings, model, query, rewritten_question, requirements,
                subquestions, answer, evidence, allow_indicative=allow_indicative,
            )
        original = _original_request(search, query or rewritten_question)
        evidence_text = str(evidence or "").lower()
        no_evidence = any(marker in evidence_text for marker in (
            "no readable web evidence", "knowledge fallback", "web research returned no",
            "no usable evidence", "0 retained", "no relevant pricing evidence",
        ))
        if allow_indicative or no_evidence:
            search.event(
                job_id, "reasoning", "returned", "Protected exact product identity",
                "No model-generated product substitution, launch date, specification or price was allowed without qualifying web evidence",
            )
            return _safe_unverified_answer(search, original, category, no_evidence=no_evidence)
        return original_review_answer(
            job_id, prompts, settings, model, original, original, requirements,
            subquestions, answer, evidence, allow_indicative=False,
        )

    def verify_citations(job_id, prompts, settings, model, rewritten_question, answer, evidence_text, evidence,
                         allow_indicative=False):
        is_consumer, _category = _consumer_category(search, rewritten_question)
        if is_consumer and str(answer or "").startswith(SAFE_FALLBACK_MARKER):
            return answer
        original = _original_request(search, rewritten_question) if is_consumer else rewritten_question
        return original_verify_citations(
            job_id, prompts, settings, model, original, answer, evidence_text, evidence,
            allow_indicative=False if is_consumer else allow_indicative,
        )

    search.consumer_identity_tokens = lambda query: _identity_tokens(search, query)
    search.consumer_identity_match = lambda text, query: _identity_match(search, text, query)
    search.consumer_initial_queries = lambda query: consumer_initial_queries(search, query)
    search.consumer_followup_queries = lambda query, attempted=None: consumer_followup_queries(search, query, attempted)
    search.pricing_queries = pricing_queries
    search.subject_relevant_candidates = subject_relevant_candidates
    search.rank_candidates = rank_candidates
    search.exact_priced_product_candidate = exact_priced_product_candidate
    search.analyse_source = analyse_source
    search.assess_coverage = assess_coverage
    search.review_answer = review_answer
    search.verify_citations = verify_citations
    search._request_identity_policy_installed = True
