from __future__ import annotations

import os
import threading

import classification_policy


_CONTEXT = threading.local()


def _confidence_threshold() -> float:
    try:
        value = float(os.environ.get("INTERNET_PRICING_CLASSIFIER_MIN_CONFIDENCE", "0.70"))
    except (TypeError, ValueError):
        value = 0.70
    return max(0.50, min(0.95, value))


def _category_catalog(rules: dict) -> list[dict]:
    rows = []
    for category_id in classification_policy.get_category_order(rules, include_disabled=False):
        rule = rules["categories"].get(category_id) or {}
        rows.append({
            "id": category_id,
            "name": str(rule.get("label") or category_id),
            "search_profile": classification_policy.category_profile(category_id, rules),
            "purpose": str(rule.get("strategy") or "")[:1200],
            "examples_or_hints": list(rule.get("phrases") or [])[:12] + list(rule.get("keywords") or [])[:12],
        })
    return rows


def _normalise_confidence(value) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence > 1.0 and confidence <= 100.0:
        confidence /= 100.0
    return max(0.0, min(1.0, confidence))


def _resolve_proposed_category(value, rules: dict) -> str | None:
    proposed = str(value or "").strip().casefold()
    if not proposed:
        return None
    categories = rules.get("categories") or {}
    for category_id, rule in categories.items():
        if not bool(rule.get("enabled", True)):
            continue
        if proposed == category_id.casefold() or proposed == str(rule.get("label") or "").strip().casefold():
            return category_id
    return None


def _report_for_category(category_id: str, reason: str, method: str, confidence: float | None,
                         deterministic: dict, rules: dict, llm_proposal: dict | None = None) -> dict:
    rule = rules["categories"][category_id]
    active_order = classification_policy.get_category_order(rules, include_disabled=False)
    result = {
        "query": deterministic.get("query", ""),
        "category": category_id,
        "label": rule["label"],
        "reason": reason,
        "method": method,
        "confidence": confidence,
        "confidence_threshold": _confidence_threshold(),
        "priority": active_order.index(category_id) + 1 if category_id in active_order else None,
        "enabled": bool(rule.get("enabled", True)),
        "search_profile": classification_policy.category_profile(category_id, rules),
        "min_priced_sources": rule["min_priced_sources"],
        "require_independent_domains": rule["require_independent_domains"],
        "strategy": rule["strategy"],
        "deterministic_category": deterministic.get("category"),
        "deterministic_label": deterministic.get("label"),
        "deterministic_reason": deterministic.get("reason"),
    }
    if llm_proposal:
        result["llm_proposal"] = llm_proposal
    return result


def hybrid_classification_report(search, query: str, model: str = "", settings: dict | None = None) -> dict:
    """Let the LLM propose a semantic category, then validate it in deterministic code.

    Code remains authoritative over the category registry, enabled state, search profile,
    evidence thresholds and stopping safeguards. The deterministic classifier is the
    fallback if the LLM is unavailable, invalid or below the confidence threshold.
    """
    query = " ".join(str(query or "").split())[:20_000]
    rules = classification_policy.get_classification_rules()
    deterministic = classification_policy.classification_report(query)
    if not query:
        return _report_for_category(
            deterministic["category"], deterministic["reason"], "deterministic-fallback", None,
            deterministic, rules,
        )

    catalog = _category_catalog(rules)
    prompt = f"""You are the semantic category classifier for an Internet Pricing research application.

Choose exactly ONE category from the enabled category catalogue below. Infer the real product/equipment/service family from meaning and technical context; do not require literal keyword matches. Do not invent categories. If none of the specialist categories is a good semantic fit, choose general-product.

Return JSON only:
{{
  "category": "exact-category-id",
  "confidence": 0.0,
  "reason": "one concise sentence explaining the semantic choice"
}}

Confidence must be between 0 and 1. Use high confidence only when the category is clear from the request.

Enabled categories:
{catalog}

Research request:
{query}
"""

    try:
        settings = settings or search.get_settings()
        selected_model = model or settings.get("model") or ""
        parsed = search.ollama_json(settings["ollama_url"], selected_model, prompt)
        proposed_id = _resolve_proposed_category(parsed.get("category"), rules)
        confidence = _normalise_confidence(parsed.get("confidence"))
        llm_reason = " ".join(str(parsed.get("reason") or "").split())[:600]
        proposal = {
            "category": proposed_id or str(parsed.get("category") or "").strip(),
            "confidence": confidence,
            "reason": llm_reason,
            "model": selected_model,
        }
        if proposed_id and confidence >= _confidence_threshold():
            reason = llm_reason or f"LLM semantic classification selected {rules['categories'][proposed_id]['label']}"
            return _report_for_category(
                proposed_id, reason, "llm", confidence, deterministic, rules, proposal,
            )

        if not proposed_id:
            fallback_reason = "LLM proposed an unknown or disabled category; deterministic classification used"
        else:
            fallback_reason = (
                f"LLM confidence {confidence:.2f} was below the {_confidence_threshold():.2f} threshold; "
                "deterministic classification used"
            )
        return _report_for_category(
            deterministic["category"], fallback_reason, "deterministic-fallback", confidence,
            deterministic, rules, proposal,
        )
    except Exception as exc:
        proposal = {"error": str(exc)[:500]}
        return _report_for_category(
            deterministic["category"],
            "LLM classification was unavailable; deterministic classification used",
            "deterministic-fallback", None, deterministic, rules, proposal,
        )


