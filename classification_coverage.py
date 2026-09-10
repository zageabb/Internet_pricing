from __future__ import annotations


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
    search._classification_coverage_guard_installed = True
