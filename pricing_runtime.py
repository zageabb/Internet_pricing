from __future__ import annotations

import math
from datetime import date


def _merge_candidate(pool: dict[str, dict], candidate: dict) -> None:
    """Keep one queued candidate per URL, preferring the richer search snippet."""
    url = str(candidate.get("url") or "")
    if not url:
        return
    existing = pool.get(url)
    if existing is None:
        pool[url] = dict(candidate)
        return
    if len(str(candidate.get("snippet") or "")) > len(str(existing.get("snippet") or "")):
        merged = dict(existing)
        merged.update(candidate)
        pool[url] = merged


def _fallback_state(discovered: int, relevant: int, attempted: int, readable: int) -> tuple[str, str]:
    if discovered == 0:
        return (
            "Web search returned no results; using model knowledge",
            "Public search engines returned no results for the request.",
        )
    if relevant == 0:
        return (
            "Web searched successfully; no equipment-relevant results found",
            f"{discovered} search results were found, but none passed the equipment-relevance gate.",
        )
    if attempted == 0:
        return (
            "Relevant web results found, but none could be attempted",
            f"{relevant} equipment-relevant candidates were identified but no page-read budget remained.",
        )
    if readable == 0:
        return (
            "Relevant web results found, but pages could not be read",
            f"{relevant} relevant candidates were found and {attempted} pages were attempted, but none produced readable evidence.",
        )
    return (
        "Web searched successfully, but no relevant pricing evidence was retained; using model knowledge",
        f"{discovered} search results → {relevant} equipment-relevant → {attempted} pages attempted → {readable} readable → 0 retained.",
    )


def _relaxed_queries(search, question: str, round_number: int, attempted_queries: list[str]) -> list[str]:
    factory = getattr(search, "hv_relaxed_queries", None)
    if not callable(factory):
        return []
    attempted = {" ".join(str(item).split()).casefold() for item in attempted_queries}
    rows = []
    for item in factory(question, round_number):
        clean = " ".join(str(item).split())[:300]
        if clean and clean.casefold() not in attempted and clean.casefold() not in {row.casefold() for row in rows}:
            rows.append(clean)
    return rows


def _safe_hv_followups(search, values, question: str) -> list[str]:
    rows = []
    checker = getattr(search, "hv_query_relevant", None)
    for value in search.clean_queries(values)[:6]:
        if callable(checker) and not checker(value, question):
            continue
        rows.append(value)
    return rows


def _collect_relevance(search, candidates: list[dict], question: str, category: str):
    """Return accepted candidates plus deterministic rejection counts for telemetry."""
    checker = getattr(search, "hv_candidate_relevance", None)
    if category != "hv-equipment" or not callable(checker):
        accepted = search.subject_relevant_candidates(candidates, question, category)
        return accepted, {}
    accepted, rejected = [], {}
    for candidate in candidates:
        ok, reason, score = checker(candidate, question)
        if not ok:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        item = dict(candidate)
        item["subject_relevance_score"] = round(float(score), 3)
        accepted.append(item)
    return accepted, rejected


def install_hv_runtime(search) -> None:
    """Replace only the HV research loop; all other categories retain the legacy runner."""
    if getattr(search, "_hv_relevance_runtime_installed", False):
        return
    original_run = search._run

    def run(app, job_id, query, history, model, allowed_only, uploaded_context=""):
        route_text = f"{query}\n{uploaded_context}"
        if search.pricing_category(route_text) != "hv-equipment":
            return original_run(app, job_id, query, history, model, allowed_only, uploaded_context)
        return _run_hv(search, app, job_id, query, history, model, allowed_only, uploaded_context)

    search._run = run
    search._hv_relevance_runtime_installed = True