def _active_category() -> str | None:
    return getattr(_CONTEXT, "category", None)


def _active_request_query() -> str:
    """Return the exact user/document-derived request that started the active research job.

    Downstream policies use this instead of an LLM rewrite when product identity or
    equipment ratings must remain invariant throughout search, evidence validation and
    answer review.
    """
    return str(getattr(_CONTEXT, "request_query", "") or "")


def _active_classification_report() -> dict | None:
    report = getattr(_CONTEXT, "report", None)
    return dict(report) if isinstance(report, dict) else None


def _set_context(report: dict | None, request_query: str = "") -> None:
    if report:
        _CONTEXT.category = report.get("category")
        _CONTEXT.report = report
        _CONTEXT.request_query = " ".join(str(request_query or report.get("query") or "").split())[:20_000]
    else:
        for name in ("category", "report", "request_query"):
            if hasattr(_CONTEXT, name):
                delattr(_CONTEXT, name)


def install_hybrid_classification(search) -> None:
    """Make semantic classification the outermost per-job routing decision."""
    if getattr(search, "_hybrid_classification_installed", False):
        return

    deterministic_pricing_category = search.pricing_category
    original_run = search._run

    def pricing_category(query):
        active = _active_category()
        if active:
            return active
        return deterministic_pricing_category(query)

    def run(app, job_id, query, history, model, allowed_only, uploaded_context=""):
        settings = search.get_settings()
        selected_model = model or settings.get("model") or ""
        classification_input = query
        if uploaded_context:
            classification_input = f"{query}\n\n{uploaded_context}"
        report = hybrid_classification_report(
            search, classification_input, selected_model, settings=settings
        )
        _set_context(report, query)
        try:
            method = "LLM semantic classifier" if report["method"] == "llm" else "deterministic fallback"
            confidence = "" if report.get("confidence") is None else f" · confidence {report['confidence']:.2f}"
            baseline = report.get("deterministic_label") or report.get("deterministic_category") or "unknown"
            detail = (
                f"{method}{confidence} · search profile {report['search_profile']} · "
                f"deterministic baseline: {baseline} · {report['reason']}"
            )
            search.event(
                job_id, "reasoning", "summary",
                f"Classification: {report['label']}", detail,
                phase="Classifying request",
            )

            prepare = getattr(search, "prepare_expansion_plan", None)
            if callable(prepare):
                try:
                    plan = prepare(query, selected_model, settings, report.get("category")) or {}
                    counts = [f"{name}={len(plan.get(name, []))}" for name in ("canonical", "near", "adjacent", "broad")]
                    if any(plan.get(name) for name in ("canonical", "near", "adjacent", "broad")):
                        search.event(
                            job_id, "reasoning", "summary", "Prepared search expansion ladder",
                            " · ".join(counts) + " · aliases/comparators are search hypotheses until source review",
                            phase="Classifying request",
                        )
                except Exception as exc:
                    search.event(
                        job_id, "reasoning", "failed", "Search expansion planning unavailable",
                        str(exc)[:500], phase="Classifying request",
                    )

            return original_run(app, job_id, query, history, model, allowed_only, uploaded_context)
        finally:
            _set_context(None)

    search.deterministic_pricing_category = deterministic_pricing_category
    search.hybrid_classification_report = lambda query, model="": hybrid_classification_report(search, query, model)
    search.active_request_query = _active_request_query
    search.active_classification_report = _active_classification_report
    search.pricing_category = pricing_category
    search._run = run
    search._hybrid_classification_installed = True
