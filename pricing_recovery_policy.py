from __future__ import annotations

import re
from urllib.parse import urlparse

import browser_fetch


PRICE_RE = re.compile(
    r"(?:GBP|USD|EUR|INR|JPY|CNY|AUD|CAD|CHF|£|€|\$|₹|¥)\s*\d[\d,.]*(?:\s*(?:million|billion|thousand|[kmb]))?|"
    r"\d[\d,.]*(?:\s*(?:million|billion|thousand|[kmb]))?\s*(?:GBP|USD|EUR|INR|JPY|CNY|AUD|CAD|CHF)",
    re.I,
)

COMMERCIAL_HINTS = (
    "unit price", "unit rate", "per panel", "each panel", "line item", "boq", "bill of quantities",
    "winning bid", "awarded value", "award value", "commercial offer", "quotation", "purchase order",
    "shipment", "transaction", "customs", "import", "export", "invoice",
)

STRONG_TRANSACTION_HOSTS = {"tenderkart.in", "volza.com", "zauba.com"}


def _compact(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _rating_tokens(value: str, unit: str) -> list[str]:
    pattern = rf"\b\d+(?:[.,]\d+)?\s*{re.escape(unit)}\b"
    rows = []
    for match in re.finditer(pattern, str(value or ""), re.I):
        token = re.sub(r"\s+", "", match.group(0))
        token = token[:-len(unit)] + unit
        if token.lower() not in {row.lower() for row in rows}:
            rows.append(token)
    return rows


def _context_current(value: str, words: tuple[str, ...]) -> str:
    text = _compact(value)
    for word in words:
        after = re.search(rf"\b{re.escape(word)}s?\b[^,;:.]{{0,28}}?\b(\d+(?:[.,]\d+)?\s*A)\b", text, re.I)
        if after:
            return re.sub(r"\s+", "", after.group(1))
        before = re.search(rf"\b(\d+(?:[.,]\d+)?\s*A)\b\s+(?:rated\s+)?{re.escape(word)}s?\b", text, re.I)
        if before:
            return re.sub(r"\s+", "", before.group(1))
    return ""


def hv_price_recovery_queries(question: str) -> list[str]:
    """Return price-first HV searches used when retained evidence is only technical."""
    base = _compact(question)
    voltage = (_rating_tokens(base, "kV") or ["11kV"])[0]
    faults = _rating_tokens(base, "kA")
    fault = faults[0] if faults else ""
    incomer = _context_current(base, ("incomer", "incoming"))
    feeder = _context_current(base, ("feeder", "outgoing"))

    values = [
        f'TenderKart "{voltage}" "{feeder}" "{fault}" VCB panel award price' if feeder else "",
        f'Volza "{voltage}" "{incomer}" "{fault}" switchgear transaction value' if incomer else "",
        f'"{voltage}" "{feeder}" VCB panel BOQ winning bid unit price' if feeder else "",
        f'"{voltage}" "{incomer}" incomer switchgear import export customs price' if incomer else "",
        f'Zauba "{voltage}" switchgear import price transaction',
        f'"{voltage}" "{fault}" switchgear quotation commercial offer price' if fault else f'"{voltage}" switchgear quotation commercial offer price',
    ]
    return list(dict.fromkeys(_compact(value)[:300] for value in values if _compact(value)))


def _has_visible_price(value: str) -> bool:
    text = str(value or "")
    return bool(PRICE_RE.search(text) or browser_fetch.has_price_signal(text))


def _deterministic_hv_price_evidence(search, query: str, title: str, url: str, content: str):
    """Recognise obvious line-item/transaction price evidence without depending on LLM source review."""
    if search.pricing_category(query) != "hv-equipment":
        return False, []
    if not _has_visible_price(content):
        return False, []

    checker = getattr(search, "hv_candidate_relevance", None)
    if callable(checker):
        ok, _reason, _score = checker({"title": title, "snippet": content[:5000], "url": url}, query)
        if not ok:
            return False, []

    lower = f"{title}\n{content}".lower()
    line_level = any(hint in lower for hint in COMMERCIAL_HINTS)
    unrelated_project_parts = sum(1 for token in (
        "transformer", "dg set", "diesel generator", "lt panel", "low voltage board", "civil works", "cables",
    ) if token in lower)
    if unrelated_project_parts >= 2 and not line_level:
        return False, []

    host = (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")
    if not line_level and host not in STRONG_TRANSACTION_HOSTS:
        return False, []

    claims = search.best_passages(
        content,
        f"{query} price unit rate award winning bid quotation transaction import export",
        limit=4,
        max_chars=2200,
    )
    return True, claims


def _needs_indicative_budget(answer: str) -> bool:
    """Require an explicit fallback budget; incidental currency/FX is not enough."""
    lower = str(answer or "").lower()
    explicit_fallback = (
        "not web-verified" in lower
        and "low" in lower
        and "base" in lower
        and "high" in lower
    )
    return not explicit_fallback


def _model_budget_supplement(search, settings, model, question: str, *, headline_fallback: bool, answer: str = "") -> str:
    if headline_fallback:
        instruction = """The web research did not find a usable commercial price for the main requested equipment. Provide the final fallback budget from general model knowledge. Give a concise low/base/high EQUIPMENT-ONLY range and a suggested estimating figure. Then give optional percentage/range allowances for relevant accessories and package items such as protection/control, metering, engineering, spares, freight, erection/testing/commissioning and contingency. Do not claim these are current quotes or web evidence. Put `NOT WEB-VERIFIED` prominently in the heading and state low confidence. Do not invent citations or exchange rates."""
    else:
        instruction = """The answer already contains web-backed evidence for the main equipment price. Add only a concise budgeting breakdown from general model knowledge for accessories/package allowances such as protection/control, metering, engineering, spares, freight, erection/testing/commissioning and contingency. Express these primarily as percentage or range allowances relative to the web-backed equipment subtotal. Do NOT provide a competing headline equipment price. Put `NOT WEB-VERIFIED` prominently in the heading and do not invent citations or current exchange rates."""

    prompt = f"""You are producing a small supplementary section for Internet Pricing.

{instruction}

Requested equipment:
{question}

Existing answer context:
{str(answer or '')[:9000]}

Return only the Markdown section to append, with no preamble."""
    try:
        return search.ollama_text(settings["ollama_url"], model, prompt).strip()
    except Exception:
        return ""


def install_pricing_recovery_policy(search) -> None:
    """Install HV price recovery, sensible FX behaviour, and model-knowledge fallback boundaries."""
    if getattr(search, "_pricing_recovery_policy_installed", False):
        return

    original_assess_coverage = search.assess_coverage
    original_analyse_source = search.analyse_source
    original_currency_evidence = search.currency_conversion_evidence
    original_review_answer = search.review_answer
    original_verify_citations = search.verify_citations

    def assess_coverage(prompts, settings, model, rewritten_question, requirements, subquestions, queries, evidence):
        result = original_assess_coverage(
            prompts, settings, model, rewritten_question, requirements, subquestions, queries, evidence
        )
        if search.pricing_category(rewritten_question) != "hv-equipment":
            return result
        if search.has_sufficient_commercial_benchmark(evidence, rewritten_question, "hv-equipment"):
            return result

        result = dict(result or {})
        gaps = search.clean_items(result.get("gaps", []), 6)
        price_gap = "No sufficiently comparable commercial price benchmark retained yet"
        result["complete"] = False
        result["gaps"] = [price_gap] + [gap for gap in gaps if gap.casefold() != price_gap.casefold()]
        # Put deterministic price searches first because pricing_runtime truncates the
        # combined follow-up list. Technical follow-ups must not crowd these out.
        result["queries"] = hv_price_recovery_queries(rewritten_question)[:4]
        return result

    def analyse_source(prompts, settings, model, query, title, url, content):
        deterministic, claims = _deterministic_hv_price_evidence(search, query, title, url, content)
        if deterministic:
            return (
                "useful",
                "Deterministically retained price-bearing HV tender/transaction evidence",
                claims,
            )
        return original_analyse_source(prompts, settings, model, query, title, url, content)

    def currency_conversion_evidence(evidence):
        # Do not add an FX source to a technical-only evidence set. There is no
        # monetary value to convert, and doing so makes the final source list misleading.
        if not search.has_commercial_price(evidence):
            return None
        return original_currency_evidence(evidence)

    def review_answer(job_id, prompts, settings, model, query, rewritten_question, requirements, subquestions,
                      answer, evidence, allow_indicative=False):
        reviewed = original_review_answer(
            job_id, prompts, settings, model, query, rewritten_question, requirements,
            subquestions, answer, evidence, allow_indicative=allow_indicative,
        )
        if search.pricing_category(rewritten_question) != "hv-equipment":
            return reviewed

        evidence_text = str(evidence or "").lower()
        final_web_fallback = (
            allow_indicative
            or "0 retained" in evidence_text
            or "no readable web evidence" in evidence_text
            or "no usable evidence" in evidence_text
            or "no relevant pricing evidence" in evidence_text
            or "returned no results" in evidence_text
            or "none passed the equipment-relevance gate" in evidence_text
            or "no page-read budget" in evidence_text
            or "none produced readable evidence" in evidence_text
        )
        if final_web_fallback and _needs_indicative_budget(reviewed):
            supplement = _model_budget_supplement(
                search, settings, model, rewritten_question,
                headline_fallback=True, answer=reviewed,
            )
            if supplement:
                return reviewed.rstrip() + "\n\n" + supplement
        return reviewed

    def verify_citations(job_id, prompts, settings, model, rewritten_question, answer, evidence_text, evidence,
                         allow_indicative=False):
        verified = original_verify_citations(
            job_id, prompts, settings, model, rewritten_question, answer,
            evidence_text, evidence, allow_indicative=allow_indicative,
        )
        if search.pricing_category(rewritten_question) != "hv-equipment":
            return verified

        if allow_indicative:
            if _needs_indicative_budget(verified):
                supplement = _model_budget_supplement(
                    search, settings, model, rewritten_question,
                    headline_fallback=True, answer=verified,
                )
                if supplement:
                    verified = verified.rstrip() + "\n\n" + supplement
            return verified

        # Web-backed main pricing should remain authoritative. Model knowledge is
        # useful here only as a clearly separated estimating breakdown.
        if "not web-verified" not in verified.lower():
            supplement = _model_budget_supplement(
                search, settings, model, rewritten_question,
                headline_fallback=False, answer=verified,
            )
            if supplement:
                verified = verified.rstrip() + "\n\n" + supplement
        return verified

    search.hv_price_recovery_queries = hv_price_recovery_queries
    search.assess_coverage = assess_coverage
    search.analyse_source = analyse_source
    search.currency_conversion_evidence = currency_conversion_evidence
    search.review_answer = review_answer
    search.verify_citations = verify_citations
    search._pricing_recovery_policy_installed = True