def _run_hv(search, app, job_id, query, history, model, allowed_only, uploaded_context=""):
    search.update(job_id, status="running", phase="Planning research", started_at=search.now())
    try:
        settings = search.get_settings()
        model = model or settings["model"]
        market = search.market_context(settings)
        allowed = search.domains(settings["allowed_domains"]) if allowed_only else []
        blocked = search.domains(settings["blocked_domains"])
        scope = "Only: " + ", ".join(allowed) if allowed else "Any public website except blocked domains"
        prompts = search.PROMPTS.load()
        context = "\n\n".join(f"{x['role'].title()}: {x['content']}" for x in history[-12:])
        effective_query = query if not context else f"Conversation context:\n{context}\n\nCurrent request:\n{query}"
        if uploaded_context:
            effective_query = f"{effective_query}\n\n{uploaded_context}"
            search.event(job_id, "document", "returned", "Included uploaded document context",
                         f"{len(uploaded_context):,} characters available")

        planning = search.render(prompts["planning"], market=market, scope=scope, query=effective_query)
        search.event(job_id, "phase", "running", "Understanding and improving the request",
                     phase="Planning response")
        parsed = search.ollama_json(settings["ollama_url"], model, planning)
        rewritten_question = search.clean_text(parsed.get("rewritten_question"), effective_query)
        requirements = search.clean_items(parsed.get("requirements", []), 8)
        subquestions = search.clean_items(parsed.get("subquestions", []), 5)
        category_query = query if query.strip() else effective_query
        inferred_category = search.pricing_category(category_query)
        is_pricing = search.pricing_intent(effective_query, rewritten_question) or search.implicit_product_pricing(category_query)
        price_category = inferred_category if is_pricing else "none"
        needs_web = is_pricing or parsed.get("needs_web") is True
        queries = search.clean_queries(parsed.get("queries", []))
        if needs_web and not queries:
            queries = [query, f"{query} authoritative source", f"{query} {market}"]
        if needs_web and is_pricing:
            queries = search.pricing_queries(query, queries, price_category)
        queries = queries[:6]

        route = "web research" if needs_web else "model knowledge"
        search.event(job_id, "reasoning", "summary", f"Using {route}", rewritten_question,
                     phase="Planning complete")
        if is_pricing:
            search.event(job_id, "reasoning", "summary", f"Pricing strategy: {price_category}",
                         search.pricing_strategy_context(price_category))
        if subquestions:
            search.event(job_id, "reasoning", "summary",
                         f"Identified {len(subquestions)} supporting questions", "; ".join(subquestions))

        if not needs_web:
            direct_prompt = search.direct_answer_prompt(
                prompts, settings, market, effective_query, rewritten_question,
                requirements, subquestions, "Not needed for this request",
            )
            search.event(job_id, "phase", "running", "Answering from model knowledge",
                         phase="Producing answer")
            answer = search.ollama_text(settings["ollama_url"], model, direct_prompt)
            answer = search.review_answer(
                job_id, prompts, settings, model, effective_query, rewritten_question,
                requirements, subquestions, answer, "No web evidence (model knowledge answer)",
            )
            search.update(
                job_id, status="completed", phase="Complete", message=answer, sources=[],
                steps=[f"Ollama model: {model}", "Route: model knowledge",
                       f"Clarified request: {rewritten_question}", "Final answer reviewed"],
                completed_at=search.now(),
            )
            search.event(job_id, "phase", "returned", "Answer completed", phase="Complete")
            return

        evidence: list[dict] = []
        attempted_queries: list[str] = []
        current_queries = queries
        candidate_pool: dict[str, dict] = {}
        discovered_urls: set[str] = set()
        relevant_urls: set[str] = set()
        attempted_urls: set[str] = set()
        readable_urls: set[str] = set()
        rejection_counts: dict[str, int] = {}
        max_pages = int(settings["max_pages_to_read"])
        max_rounds = int(settings["max_search_rounds"])

        for round_number in range(1, max_rounds + 1):
            search.event(job_id, "phase", "running", f"Research round {round_number}",
                         phase=f"Searching — round {round_number}")
            new_candidates: list[dict] = []

            if round_number == 1 and price_category in {"hv-equipment", "industrial", "service-project"}:
                indexed = search.search_procurement(
                    rewritten_question, limit=max(10, settings["results_per_query"] * 2)
                )
                search.event(job_id, "index", "returned", "Searched local procurement index",
                             f"{len(indexed)} structured notices returned")
                for row in indexed:
                    url = search.canonical_url(str(row.get("url") or ""))
                    if not url or url in attempted_urls:
                        continue
                    host = search.hostname(url)
                    if any(host == domain or host.endswith("." + domain) for domain in blocked):
                        continue
                    discovered_urls.add(url)
                    item = dict(row)
                    item["url"] = url
                    item.setdefault("query", "local procurement index")
                    item.setdefault("title", url)
                    item.setdefault("snippet", str(item.get("indexed_text") or "")[:4000])
                    new_candidates.append(item)

            for search_query in current_queries:
                attempted_queries.append(search_query)
                search.event(job_id, "search", "initiated", search_query)
                rows, engine_status = search.search_web(
                    search_query, settings["search_backend"], settings["results_per_query"]
                )
                if not rows:
                    search.event(job_id, "search", "failed", search_query,
                                 "; ".join(engine_status) or "No results")
                    continue
                search.event(
                    job_id, "search", "returned", search_query,
                    f"{len(rows)} merged results · " + "; ".join(engine_status),
                )
                for row in rows:
                    url = search.canonical_url(str(row.get("href") or row.get("url") or ""))
                    host = search.hostname(url)
                    if not host or url in attempted_urls or any(
                        host == d or host.endswith("." + d) for d in blocked
                    ):
                        continue
                    if allowed and not any(host == d or host.endswith("." + d) for d in allowed):
                        continue
                    discovered_urls.add(url)
                    new_candidates.append({
                        "title": str(row.get("title") or url),
                        "url": url,
                        "snippet": str(row.get("body") or ""),
                        "query": search_query,
                        "published_at": str(row.get("date") or row.get("published") or ""),
                        "search_backend": str(row.get("search_backend") or ""),
                    })

            relevant, rejected = _collect_relevance(
                search, new_candidates, rewritten_question, price_category
            )
            for reason, count in rejected.items():
                rejection_counts[reason] = rejection_counts.get(reason, 0) + count
            for candidate in relevant:
                relevant_urls.add(candidate["url"])
                if candidate["url"] not in attempted_urls:
                    _merge_candidate(candidate_pool, candidate)

            filtered_count = len(new_candidates) - len(relevant)
            if new_candidates:
                detail = (
                    f"{len(new_candidates)} candidates discovered this round · "
                    f"{len(relevant)} equipment-relevant · {filtered_count} filtered"
                )
                if rejected:
                    detail += " · " + ", ".join(
                        f"{key}={value}" for key, value in sorted(rejected.items())
                    )
                search.event(job_id, "reasoning", "summary",
                             "Applied equipment-relevance gate", detail)

            remaining_pages = max_pages - len(attempted_urls)
            if remaining_pages <= 0:
                break
            remaining_rounds = max_rounds - round_number + 1
            round_attempt_budget = (
                remaining_pages if remaining_rounds == 1
                else max(1, math.ceil(remaining_pages / remaining_rounds))
            )
            attempts_this_round = 0

            while candidate_pool and attempts_this_round < round_attempt_budget:
                queued = list(candidate_pool.values())
                ranked = search.rank_candidates(
                    queued, rewritten_question, requirements, subquestions, price_category
                )
                ranked = search.embedding_rerank(
                    job_id, settings, ranked,
                    search.research_text(rewritten_question, requirements, subquestions),
                )
                if not ranked:
                    break
                batch_size = min(
                    max(1, int(settings["max_fetch_workers"])),
                    round_attempt_budget - attempts_this_round,
                    len(ranked),
                )
                batch = ranked[:batch_size]
                for candidate in batch:
                    attempted_urls.add(candidate["url"])
                    candidate_pool.pop(candidate["url"], None)
                attempts_this_round += len(batch)

                fetched = search.fetch_pages(job_id, batch, settings["max_fetch_workers"])
                for candidate in batch:
                    title = candidate.get("title") or candidate["url"]
                    url = candidate["url"]
                    snippet = str(candidate.get("snippet") or "")
                    source_query = str(candidate.get("query") or "research candidate")
                    source_id = len(evidence) + 1
                    page = fetched.get(url, {})
                    if page.get("error"):
                        if len(snippet.strip()) < 80:
                            search.event(job_id, "site", "failed", title, page["error"], url)
                            continue
                        search.event(
                            job_id, "site", "partial", title,
                            f"Page unavailable ({page['error']}); evaluating indexed search passage",
                            url,
                        )
                        page = {
                            "text": snippet, "url": url,
                            "content_type": "text/search-snippet",
                            "published_at": candidate.get("published_at", ""),
                        }

                    text, page["content_type"] = search.merge_page_and_snippet(
                        page.get("text"), snippet, page.get("content_type", "")
                    )
                    if len(text.strip()) < 40:
                        search.event(job_id, "site", "unreadable", title,
                                     "No readable evidence", url)
                        continue
                    readable_urls.add(url)

                    passages = search.best_passages(
                        text,
                        search.research_text(rewritten_question, requirements, subquestions),
                        limit=4, max_chars=6_000,
                    )
                    focused_text = "\n\n".join(passages) or text[:12_000]
                    if search.exact_priced_product_candidate(
                        candidate, rewritten_question, focused_text
                    ):
                        verdict, reason = (
                            "useful",
                            "Exact requested product/specification with a visible commercial price",
                        )
                        claims = search.best_passages(
                            focused_text, f"{rewritten_question} price",
                            limit=3, max_chars=1_500,
                        )
                    else:
                        review_query = (
                            f"{source_query}\nPricing strategy: "
                            f"{search.pricing_strategy_context(price_category)}"
                        )
                        verdict, reason, claims = search.analyse_source(
                            prompts, settings, model, review_query, title, url, focused_text
                        )
                    if verdict != "useful":
                        code = "SOURCE_REVIEW_REJECTED" if verdict == "unusable" else "SOURCE_REVIEW_FAILED"
                        rejection_counts[code] = rejection_counts.get(code, 0) + 1
                        if verdict == "unusable":
                            reason = f"Not retained: {reason}"
                        search.event(job_id, "site", "failed", title, f"{code}: {reason}", url)
                        continue

                    search.record_domain_verdict(search.hostname(url), True)
                    evidence.append({
                        "source_id": source_id,
                        "title": title,
                        "url": url,
                        "query": source_query,
                        "passages": passages,
                        "claims": claims,
                        "text": focused_text[:12_000],
                        "relevance": candidate.get("score", 0),
                        "published_at": page.get("published_at") or candidate.get("published_at", ""),
                        "obtained_at": date.today().isoformat(),
                        "content_type": page.get("content_type", ""),
                    })
                    search.event(
                        job_id, "site", "returned", title,
                        f"Source {source_id} retained · {reason}", url,
                    )

            if is_pricing and search.has_sufficient_commercial_benchmark(
                evidence, category_query, price_category
            ):
                search.event(
                    job_id, "reasoning", "returned", "Commercial benchmark found",
                    "Comparable price evidence found; proceeding to the estimate",
                )
                break
            if round_number == max_rounds or len(attempted_urls) >= max_pages:
                break

            coverage = (
                search.assess_coverage(
                    prompts, settings, model, rewritten_question, requirements,
                    subquestions, attempted_queries, evidence,
                )
                if evidence else
                {"complete": False, "covered": [], "gaps": ["No usable evidence retained"], "queries": []}
            )
            gaps = search.clean_items(coverage.get("gaps", []), 6)
            llm_followups = _safe_hv_followups(
                search, coverage.get("queries", []), rewritten_question
            )
            deterministic = _relaxed_queries(
                search, rewritten_question, round_number + 1, attempted_queries
            )
            current_queries = search.clean_queries(llm_followups + deterministic)[:4]

            if gaps:
                search.event(
                    job_id, "reasoning", "summary",
                    f"Research found {len(gaps)} evidence gap(s)", "; ".join(gaps),
                )
            if current_queries:
                search.event(
                    job_id, "reasoning", "summary",
                    "Relaxing the next HV search without relaxing the target specification",
                    "; ".join(current_queries),
                )
            elif candidate_pool:
                search.event(
                    job_id, "reasoning", "summary",
                    "Continuing with queued relevant candidates",
                    f"{len(candidate_pool)} previously discovered candidates remain unread",
                )
            elif evidence:
                search.event(
                    job_id, "reasoning", "summary",
                    "No productive follow-up search identified",
                    "Proceeding with available evidence and explicit uncertainty",
                )
                break

        diagnostics = (
            f"{len(discovered_urls)} search results → {len(relevant_urls)} equipment-relevant → "
            f"{len(attempted_urls)} pages attempted → {len(readable_urls)} readable → "
            f"{len(evidence)} retained"
        )
        if rejection_counts:
            diagnostics += " · rejected: " + ", ".join(
                f"{key}={value}" for key, value in sorted(rejection_counts.items())
            )
        search.event(job_id, "reasoning", "summary", "Research diagnostics", diagnostics)

        if not evidence:
            label, detail = _fallback_state(
                len(discovered_urls), len(relevant_urls), len(attempted_urls), len(readable_urls)
            )
            direct_prompt = search.direct_answer_prompt(
                prompts, settings, market, effective_query, rewritten_question,
                requirements, subquestions,
                f"{detail} Answer cautiously from model knowledge.",
            )
            search.event(job_id, "phase", "running", label, detail, phase="Producing answer")
            answer = search.ollama_text(settings["ollama_url"], model, direct_prompt)
            answer = search.review_answer(
                job_id, prompts, settings, model, effective_query, rewritten_question,
                requirements, subquestions, answer, detail,
            )
            search.update(
                job_id, status="completed", phase="Complete", message=answer, sources=[],
                steps=[
                    f"Ollama model: {model}",
                    "Route: model knowledge after web evidence rejection",
                    f"Search results discovered: {len(discovered_urls)}",
                    f"Equipment-relevant candidates: {len(relevant_urls)}",
                    f"Pages attempted: {len(attempted_urls)}",
                    f"Readable pages: {len(readable_urls)}",
                    "Sources retained: 0",
                    f"Clarified request: {rewritten_question}",
                    "Final answer reviewed",
                ],
                completed_at=search.now(),
            )
            search.event(job_id, "phase", "returned", "Fallback answer completed",
                         phase="Complete")
            return

        commercial_price_found = search.has_sufficient_commercial_benchmark(
            evidence, category_query, price_category
        )
        if is_pricing:
            fx = search.currency_conversion_evidence(evidence)
            if fx:
                fx["source_id"] = len(evidence) + 1
                evidence.append(fx)
                search.event(
                    job_id, "currency", "returned",
                    "Loaded dated reference exchange rates",
                    f"Approximate USD, EUR and GBP conversions · {fx['published_at']}",
                    fx["url"],
                )
            else:
                search.event(
                    job_id, "currency", "failed",
                    "Reference exchange rates unavailable",
                    "Report will preserve source currencies without inventing conversions",
                )

        evidence_text = search.evidence_ledger(evidence)
        answer_prompt = search.render(
            prompts["answer"], date=date.today(), market=market, scope=scope,
            query=effective_query, rewritten_question=rewritten_question,
            requirements="; ".join(requirements) or "None specified",
            subquestions="; ".join(subquestions) or "None",
            evidence=evidence_text[:60_000],
        )
        allow_indicative = is_pricing and not commercial_price_found
        if allow_indicative:
            answer_prompt = (
                "Commercial evidence limitation: the retained sources contain no concrete usable price. "
                "Provide a concise indicative model-knowledge low/base/high budget anyway, clearly label it "
                "as not web-verified, state scope and confidence, and keep it separate from cited facts.\n\n"
                + answer_prompt
            )
        instructions = settings["general_search_instructions"].strip()
        if instructions:
            answer_prompt = f"Persistent user instructions:\n{instructions}\n\n{answer_prompt}"

        search.event(
            job_id, "phase", "running", f"Synthesising from {len(evidence)} sources",
            phase="Producing answer",
        )
        answer = search.ollama_text(settings["ollama_url"], model, answer_prompt)
        answer = search.review_answer(
            job_id, prompts, settings, model, effective_query, rewritten_question,
            requirements, subquestions, answer, evidence_text,
            allow_indicative=allow_indicative,
        )
        answer = search.verify_citations(
            job_id, prompts, settings, model, rewritten_question, answer,
            evidence_text, evidence, allow_indicative=allow_indicative,
        )
        sources = [{
            "source_id": item["source_id"],
            "title": item["title"],
            "url": item["url"],
            "published_at": item.get("published_at", ""),
            "obtained_at": item["obtained_at"],
        } for item in evidence]
        search.update(
            job_id, status="completed", phase="Complete", message=answer, sources=sources,
            steps=[
                f"Ollama model: {model}",
                f"Ran {len(attempted_queries)} targeted searches",
                f"Pricing strategy: {price_category}",
                f"Search results discovered: {len(discovered_urls)}",
                f"Equipment-relevant candidates: {len(relevant_urls)}",
                f"Pages attempted: {len(attempted_urls)}",
                f"Retained {len(evidence)} ranked sources",
                "Evidence coverage and citations reviewed",
            ],
            completed_at=search.now(),
        )
        search.event(job_id, "phase", "returned", "Research answer completed",
                     phase="Complete")
    except Exception as exc:
        search.update(job_id, status="failed", phase="Failed", error=str(exc),
                      completed_at=search.now())
        search.event(job_id, "phase", "failed", f"Search failed: {exc}", phase="Failed")
