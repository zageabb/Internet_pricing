from __future__ import annotations


def install_category_profile_runtime(search) -> None:
    """Route dynamic categories through the specialist runtime selected by search_profile.

    The classification page can create categories with arbitrary IDs. Their search_profile
    determines which proven retrieval/relevance mechanics they inherit. In particular,
    custom HV-derived categories (such as power-transformers) must still use the strict
    HV relevance gate, relevance-aware engine fallback and queued HV research loop.
    """
    if getattr(search, "_category_profile_runtime_installed", False):
        return

    import pricing_runtime

    original_run = search._run
    original_search_web = search.search_web
    original_subject_filter = search.subject_relevant_candidates
    original_rank = search.rank_candidates
    original_collect_relevance = pricing_runtime._collect_relevance

    def category_profile_for(category_or_query):
        if hasattr(search, "pricing_profile"):
            try:
                return search.pricing_profile(category_or_query)
            except Exception:
                pass
        return category_or_query

    def subject_relevant_candidates(candidates, question, category=None):
        resolved = category or search.pricing_category(question)
        resolved_profile = category_profile_for(resolved)
        if resolved_profile != "hv-equipment" or resolved == "hv-equipment":
            return original_subject_filter(candidates, question, resolved)
        checker = getattr(search, "hv_candidate_relevance", None)
        if not callable(checker):
            return original_subject_filter(candidates, question, "hv-equipment")
        accepted = []
        for candidate in candidates:
            ok, _reason, score = checker(candidate, question)
            if ok:
                item = dict(candidate)
                item["subject_relevance_score"] = round(float(score), 3)
                accepted.append(item)
        return accepted

    def rank_candidates(candidates, question, requirements=None, subquestions=None, category="general-product"):
        resolved_profile = category_profile_for(category)
        if resolved_profile == "hv-equipment" and category != "hv-equipment":
            return original_rank(candidates, question, requirements, subquestions, "hv-equipment")
        return original_rank(candidates, question, requirements, subquestions, category)

    def search_web(query, backend_setting="auto", max_results=6):
        resolved = search.pricing_category(query)
        resolved_profile = category_profile_for(resolved)
        if resolved_profile != "hv-equipment" or resolved == "hv-equipment":
            return original_search_web(query, backend_setting, max_results)

        rows, seen, status = [], set(), []
        relevant_urls, relevant_backends = set(), 0
        checker = getattr(search, "hv_candidate_relevance", None)

        try:
            indexed = search.search_procurement(query, limit=max(6, int(max_results)))
        except Exception:
            indexed = []
        indexed_relevant = 0
        for row in indexed:
            url = search.canonical_url(str(row.get("url") or ""))
            if not url or url in seen:
                continue
            probe = {
                "title": str(row.get("title") or url),
                "snippet": str(row.get("snippet") or row.get("indexed_text") or ""),
                "url": url,
            }
            ok = True
            if callable(checker):
                ok, _reason, _score = checker(probe, query)
            if ok:
                indexed_relevant += 1
                relevant_urls.add(url)
            seen.add(url)
            rows.append({
                "title": probe["title"],
                "href": url,
                "body": probe["snippet"],
                "date": str(row.get("published_at") or row.get("date") or ""),
                "search_backend": "procurement-index",
            })
        if indexed:
            status.append(f"procurement-index: {len(indexed)} / {indexed_relevant} relevant")
            if indexed_relevant:
                relevant_backends += 1

        for backend in search.configured_search_backends(backend_setting):
            try:
                found = list(search.DDGS(timeout=12).text(
                    query, region="wt-wt", safesearch="moderate",
                    max_results=max_results, backend=backend,
                ) or [])
                backend_relevant = 0
                for row in found:
                    url = search.canonical_url(str(row.get("href") or row.get("url") or ""))
                    if not url:
                        continue
                    probe = {
                        "title": str(row.get("title") or url),
                        "snippet": str(row.get("body") or ""),
                        "url": url,
                    }
                    ok = True
                    if callable(checker):
                        ok, _reason, _score = checker(probe, query)
                    if ok:
                        backend_relevant += 1
                        relevant_urls.add(url)
                    if url in seen:
                        continue
                    seen.add(url)
                    item = dict(row)
                    item["href"] = url
                    item["search_backend"] = backend
                    rows.append(item)
                status.append(f"{backend}: {len(found)} / {backend_relevant} relevant")
                if backend_relevant:
                    relevant_backends += 1
            except Exception as exc:
                status.append(f"{backend}: {search.request_error(exc)}")

            if relevant_backends >= 2 or len(relevant_urls) >= max(4, int(max_results)):
                break
        return rows, status

    def collect_relevance(search_module, candidates, question, category):
        resolved_profile = category_profile_for(category)
        if resolved_profile != "hv-equipment" or category == "hv-equipment":
            return original_collect_relevance(search_module, candidates, question, category)
        checker = getattr(search_module, "hv_candidate_relevance", None)
        if not callable(checker):
            return original_collect_relevance(search_module, candidates, question, "hv-equipment")
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

    def run(app, job_id, query, history, model, allowed_only, uploaded_context=""):
        route_text = f"{query}\n{uploaded_context}"
        category = search.pricing_category(route_text)
        if category != "hv-equipment" and category_profile_for(category) == "hv-equipment":
            return pricing_runtime._run_hv(
                search, app, job_id, query, history, model, allowed_only, uploaded_context
            )
        return original_run(app, job_id, query, history, model, allowed_only, uploaded_context)

    search.subject_relevant_candidates = subject_relevant_candidates
    search.rank_candidates = rank_candidates
    search.search_web = search_web
    search._run = run
    pricing_runtime._collect_relevance = collect_relevance
    search._category_profile_runtime_installed = True
