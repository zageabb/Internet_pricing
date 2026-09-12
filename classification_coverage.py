from __future__ import annotations

import threading


_STRUCTURED_EVIDENCE_CONTEXT = threading.local()


def category_followup_queries(question: str, profile: str) -> list[str]:
    base = " ".join(str(question or "").split())[:260]
    if not base:
        return []
    if profile == "consumer-retail":
        values = [
            f'"{base}" retailer price',
            f'"{base}" buy price in stock',
            f'"{base}" supplier price',
        ]
    elif profile == "general-product":
        values = [
            f'"{base}" supplier price',
            f'"{base}" distributor price',
            f'"{base}" catalogue price',
        ]
    elif profile == "industrial":
        values = [
            f'"{base}" distributor price',
            f'"{base}" quotation price',
            f'"{base}" tender award price',
        ]
    elif profile == "service-project":
        values = [
            f'"{base}" schedule of rates',
            f'"{base}" day rate price',
            f'"{base}" tender contract award value',
        ]
    else:
        return []
    return values


def structured_evidence_records(search, evidence) -> list[dict]:
    """Return a bounded machine-readable copy of retained research evidence.

    The user-facing answer remains unchanged; this payload is for downstream systems such
    as Should-Cost that need the retained passages rather than attempting to parse prices
    back out of final Markdown.
    """
    rows = []
    fx_url = str(getattr(search, "FX_URL", "") or "")
    for item in list(evidence or [])[:50]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")[:4000]
        title = str(item.get("title") or url)[:1000]
        text = str(item.get("text") or "")[:20_000]
        passages = [str(value)[:6_000] for value in (item.get("passages") or []) if str(value).strip()][:8]
        claims = [str(value)[:3_000] for value in (item.get("claims") or []) if str(value).strip()][:8]
        if not url or not (text.strip() or passages or claims):
            continue
        kind = "currency_reference" if fx_url and url.startswith(fx_url) else "market_source"
        rows.append({
            "source_id": item.get("source_id"),
            "kind": kind,
            "title": title,
            "url": url,
            "query": str(item.get("query") or "")[:1000],
            "passages": passages,
            "claims": claims,
            "text": text,
            "relevance": item.get("relevance"),
            "published_at": str(item.get("published_at") or "")[:100],
            "obtained_at": str(item.get("obtained_at") or "")[:100],
            "content_type": str(item.get("content_type") or "")[:200],
            "benchmark_eligible": False,
        })
    return rows


def _source_benchmark_eligible(search, item: dict, query: str, category: str) -> bool:
    if item.get("kind") != "market_source":
        return False
    relation_getter = getattr(search, "query_expansion_relation", None)
    relation = relation_getter(item.get("query", "")) if callable(relation_getter) else None
    if relation and relation.get("level") in {"near", "adjacent", "broad"}:
        return False

    profile = search.pricing_profile(category) if hasattr(search, "pricing_profile") else category
    if profile == "consumer-retail":
        candidate = {
            "title": item.get("title", ""),
            "snippet": " ".join(item.get("passages") or [])[:4000],
            "query": item.get("query", ""),
            "url": item.get("url", ""),
        }
        try:
            return bool(search.exact_priced_product_candidate(candidate, query, item.get("text", "")))
        except Exception:
            return False

    try:
        return bool(search.has_commercial_price([item]))
    except Exception:
        return False


def _install_structured_evidence_export(search) -> None:
    """Attach retained evidence to completed jobs without changing the search loop."""
    if getattr(search, "_structured_evidence_export_installed", False):
        return

    original_evidence_ledger = search.evidence_ledger
    original_run = search._run

    def evidence_ledger_with_capture(evidence):
        _STRUCTURED_EVIDENCE_CONTEXT.records = structured_evidence_records(search, evidence)
        return original_evidence_ledger(evidence)

    def run_with_structured_evidence(app, job_id, query, history, model, allowed_only, uploaded_context=""):
        _STRUCTURED_EVIDENCE_CONTEXT.records = []
        try:
            return original_run(app, job_id, query, history, model, allowed_only, uploaded_context)
        finally:
            records = list(getattr(_STRUCTURED_EVIDENCE_CONTEXT, "records", []) or [])
            try:
                delattr(_STRUCTURED_EVIDENCE_CONTEXT, "records")
            except AttributeError:
                pass
            if not records:
                return

            market_records = [item for item in records if item.get("kind") == "market_source"]
            category = search.pricing_category(query)
            is_pricing = bool(
                search.pricing_intent(query, query)
                or search.implicit_product_pricing(query)
                or search.has_commercial_price(market_records)
            )
            commercial_price_found = False
            if is_pricing and market_records:
                try:
                    commercial_price_found = bool(
                        search.has_sufficient_commercial_benchmark(market_records, query, category)
                    )
                except Exception:
                    commercial_price_found = bool(search.has_commercial_price(market_records))

            for item in market_records:
                item["benchmark_eligible"] = bool(
                    commercial_price_found and _source_benchmark_eligible(search, item, query, category)
                )

            with search.LOCK:
                job = search.JOBS.get(job_id)
                if not job or str(job.get("status") or "").lower() != "completed":
                    return
                job["retained_evidence"] = records
                job["pricing_evidence"] = {
                    "is_pricing": is_pricing,
                    "category": category,
                    "commercial_price_found": commercial_price_found,
                    "retained_market_sources": len(market_records),
                    "benchmark_eligible_sources": sum(
                        1 for item in market_records if item.get("benchmark_eligible")
                    ),
                }

    search.evidence_ledger = evidence_ledger_with_capture
    search._run = run_with_structured_evidence
    search._structured_evidence_export_installed = True


def install_classification_coverage_guard(search) -> None:
    """Prevent an LLM coverage judgement from bypassing category price thresholds."""
    if getattr(search, "_classification_coverage_guard_installed", False):
        return

    original_assess_coverage = search.assess_coverage

    def assess_coverage(prompts, settings, model, rewritten_question, requirements, subquestions, queries, evidence):
        result = original_assess_coverage(
            prompts, settings, model, rewritten_question, requirements, subquestions, queries, evidence
        )
        category = search.pricing_category(rewritten_question)
        profile = search.pricing_profile(category) if hasattr(search, "pricing_profile") else category
        # HV-profile categories have their own stronger deterministic recovery policy.
        if profile == "hv-equipment":
            return result

        is_pricing = (
            search.pricing_request(rewritten_question)
            or search.implicit_product_pricing(rewritten_question)
            or search.has_commercial_price(evidence)
        )
        if not is_pricing:
            return result

        status = search.benchmark_status(evidence, rewritten_question, category)
        if status["sufficient"]:
            return result

        result = dict(result or {})
        existing_gaps = search.clean_items(result.get("gaps", []), 6)
        qualifier = "independent " if status["require_independent_domains"] else ""
        gap = (
            f"Commercial benchmark threshold not met: {status['qualifying_priced_sources']}/"
            f"{status['minimum_priced_sources']} {qualifier}priced sources"
        )
        result["complete"] = False
        result["gaps"] = [gap] + [item for item in existing_gaps if item.casefold() != gap.casefold()]

        deterministic = category_followup_queries(rewritten_question, profile)
        llm_queries = search.clean_queries(result.get("queries", []))
        result["queries"] = search.clean_queries(deterministic + llm_queries)[:4]
        return result

    search.assess_coverage = assess_coverage
    _install_structured_evidence_export(search)
    search._classification_coverage_guard_installed = True
