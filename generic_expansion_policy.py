from __future__ import annotations

import threading


_STATE = threading.local()
LEVELS = ("canonical", "near", "adjacent", "broad")
LEVEL_LABELS = {
    "canonical": "canonical-name / alias expansion",
    "near": "near-spec comparator",
    "adjacent": "adjacent-family comparator",
    "broad": "broad family benchmark",
}


def _compact(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _original_request(search, fallback: str = "") -> str:
    getter = getattr(search, "active_request_query", None)
    if callable(getter):
        value = _compact(getter())
        if value:
            return value
    return _compact(fallback)


def _query_key(value: str) -> str:
    first_line = str(value or "").splitlines()[0] if str(value or "") else ""
    return _compact(first_line).casefold()


def _reset_state(original: str = "") -> None:
    _STATE.original = _compact(original)
    _STATE.plan = {level: [] for level in LEVELS}
    _STATE.relations = {}
    _STATE.prepared = False


def _state_for(original: str = ""):
    original = _compact(original)
    if not hasattr(_STATE, "relations") or (original and getattr(_STATE, "original", "") != original):
        _reset_state(original)
    return _STATE


def _relation_for(value: str):
    if not hasattr(_STATE, "relations"):
        return None
    return _STATE.relations.get(_query_key(value))


def _register(level: str, query: str, reason: str, original: str) -> None:
    state = _state_for(original)
    query = _compact(query)[:300]
    reason = _compact(reason)[:500]
    if not query or level not in LEVELS:
        return
    key = _query_key(query)
    relation = {
        "level": level,
        "label": LEVEL_LABELS[level],
        "query": query,
        "reason": reason or LEVEL_LABELS[level],
        "original_request": _compact(original),
    }
    state.relations[key] = relation
    if all(_query_key(row["query"]) != key for row in state.plan[level]):
        state.plan[level].append(relation)


def _clean_rows(value):
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if isinstance(item, str):
            query, reason = item, ""
        elif isinstance(item, dict):
            query, reason = item.get("query"), item.get("reason")
        else:
            continue
        query = _compact(query)
        if query:
            rows.append((query, _compact(reason)))
    return rows


def _commercial_hint(profile: str) -> str:
    return {
        "consumer-retail": "Use retailer/store/official-product price language.",
        "industrial": "Use distributor/catalogue/quotation/tender price language.",
        "service-project": "Use schedule-of-rates/day-rate/contract-award language.",
        "hv-equipment": "Use tender/BOQ/purchase-order/transaction/quotation language.",
        "general-product": "Use supplier/distributor/catalogue price language.",
    }.get(profile, "Use commercially useful price language.")


def prepare_expansion_plan(search, query: str, model: str = "", settings: dict | None = None,
                           category: str | None = None) -> dict:
    """Prepare a generic search-expansion ladder. All aliases are hypotheses, never facts."""
    original = _original_request(search, query)
    state = _state_for(original)
    if state.prepared:
        return state.plan

    category = category or search.pricing_category(original)
    profile = search.pricing_profile(category) if hasattr(search, "pricing_profile") else category
    is_pricing = search.pricing_request(original) or search.implicit_product_pricing(original)
    if not is_pricing:
        state.prepared = True
        return state.plan

    settings = settings or search.get_settings()
    selected_model = model or settings.get("model") or ""
    strategy = search.pricing_strategy_context(category)
    prompt = f"""You are designing broader WEB SEARCH QUERIES for an Internet Pricing application.

Original request:
{original}

Category: {category}
Search profile: {profile}
Category strategy: {strategy}
Commercial-query guidance: {_commercial_hint(profile)}

Create a progressive search ladder. These are SEARCH HYPOTHESES only; do not assert that an alias or comparator is equivalent to the requested item. The downstream source-review LLM will decide whether results are useful.

Return JSON only with four arrays. Each array item must contain `query` and `reason`:
{{
  "canonical": [{{"query":"...","reason":"..."}}],
  "near": [{{"query":"...","reason":"..."}}],
  "adjacent": [{{"query":"...","reason":"..."}}],
  "broad": [{{"query":"...","reason":"..."}}]
}}

Rules:
- canonical: same requested item under likely official name, manufacturer wording, known alias, abbreviation, expanded acronym, or alternate word order. Do not change generation/rating/specification unless the alternate wording itself requires an extra official modifier.
- near: same product/equipment/service family with a small generation, capacity, rating, size, configuration or market variation that could be a useful comparator.
- adjacent: same family with one material specification difference but still commercially informative.
- broad: broader family/category benchmark only; keep the underlying item family recognisable.
- Produce at most 2 queries per level.
- Keep queries concise; do not quote the whole user request.
- Include commercial intent in every query.
- Do not invent prices, dates, specifications, suppliers or factual equivalence statements.
"""
    try:
        parsed = search.ollama_json(settings["ollama_url"], selected_model, prompt)
    except Exception:
        parsed = {}

    for level in LEVELS:
        for query_text, reason in _clean_rows(parsed.get(level))[:2]:
            _register(level, query_text, reason, original)

    if not any(state.plan[level] for level in LEVELS):
        base = _compact(original)[:220]
        _register("broad", f"{base} similar product equipment price benchmark", "Generic fallback comparator search", original)

    state.prepared = True
    return state.plan


def next_expansion_queries(search, attempted_queries=None, limit: int = 4) -> list[str]:
    original = _original_request(search, "")
    state = _state_for(original)
    attempted = {_query_key(item) for item in (attempted_queries or [])}
    rows = []
    for level in LEVELS:
        pending = [row for row in state.plan.get(level, []) if _query_key(row["query"]) not in attempted]
        for row in pending:
            if _query_key(row["query"]) in {_query_key(item) for item in rows}:
                continue
            rows.append(row["query"])
            if len(rows) >= max(1, int(limit)):
                return rows
        if rows:
            next_index = LEVELS.index(level) + 1
            if next_index < len(LEVELS):
                for row in state.plan.get(LEVELS[next_index], []):
                    if _query_key(row["query"]) in attempted or _query_key(row["query"]) in {_query_key(item) for item in rows}:
                        continue
                    rows.append(row["query"])
                    if len(rows) >= max(1, int(limit)):
                        return rows
            return rows
    return rows


def _non_comparator_evidence(evidence):
    rows = []
    for item in evidence or []:
        relation = _relation_for(item.get("query", ""))
        if relation and relation.get("level") in {"near", "adjacent", "broad"}:
            continue
        rows.append(item)
    return rows


def _enriched_query(query: str, relation: dict, original: str) -> str:
    return (
        f"{query}\n"
        f"Search expansion relation: {relation['label']}\n"
        f"Original request: {original}\n"
        f"Expansion rationale: {relation.get('reason') or relation['label']}\n"
        "Treat this expansion as a search hypothesis, not as proof of equivalence. Decide whether the source is an exact match, a useful comparator, or irrelevant. If useful only as a comparator, say what differs from the original request."
    )


def _llm_review_expanded_source(search, prompts, settings, model, query, title, url, content, relation):
    """Expanded hits deliberately bypass exact-match pre-rejectors and go to the final source-review LLM."""
    original = relation.get("original_request") or _original_request(search, query)
    review_query = _enriched_query(query, relation, original)
    prompt = search.render(prompts["source_review"], query=review_query, title=title, url=url, content=content[:6_000])
    try:
        result = search.ollama_json(settings["ollama_url"], model, prompt)
    except Exception as exc:
        return "review_failed", f"Expanded-source quality check failed: {exc}", []
    verdict = str(result.get("verdict") or "").strip().lower()
    reason = search.clean_text(result.get("reason"), "Expanded hit was not useful to the original request")[:500]
    claims = search.clean_items(result.get("claims", []), 5)
    return ("useful", reason, claims) if verdict == "useful" else ("unusable", reason, [])


def install_generic_expansion_policy(search) -> None:
    if getattr(search, "_generic_expansion_policy_installed", False):
        return

    original_pricing_queries = search.pricing_queries
    original_assess_coverage = search.assess_coverage
    original_analyse_source = search.analyse_source
    original_evidence_ledger = search.evidence_ledger
    original_benchmark_status = search.benchmark_status
    original_has_sufficient = search.has_sufficient_commercial_benchmark

    def pricing_queries(query, planned, category=None):
        resolved = category or search.pricing_category(query)
        base = search.clean_queries(original_pricing_queries(query, planned, resolved))
        original = _original_request(search, query)
        prepare_expansion_plan(search, original, category=resolved)
        canonical = [row["query"] for row in _state_for(original).plan.get("canonical", [])][:1]
        return search.clean_queries(base[:3] + canonical)[:4]

    def benchmark_status(evidence, question, category=None):
        return original_benchmark_status(_non_comparator_evidence(evidence), question, category)

    def has_sufficient_commercial_benchmark(evidence, question, category):
        return original_has_sufficient(_non_comparator_evidence(evidence), question, category)

    def assess_coverage(prompts, settings, model, rewritten_question, requirements, subquestions, queries, evidence):
        result = original_assess_coverage(
            prompts, settings, model, rewritten_question, requirements, subquestions, queries, evidence
        )
        original = _original_request(search, rewritten_question)
        category = search.pricing_category(original)
        is_pricing = search.pricing_request(original) or search.implicit_product_pricing(original)
        if not is_pricing:
            return result
        if has_sufficient_commercial_benchmark(evidence, original, category):
            return result

        prepare_expansion_plan(search, original, model=model, settings=settings, category=category)
        ladder = next_expansion_queries(search, queries, limit=4)
        result = dict(result or {})
        result["complete"] = False
        existing = search.clean_queries(result.get("queries", []))
        result["queries"] = search.clean_queries(ladder + existing)[:4]
        gaps = search.clean_items(result.get("gaps", []), 6)
        gap = "Exact commercial benchmark threshold not met; canonical/comparator search ladder active"
        result["gaps"] = [gap] + [item for item in gaps if item.casefold() != gap.casefold()]
        return result

    def analyse_source(prompts, settings, model, query, title, url, content):
        relation = _relation_for(query)
        if not relation:
            return original_analyse_source(prompts, settings, model, query, title, url, content)
        return _llm_review_expanded_source(search, prompts, settings, model, query, title, url, content, relation)

    def evidence_ledger(evidence):
        enriched = []
        for item in evidence or []:
            row = dict(item)
            relation = _relation_for(row.get("query", ""))
            if relation:
                row["query"] = (
                    f"{row.get('query', '')} | {relation['label']} | "
                    f"reason: {relation.get('reason') or relation['label']} | "
                    "equivalence not assumed"
                )
            enriched.append(row)
        return original_evidence_ledger(enriched)

    search.prepare_expansion_plan = lambda query, model="", settings=None, category=None: prepare_expansion_plan(
        search, query, model=model, settings=settings, category=category
    )
    search.next_expansion_queries = lambda attempted=None, limit=4: next_expansion_queries(search, attempted, limit)
    search.query_expansion_relation = _relation_for
    search.has_expansion_evidence = lambda evidence: any(_relation_for(item.get("query", "")) for item in (evidence or []))
    search.pricing_queries = pricing_queries
    search.benchmark_status = benchmark_status
    search.has_sufficient_commercial_benchmark = has_sufficient_commercial_benchmark
    search.assess_coverage = assess_coverage
    search.analyse_source = analyse_source
    search.evidence_ledger = evidence_ledger
    search._generic_expansion_policy_installed = True
