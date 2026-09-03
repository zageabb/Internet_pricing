from __future__ import annotations

import ipaddress
import json
import math
import re
import socket
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import date, datetime, timezone
from io import BytesIO
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

from procurement_index import search_procurement
from retrieval_cache import load_page, store_page
from settings_store import PROMPTS, get_settings, record_domain_verdict, render


JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
HEADERS = {"User-Agent": "GeneralSearch/1.0 (+local research app)",
           "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9"}
MAX_WEB_BYTES = 8_000_000
MAX_REDIRECTS = 5
FX_URL = "https://api.frankfurter.dev/v2/rates?base=EUR"
FX_TARGETS = ("USD", "EUR", "GBP")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_models():
    settings = get_settings()
    response = requests.get(settings["ollama_url"].rstrip("/") + "/api/tags", timeout=8)
    response.raise_for_status()
    return [row.get("name") for row in response.json().get("models", []) if row.get("name")]


def start_job(app, query, history, model, allowed_only, uploaded_context=""):
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "status": "queued", "phase": "Queued", "events": [], "sources": [], "steps": [], "message": None, "error": None, "created_at": now(), "started_at": None, "completed_at": None}
    with LOCK:
        JOBS[job_id] = job
        finished = [key for key, value in JOBS.items() if value["status"] in {"completed", "failed"}]
        for key in finished[:-50]:
            JOBS.pop(key, None)
    threading.Thread(target=_run, args=(app, job_id, query, history, model, allowed_only, uploaded_context), daemon=True).start()
    return deepcopy(job)


def event(job_id, kind, status, label, detail="", url="", phase=""):
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["events"].append({"sequence": len(job["events"]) + 1, "timestamp": now(), "kind": kind, "status": status, "label": label[:500], "detail": detail[:1000], "url": url[:2000]})
        job["events"] = job["events"][-250:]
        if phase:
            job["phase"] = phase


def update(job_id, **values):
    with LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(values)


def _run(app, job_id, query, history, model, allowed_only, uploaded_context=""):
    update(job_id, status="running", phase="Planning research", started_at=now())
    try:
        settings = get_settings()
        model = model or settings["model"]
        market = market_context(settings)
        allowed = domains(settings["allowed_domains"]) if allowed_only else []
        blocked = domains(settings["blocked_domains"])
        scope = "Only: " + ", ".join(allowed) if allowed else "Any public website except blocked domains"
        prompts = PROMPTS.load()
        context = "\n\n".join(f"{x['role'].title()}: {x['content']}" for x in history[-12:])
        effective_query = query if not context else f"Conversation context:\n{context}\n\nCurrent request:\n{query}"
        if uploaded_context:
            effective_query = f"{effective_query}\n\n{uploaded_context}"
            event(job_id, "document", "returned", "Included uploaded document context", f"{len(uploaded_context):,} characters available")
        planning = render(prompts["planning"], market=market, scope=scope, query=effective_query)
        event(job_id, "phase", "running", "Understanding and improving the request", phase="Planning response")
        parsed = ollama_json(settings["ollama_url"], model, planning)
        rewritten_question = clean_text(parsed.get("rewritten_question"), effective_query)
        requirements = clean_items(parsed.get("requirements", []), 8)
        subquestions = clean_items(parsed.get("subquestions", []), 5)
        is_pricing = pricing_intent(effective_query, rewritten_question)
        needs_web = is_pricing or parsed.get("needs_web") is True
        queries = clean_queries(parsed.get("queries", []))
        if needs_web and not queries:
            queries = [query, f"{query} authoritative source", f"{query} {market}"]
        if needs_web and is_pricing:
            queries = pricing_queries(query, queries)
        queries = queries[:6]
        route = "web research" if needs_web else "model knowledge"
        event(job_id, "reasoning", "summary", f"Using {route}", rewritten_question, phase="Planning complete")
        if subquestions:
            event(job_id, "reasoning", "summary", f"Identified {len(subquestions)} supporting questions", "; ".join(subquestions))

        if not needs_web:
            direct_prompt = direct_answer_prompt(prompts, settings, market, effective_query, rewritten_question,
                                                 requirements, subquestions, "Not needed for this request")
            event(job_id, "phase", "running", "Answering from model knowledge", phase="Producing answer")
            answer = ollama_text(settings["ollama_url"], model, direct_prompt)
            answer = review_answer(job_id, prompts, settings, model, effective_query, rewritten_question,
                                   requirements, subquestions, answer, "No web evidence (model knowledge answer)")
            update(job_id, status="completed", phase="Complete", message=answer, sources=[],
                   steps=[f"Ollama model: {model}", "Route: model knowledge", f"Clarified request: {rewritten_question}", "Final answer reviewed"], completed_at=now())
            event(job_id, "phase", "returned", "Answer completed", phase="Complete")
            return

        evidence = []
        seen = set()
        attempted_queries = []
        current_queries = queries
        max_rounds = 1 if is_pricing else settings["max_search_rounds"]
        for round_number in range(1, max_rounds + 1):
            event(job_id, "phase", "running", f"Research round {round_number}", phase=f"Searching — round {round_number}")
            candidates = []
            if round_number == 1 and is_pricing:
                indexed = search_procurement(rewritten_question, limit=max(10, settings["results_per_query"] * 2))
                event(job_id, "index", "returned", "Searched local procurement index",
                      f"{len(indexed)} structured notices returned")
                for row in indexed:
                    url = canonical_url(str(row.get("url") or ""))
                    if not url or url in seen:
                        continue
                    host = hostname(url)
                    if any(host == domain or host.endswith("." + domain) for domain in blocked):
                        continue
                    seen.add(url)
                    item = dict(row)
                    item["url"] = url
                    candidates.append(item)
            for search_query in current_queries:
                attempted_queries.append(search_query)
                event(job_id, "search", "initiated", search_query)
                rows, engine_status = search_web(search_query, settings["search_backend"], settings["results_per_query"])
                if not rows:
                    event(job_id, "search", "failed", search_query, "; ".join(engine_status) or "No results")
                    continue
                event(job_id, "search", "returned", search_query,
                      f"{len(rows)} merged results · " + "; ".join(engine_status))
                for row in rows:
                    url = canonical_url(str(row.get("href") or row.get("url") or ""))
                    host = hostname(url)
                    if not host or url in seen or any(host == d or host.endswith("." + d) for d in blocked):
                        continue
                    if allowed and not any(host == d or host.endswith("." + d) for d in allowed):
                        continue
                    seen.add(url)
                    candidates.append({"title": str(row.get("title") or url), "url": url,
                                       "snippet": str(row.get("body") or ""), "query": search_query,
                                       "published_at": str(row.get("date") or row.get("published") or ""),
                                       "search_backend": str(row.get("search_backend") or "")})
            candidates = subject_relevant_candidates(candidates, rewritten_question)
            ranked = rank_candidates(candidates, rewritten_question, requirements, subquestions)
            ranked = embedding_rerank(job_id, settings, ranked,
                                      research_text(rewritten_question, requirements, subquestions))
            remaining_rounds = max_rounds - round_number + 1
            remaining_pages = settings["max_pages_to_read"] - len(evidence)
            round_budget = remaining_pages if remaining_rounds == 1 else max(1, math.ceil(remaining_pages / remaining_rounds))
            retained_this_round = 0
            shortlist_size = min(len(ranked), max(settings["max_fetch_workers"], min(round_budget + 1, 5)))
            shortlist = ranked[:shortlist_size]
            fetched = fetch_pages(job_id, shortlist, settings["max_fetch_workers"])
            for candidate in shortlist:
                if len(evidence) >= settings["max_pages_to_read"] or retained_this_round >= round_budget:
                    break
                title, url, snippet, source_query = (candidate[key] for key in ("title", "url", "snippet", "query"))
                source_id = len(evidence) + 1
                page = fetched.get(url, {})
                if page.get("error"):
                    if len(snippet.strip()) < 80:
                        event(job_id, "site", "failed", title, page["error"], url)
                        continue
                    event(job_id, "site", "partial", title,
                          f"Page unavailable ({page['error']}); evaluating indexed search passage", url)
                    page = {"text": snippet, "url": url, "content_type": "text/search-snippet",
                            "published_at": candidate.get("published_at", "")}
                text = page.get("text") or snippet
                if len(text.strip()) < 40:
                    event(job_id, "site", "unreadable", title, "No readable evidence", url)
                    continue
                passages = best_passages(text, research_text(rewritten_question, requirements, subquestions),
                                         limit=4, max_chars=6_000)
                focused_text = "\n\n".join(passages) or text[:12_000]
                if exact_priced_product_candidate(candidate, rewritten_question, focused_text):
                    verdict, reason = "useful", "Exact requested product/specification with a visible commercial price"
                    claims = best_passages(focused_text, f"{rewritten_question} price", limit=3, max_chars=1_500)
                else:
                    verdict, reason, claims = analyse_source(prompts, settings, model, source_query, title, url, focused_text)
                if verdict != "useful":
                    if verdict == "unusable":
                        reason = f"Not retained: {reason}"
                    event(job_id, "site", "failed", title, reason, url)
                    continue
                record_domain_verdict(hostname(url), True)
                evidence.append({"source_id": source_id, "title": title, "url": url, "query": source_query,
                                 "passages": passages, "claims": claims, "text": focused_text[:12_000],
                                 "relevance": candidate["score"],
                                 "published_at": page.get("published_at") or candidate.get("published_at", ""),
                                 "obtained_at": date.today().isoformat(),
                                 "content_type": page.get("content_type", "")})
                retained_this_round += 1
                event(job_id, "site", "returned", title, f"Source {source_id} retained · {reason}", url)
            if is_pricing and has_commercial_price(evidence):
                event(job_id, "reasoning", "returned", "Commercial benchmark found",
                      "Proceeding to the estimate without another search round")
                break
            if round_number == max_rounds or len(evidence) >= settings["max_pages_to_read"]:
                break
            coverage = assess_coverage(prompts, settings, model, rewritten_question, requirements, subquestions,
                                       attempted_queries, evidence)
            gaps = clean_items(coverage.get("gaps", []), 6)
            follow_ups = clean_queries(coverage.get("queries", []))[:4]
            if coverage.get("complete") is True:
                event(job_id, "reasoning", "returned", "Evidence coverage is sufficient",
                      "; ".join(clean_items(coverage.get("covered", []), 6)) or "Core request supported")
                break
            if gaps:
                event(job_id, "reasoning", "summary", f"Research found {len(gaps)} evidence gap(s)", "; ".join(gaps))
            if not follow_ups:
                if evidence:
                    event(job_id, "reasoning", "summary", "No productive follow-up search identified",
                          "Proceeding with the available evidence and explicit uncertainty")
                    break
                follow_ups = [f"{query} primary source", f"{query} official information"]
            current_queries = follow_ups

        if not evidence:
            direct_prompt = direct_answer_prompt(prompts, settings, market, effective_query, rewritten_question,
                                                 requirements, subquestions,
                                                 "Web research returned no readable evidence; answer cautiously from model knowledge")
            event(job_id, "phase", "running", "Web unavailable; using model knowledge", phase="Producing answer")
            answer = ollama_text(settings["ollama_url"], model, direct_prompt)
            answer = review_answer(job_id, prompts, settings, model, effective_query, rewritten_question,
                                   requirements, subquestions, answer, "No readable web evidence (knowledge fallback)")
            update(job_id, status="completed", phase="Complete", message=answer, sources=[],
                   steps=[f"Ollama model: {model}", "Route: knowledge fallback after web failure", f"Clarified request: {rewritten_question}", "Final answer reviewed"], completed_at=now())
            event(job_id, "phase", "returned", "Fallback answer completed", phase="Complete")
            return
        commercial_price_found = has_commercial_price(evidence)
        if is_pricing:
            fx = currency_conversion_evidence(evidence)
            if fx:
                fx["source_id"] = len(evidence) + 1
                evidence.append(fx)
                event(job_id, "currency", "returned", "Loaded dated reference exchange rates",
                      f"Approximate USD, EUR and GBP conversions · {fx['published_at']}", fx["url"])
            else:
                event(job_id, "currency", "failed", "Reference exchange rates unavailable",
                      "Report will preserve source currencies without inventing conversions")
        evidence_text = evidence_ledger(evidence)
        answer_prompt = render(prompts["answer"], date=date.today(), market=market, scope=scope, query=effective_query,
                               rewritten_question=rewritten_question, requirements="; ".join(requirements) or "None specified",
                               subquestions="; ".join(subquestions) or "None", evidence=evidence_text[:60_000])
        allow_indicative = is_pricing and not commercial_price_found
        if allow_indicative:
            answer_prompt = ("Commercial evidence limitation: the retained sources contain no concrete usable price. "
                             "Provide a concise indicative model-knowledge low/base/high budget anyway, clearly label it "
                             "as not web-verified, state scope and confidence, and keep it separate from cited facts.\n\n" + answer_prompt)
        instructions = settings["general_search_instructions"].strip()
        if instructions:
            answer_prompt = f"Persistent user instructions:\n{instructions}\n\n{answer_prompt}"
        event(job_id, "phase", "running", f"Synthesising from {len(evidence)} sources", phase="Producing answer")
        answer = ollama_text(settings["ollama_url"], model, answer_prompt)
        answer = review_answer(job_id, prompts, settings, model, effective_query, rewritten_question,
                               requirements, subquestions, answer, evidence_text, allow_indicative=allow_indicative)
        answer = verify_citations(job_id, prompts, settings, model, rewritten_question, answer, evidence_text, evidence,
                                  allow_indicative=allow_indicative)
        sources = [{"source_id": x["source_id"], "title": x["title"], "url": x["url"],
                    "published_at": x.get("published_at", ""), "obtained_at": x["obtained_at"]}
                   for x in evidence]
        update(job_id, status="completed", phase="Complete", message=answer, sources=sources,
               steps=[f"Ollama model: {model}", f"Ran {len(attempted_queries)} targeted searches",
                      f"Retained {len(evidence)} ranked sources", "Evidence coverage and citations reviewed"], completed_at=now())
        event(job_id, "phase", "returned", "Research answer completed", phase="Complete")
    except Exception as exc:
        update(job_id, status="failed", phase="Failed", error=str(exc), completed_at=now())
        event(job_id, "phase", "failed", f"Search failed: {exc}", phase="Failed")


def ollama_text(base_url, model, prompt):
    response = requests.post(base_url.rstrip("/") + "/api/generate", json={"model": model, "prompt": prompt, "stream": False}, timeout=300)
    response.raise_for_status()
    text = str(response.json().get("response") or "").strip()
    if not text:
        raise RuntimeError("Ollama returned an empty response.")
    return text


def ollama_json(base_url, model, prompt):
    response = requests.post(base_url.rstrip("/") + "/api/generate", json={"model": model, "prompt": prompt, "stream": False, "format": "json"}, timeout=180)
    response.raise_for_status()
    try:
        return json.loads(response.json().get("response") or "{}")
    except json.JSONDecodeError:
        return {}


def fetch_pages(job_id, candidates, workers):
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 8))) as executor:
        future_map = {}
        for candidate in candidates:
            event(job_id, "site", "initiated", candidate["title"],
                  f"Opening candidate ranked {candidate['rank']} · relevance {candidate['score']:.2f}",
                  candidate["url"], "Reading sites")
            if candidate.get("indexed_text"):
                results[candidate["url"]] = {"text": candidate["indexed_text"], "url": candidate["url"],
                                              "content_type": candidate.get("content_type", "application/ocds+json"),
                                              "published_at": candidate.get("published_at", "")}
                continue
            future_map[executor.submit(fetch_page, candidate["url"])] = candidate["url"]
        for future in as_completed(future_map):
            url = future_map[future]
            try:
                results[url] = future.result()
            except Exception as exc:
                results[url] = {"text": "", "error": request_error(exc)}
    return results


def fetch_page(url):
    """Fetch a public page with a positive cache and stale fallback for temporary failures."""
    cached = load_page(url)
    if cached:
        return cached
    try:
        result = fetch_page_live(url)
    except requests.RequestException:
        stale = load_page(url, allow_stale=True)
        if stale:
            return stale
        raise
    if result.get("text"):
        store_page(url, result)
    return result


def fetch_page_live(url):
    """Fetch a bounded public HTML or PDF page, validating every redirect target."""
    current = url
    response = None
    for _ in range(MAX_REDIRECTS + 1):
        if not public_url(current):
            return {"text": "", "error": "Blocked non-public or invalid URL"}
        response = requests.get(current, headers=HEADERS, timeout=(5, 20), allow_redirects=False, stream=True)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            response.close()
            if not location:
                return {"text": "", "error": "Redirect response had no destination"}
            current = urljoin(current, location)
            continue
        break
    else:
        return {"text": "", "error": f"Too many redirects (limit {MAX_REDIRECTS})"}
    try:
        response.raise_for_status()
        declared_size = int(response.headers.get("content-length") or 0)
        if declared_size > MAX_WEB_BYTES:
            return {"text": "", "error": f"Page exceeds the {MAX_WEB_BYTES // 1_000_000} MB download limit"}
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=65_536):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_WEB_BYTES:
                return {"text": "", "error": f"Page exceeds the {MAX_WEB_BYTES // 1_000_000} MB download limit"}
            chunks.append(chunk)
        payload = b"".join(chunks)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type == "application/pdf" or payload.startswith(b"%PDF-"):
            text = extract_pdf(payload)
            return {"text": text, "url": current, "content_type": "application/pdf", "published_at": ""}
        if "html" not in content_type and "xhtml" not in content_type:
            return {"text": "", "error": f"Unsupported web content type: {content_type or 'unknown'}"}
        text, published_at = extract_html(payload)
        return {"text": text, "url": current, "content_type": content_type, "published_at": published_at}
    finally:
        response.close()


def extract_pdf(payload):
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(payload))
    sections, size = [], 0
    for page_number, page in enumerate(reader.pages, 1):
        if page_number > 100:
            break
        text = " ".join((page.extract_text() or "").split())
        if not text:
            continue
        section = f"Page {page_number}: {text}"
        sections.append(section)
        size += len(section)
        if size >= 120_000:
            break
    return "\n".join(sections)[:120_000]


def extract_html(payload):
    soup = BeautifulSoup(payload, "html.parser")
    published_at = ""
    for attributes in ({"property": "article:published_time"}, {"name": "date"},
                       {"name": "datePublished"}, {"itemprop": "datePublished"}):
        tag = soup.find("meta", attrs=attributes)
        if tag and tag.get("content"):
            published_at = str(tag["content"])[:100]
            break
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()
    blocks = [" ".join(block.split()) for block in soup.get_text("\n", strip=True).splitlines()]
    return "\n".join(block for block in blocks if len(block) >= 20)[:120_000], published_at


def read_page(url):
    """Backward-compatible text-only page reader."""
    return fetch_page(url).get("text", "")


def request_error(exc):
    """Return a useful, bounded message without leaking a response body."""
    response = getattr(exc, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}: {response.reason or 'request failed'}"
    return str(exc)


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return False
    try:
        for info in socket.getaddrinfo(parsed.hostname, None):
            if not ipaddress.ip_address(info[4][0]).is_global:
                return False
    except (OSError, ValueError):
        return False
    return True


def hostname(url):
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def domains(value):
    return list(dict.fromkeys(filter(None, (hostname(x if "://" in x else "https://" + x) for x in re.split(r"[\n,]+", str(value))))))


FREE_SEARCH_BACKENDS = ("duckduckgo", "mojeek", "startpage", "yahoo")


def configured_search_backends(value):
    requested = [item.strip().lower() for item in str(value or "auto").split(",") if item.strip()]
    if not requested or requested == ["auto"]:
        return list(FREE_SEARCH_BACKENDS)
    return list(dict.fromkeys(requested))


def search_web(query, backend_setting="auto", max_results=6):
    """Merge two successful free search engines, falling through when one is unavailable."""
    rows, seen, status, successes = [], set(), [], 0
    for backend in configured_search_backends(backend_setting):
        try:
            found = list(DDGS(timeout=12).text(query, region="wt-wt", safesearch="moderate",
                                               max_results=max_results, backend=backend) or [])
            status.append(f"{backend}: {len(found)}")
            if found:
                successes += 1
            for row in found:
                url = canonical_url(str(row.get("href") or row.get("url") or ""))
                if not url or url in seen:
                    continue
                seen.add(url)
                item = dict(row)
                item["href"] = url
                item["search_backend"] = backend
                rows.append(item)
        except Exception as exc:
            status.append(f"{backend}: {request_error(exc)}")
        if successes >= 2:
            break
    return rows, status


def canonical_url(url):
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        host = (parsed.hostname or "").lower()
        if (host.endswith("bing.com") and parsed.path.startswith("/aclick")) or "doubleclick.net" in host:
            return ""
        tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}
        query = urlencode([(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                           if key.lower() not in tracking])
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", query, ""))
    except ValueError:
        return ""


STOP_WORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is", "it",
              "of", "on", "or", "that", "the", "this", "to", "was", "what", "when", "where", "which", "who",
              "why", "will", "with", "you", "your"}


def terms(value):
    return {word for word in re.findall(r"[a-z0-9][a-z0-9_-]{1,}", str(value).lower()) if word not in STOP_WORDS}


def research_text(question, requirements, subquestions):
    return " ".join([question, *requirements, *subquestions])


def rank_candidates(candidates, question, requirements=None, subquestions=None):
    """Rank search results for relevance, authority, and source diversity."""
    target = terms(research_text(question, requirements or [], subquestions or []))
    generic = {"price", "prices", "pricing", "cost", "costs", "current", "market", "buy", "deal",
               "deals", "new", "laptop", "computer"}
    anchors = {term for term in terms(question) if term not in generic}
    scored = []
    for candidate in candidates:
        title_terms = terms(candidate.get("title", ""))
        snippet_terms = terms(candidate.get("snippet", ""))
        query_terms = terms(candidate.get("query", ""))
        host = hostname(candidate.get("url", ""))
        overlap = len(target & title_terms) * 3 + len(target & snippet_terms) + len(query_terms & (title_terms | snippet_terms))
        denominator = max(1, len(target))
        authority = 1.25 if (host.endswith(".gov") or host.endswith(".gov.uk") or host.endswith(".edu") or
                             host.endswith(".ac.uk")) else 0.0
        path = urlparse(candidate.get("url", "")).path.lower()
        primary_hint = 0.6 if any(token in path for token in ("/docs", "/documentation", "/research", "/report", "/news")) else 0.0
        commercial_text = f"{candidate.get('title', '')} {candidate.get('snippet', '')}".lower()
        commercial_hint = 1.4 if (re.search(r"(?:gbp|usd|eur|£|€|\$)\s*[\d,.]+", commercial_text) or
                                          any(token in commercial_text for token in
                                              ("award value", "lot value", "estimated value", "unit rate"))) else 0.0
        structured_hint = 1.0 if str(candidate.get("search_backend", "")).startswith("procurement-index:") else 0.0
        matched_anchors = anchors & (title_terms | snippet_terms)
        exact_hint = 8.0 if anchors and len(matched_anchors) / len(anchors) >= 0.75 else 0.0
        freshness = freshness_score(candidate.get("published_at", "")) if freshness_sensitive(question) else 0.0
        candidate = dict(candidate)
        candidate["score"] = round(overlap / denominator + authority + primary_hint + commercial_hint +
                                   structured_hint + exact_hint + freshness, 3)
        scored.append(candidate)
    scored.sort(key=lambda item: (-item["score"], item.get("title", "").lower()))
    return diversify(scored)


def diversify(scored):
    # Interleave domains so one publisher cannot consume the reading budget.
    ranked, pending, domain_counts = [], scored[:], {}
    while pending:
        best_index = max(range(len(pending)), key=lambda index: pending[index]["score"] - domain_counts.get(hostname(pending[index]["url"]), 0) * 0.75)
        item = pending.pop(best_index)
        host = hostname(item["url"])
        domain_counts[host] = domain_counts.get(host, 0) + 1
        item["rank"] = len(ranked) + 1
        ranked.append(item)
    return ranked


def freshness_sensitive(query):
    query_terms = terms(query)
    current_year = str(date.today().year)
    return bool(query_terms & {"current", "currently", "latest", "recent", "today", "news", "price", "prices",
                               "law", "laws", "regulation", "regulations", "schedule", current_year})


def pricing_request(query):
    return bool(terms(query) & {"price", "prices", "pricing", "cost", "costs", "quote", "quotation", "budget",
                                "estimate", "valuation", "rate", "rates", "tender", "procurement"})


def pricing_intent(original_query, rewritten_question):
    """A planner rewrite may clarify a product but must never erase pricing intent."""
    return pricing_request(original_query) or pricing_request(rewritten_question)


def pricing_queries(query, planned):
    """Preserve the requested item/specification in deterministic commercial searches."""
    base = " ".join(str(query).split())
    equipment = re.sub(r"\bpricing\s+for\b", "", base, flags=re.I).strip()
    equipment = re.sub(r"\bwith\s+earthing\b", "with earth switch", equipment, flags=re.I)
    industrial_terms = {"kv", "switchgear", "transformer", "disconnector", "substation", "tender", "procurement",
                        "cable", "generator", "motor", "pump", "compressor", "gis", "ais"}
    normalized_equipment = re.sub(r"(?<=\d)\s+(?=(?:gb|tb|kv|ka|a)\b)", "", equipment, flags=re.I)
    if terms(equipment) & industrial_terms or re.search(r"\b\d+\s*k[va]\b", equipment, re.I):
        additions = [f"{equipment} tender award procurement price", f"{equipment} schedule of rates cost data pdf",
                     f"{equipment} framework contract award lot value"]
    else:
        additions = [f"{normalized_equipment} price", f"{normalized_equipment} buy online",
                     f"{normalized_equipment} retailer"]
    voltage = re.search(r"\b132\s*k\s*v\b", equipment, re.I)
    if voltage:
        additions[0] = f"132 kV 145 kV disconnector earth switch tender award procurement price"
    vague = re.compile(r"^(global\s+prices?|market\s+price|earthing\s+system\s+cost)\b", re.I)
    anchors = {term for term in terms(normalized_equipment) if term not in {"price", "pricing", "cost"}}
    kept = [item for item in planned if not vague.search(item) and anchors.issubset(terms(item))]
    return clean_queries(additions + kept)


def subject_relevant_candidates(candidates, question):
    """Drop results that match only generic words such as global, market, or price."""
    ignored = {"price", "prices", "pricing", "cost", "costs", "current", "global", "market", "value", "values",
               "specification", "specifications", "equipment", "including", "with", "for", "and", "the"}
    def stem(term):
        if term.endswith("ing") and len(term) > 6:
            term = term[:-3]
        return term.rstrip("s")

    consumer_nouns = {"laptop", "monitor", "computer", "desktop", "phone", "smartphone", "tablet", "printer",
                      "television", "camera", "headphone", "headphones"}
    query_terms = terms(question)
    consumer_request = bool(query_terms & consumer_nouns)
    anchors = {stem(term) for term in query_terms if len(term) >= 3 and term not in ignored and
               (consumer_request and term not in consumer_nouns or
                not consumer_request and not any(character.isdigit() for character in term))}
    if not anchors:
        return candidates
    matched = []
    for candidate in candidates:
        candidate_text = f"{candidate.get('title', '')} {candidate.get('snippet', '')}"
        if "surge arrester" in candidate_text.lower() and "surge arrester" not in question.lower():
            continue
        haystack = terms(candidate_text)
        normalized = haystack | {stem(term) for term in haystack if len(term) >= 4}
        matching_anchors = anchors & normalized
        required = len(anchors) if consumer_request else 1
        if len(matching_anchors) >= required:
            matched.append(candidate)
    return matched or candidates


def exact_priced_product_candidate(candidate, question, content=""):
    """Retain exact retail evidence deterministically when both identity and price are visible."""
    consumer_nouns = {"laptop", "monitor", "computer", "desktop", "phone", "smartphone", "tablet", "printer",
                      "television", "camera", "headphone", "headphones"}
    query_terms = terms(question)
    if not query_terms & consumer_nouns:
        return False
    anchors = {term for term in query_terms if term not in consumer_nouns and term not in
               {"price", "prices", "pricing", "cost", "current", "new", "buy"}}
    corpus = f"{candidate.get('title', '')} {candidate.get('snippet', '')} {content}"
    corpus_terms = terms(corpus)
    required = max(1, math.ceil(len(anchors) * 0.75))
    identity_match = len(anchors & corpus_terms) >= required
    visible_price = bool(re.search(
        r"(?:GBP|USD|EUR|CAD|AUD|INR|BDT|NPR|NGN|£|€|\$|₹|৳|Rs\.?|Tk\.?)\s*[\d,.]+|"
        r"[\d,.]+\s*(?:GBP|USD|EUR|CAD|AUD|INR|BDT|NPR|NGN)", corpus, re.I))
    return identity_match and visible_price


def has_commercial_price(evidence):
    corpus = evidence_ledger(evidence)
    currency = r"(?:USD|EUR|GBP|JPY|INR|CNY|AUD|CAD|CHF|£|€|\$|₹|¥)"
    amount = r"(?:\d[\d,.]*\s*(?:million|billion|thousand|[kmb])?)"
    return bool(re.search(rf"(?:{currency}\s*{amount}|{amount}\s*{currency})", corpus, re.I))


def currency_conversion_evidence(evidence):
    """Build dated cross-rates into USD, EUR and GBP for currencies present in evidence."""
    try:
        response = requests.get(FX_URL, timeout=8)
        response.raise_for_status()
        rows = response.json()
        rates = {str(row.get("quote") or "").upper(): float(row["rate"]) for row in rows
                 if row.get("quote") and float(row.get("rate") or 0) > 0}
        rates["EUR"] = 1.0
        rate_date = max(str(row.get("date") or "") for row in rows)
    except (requests.RequestException, TypeError, ValueError, KeyError):
        return None

    corpus = evidence_ledger(evidence)
    codes = {code for code in rates if re.search(rf"(?<![A-Z]){re.escape(code)}(?![A-Z])", corpus.upper())}
    if "$" in corpus:
        codes.add("USD")
    if "€" in corpus:
        codes.add("EUR")
    if "£" in corpus:
        codes.add("GBP")
    codes.update(FX_TARGETS)
    codes &= rates.keys()

    claims = []
    for source in sorted(codes):
        conversions = [f"1 {source} ≈ {rates[target] / rates[source]:.6g} {target}" for target in FX_TARGETS]
        claims.append("; ".join(conversions))
    url = f"{FX_URL}&quotes={','.join(sorted(codes))}"
    return {"title": "Frankfurter dated reference exchange rates", "url": url, "query": "reference exchange rates",
            "passages": [f"Reference rates dated {rate_date}. " + claim for claim in claims], "claims": claims,
            "text": "\n".join(claims), "relevance": 0, "published_at": rate_date,
            "obtained_at": date.today().isoformat(), "content_type": "application/json"}


def freshness_score(value):
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_days = max(0, (datetime.now(timezone.utc) - published).days)
    except ValueError:
        match = re.search(r"\b(20\d{2})\b", raw)
        if not match:
            return 0.0
        age_days = max(0, (date.today().year - int(match.group(1))) * 365)
    if age_days <= 30:
        return 1.0
    if age_days <= 180:
        return 0.7
    if age_days <= 365:
        return 0.4
    if age_days <= 730:
        return 0.1
    return -0.25


def embedding_rerank(job_id, settings, candidates, query):
    model = str(settings.get("embedding_model") or "").strip()
    if not model or len(candidates) < 2:
        return candidates
    inputs = [query] + [f"{item.get('title', '')}\n{item.get('snippet', '')}" for item in candidates]
    try:
        response = requests.post(settings["ollama_url"].rstrip("/") + "/api/embed",
                                 json={"model": model, "input": inputs}, timeout=90)
        response.raise_for_status()
        vectors = response.json().get("embeddings") or []
        if len(vectors) != len(inputs):
            raise ValueError("embedding response did not contain every requested vector")
        query_vector = vectors[0]
        reranked = []
        for candidate, vector in zip(candidates, vectors[1:]):
            candidate = dict(candidate)
            candidate["semantic_similarity"] = round(cosine_similarity(query_vector, vector), 4)
            candidate["score"] = round(candidate["score"] + candidate["semantic_similarity"] * 2, 3)
            reranked.append(candidate)
        reranked.sort(key=lambda item: (-item["score"], item.get("title", "").lower()))
        event(job_id, "reasoning", "returned", f"Semantically reranked {len(reranked)} results",
              f"Embedding model: {model}")
        return diversify(reranked)
    except Exception as exc:
        event(job_id, "reasoning", "failed", "Embedding reranking unavailable",
              f"Using lexical ranking: {request_error(exc)}")
        return candidates


def cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def best_passages(content, query, limit=5, max_chars=9_000):
    """Return the most query-relevant, de-duplicated passages from a page."""
    target = terms(query)
    raw = [" ".join(part.split()) for part in re.split(r"\n{1,}|(?<=[.!?])\s+(?=[A-Z0-9])", str(content))]
    passages = [part for part in raw if 40 <= len(part) <= 2_500]
    if not passages:
        passages = [" ".join(str(content).split())[:max_chars]] if str(content).strip() else []
    scored = []
    for index, passage in enumerate(passages):
        passage_terms = terms(passage)
        coverage = len(target & passage_terms) / max(1, len(target))
        density = len(target & passage_terms) / max(1, len(passage_terms))
        number_bonus = 0.08 if re.search(r"\b\d[\d,.%]*\b", passage) else 0
        scored.append((coverage * 3 + density + number_bonus, index, passage))
    selected, selected_terms, size = [], [], 0
    for score, index, passage in sorted(scored, key=lambda row: (-row[0], row[1])):
        p_terms = terms(passage)
        if any(len(p_terms & prior) / max(1, len(p_terms | prior)) > 0.82 for prior in selected_terms):
            continue
        if size + len(passage) > max_chars and selected:
            continue
        selected.append((index, passage))
        selected_terms.append(p_terms)
        size += len(passage)
        if len(selected) >= limit:
            break
    return [passage for _, passage in sorted(selected)]


def evidence_ledger(evidence):
    rows = []
    for item in evidence:
        claims = "\n".join(f"- {claim}" for claim in item.get("claims", [])) or "- No claims pre-extracted"
        passages = "\n\n".join(f"Passage {index}: {passage}" for index, passage in enumerate(item.get("passages", []), 1))
        published = f"\nPublished: {item['published_at']}" if item.get("published_at") else ""
        obtained = item.get("obtained_at") or date.today().isoformat()
        rows.append(f"[{item['source_id']}] {item['title']}\nURL: {item['url']}\nFound via: {item['query']}{published}\nObtained: {obtained}\n"
                    f"Extracted claims:\n{claims}\nRelevant passages:\n{passages or item.get('text', '')}")
    return "\n\n---\n\n".join(rows)


def clean_queries(values):
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(" ".join(str(x).split())[:300] for x in values if str(x).strip()))


def market_context(settings):
    country = str(settings.get("market_country") or "").strip()
    if not country or country.lower() in {"global", "worldwide", "world"}:
        return "Global"
    return ", ".join(filter(None, [str(settings.get("market_city") or "").strip(),
                                    str(settings.get("market_region") or "").strip(), country]))


def clean_items(values, limit):
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(" ".join(str(x).split())[:500] for x in values if str(x).strip()))[:limit]


def clean_text(value, fallback):
    value = " ".join(str(value or "").split()).strip()
    return value[:4000] or fallback


def direct_answer_prompt(prompts, settings, market, query, rewritten_question, requirements, subquestions, web_status):
    prompt = render(prompts["direct_answer"], date=date.today(), market=market, query=query,
                    rewritten_question=rewritten_question, requirements="; ".join(requirements) or "None specified",
                    subquestions="; ".join(subquestions) or "None", web_status=web_status)
    instructions = settings["general_search_instructions"].strip()
    return f"Persistent user instructions:\n{instructions}\n\n{prompt}" if instructions else prompt


def review_answer(job_id, prompts, settings, model, query, rewritten_question, requirements, subquestions, answer, evidence,
                  allow_indicative=False):
    event(job_id, "phase", "running", "Checking the answer against the request", phase="Reviewing answer")
    prompt = render(prompts["review"], query=query, rewritten_question=rewritten_question,
                    requirements="; ".join(requirements) or "None specified",
                    subquestions="; ".join(subquestions) or "None", evidence=str(evidence)[:40_000], answer=answer[:30_000])
    if allow_indicative:
        prompt = ("Review invariant: no usable commercial price was found. Preserve or add a concise indicative "
                  "model-knowledge budget range, explicitly labelled not web-verified, with scope and low confidence.\n\n" + prompt)
    try:
        reviewed = ollama_json(settings["ollama_url"], model, prompt)
        final_answer = str(reviewed.get("final_answer") or "").strip()
        issues = clean_items(reviewed.get("issues", []), 8)
        detail = "; ".join(issues) if issues else "No material omissions found"
        if not final_answer:
            event(job_id, "reasoning", "failed", "Final review returned no answer", "Using the original draft")
            return answer
        status = "passed" if reviewed.get("answered") is True else "revised"
        event(job_id, "reasoning", "returned", f"Final answer review {status}", detail)
        return final_answer
    except Exception as exc:
        event(job_id, "reasoning", "failed", "Final answer review unavailable", str(exc))
        return answer


def assess_coverage(prompts, settings, model, rewritten_question, requirements, subquestions, queries, evidence):
    if not evidence:
        return {"complete": False, "covered": [], "gaps": ["No readable evidence retained"], "queries": []}
    prompt = render(prompts["research_review"], rewritten_question=rewritten_question,
                    requirements="; ".join(requirements) or "None specified",
                    subquestions="; ".join(subquestions) or "None", queries="; ".join(queries),
                    evidence=evidence_ledger(evidence)[:35_000])
    try:
        return ollama_json(settings["ollama_url"], model, prompt)
    except Exception:
        return {"complete": False, "covered": [], "gaps": [], "queries": []}


def verify_citations(job_id, prompts, settings, model, rewritten_question, answer, evidence_text, evidence,
                     allow_indicative=False):
    event(job_id, "phase", "running", "Validating claims and citations", phase="Verifying citations")
    valid_ids = {str(item["source_id"]) for item in evidence}
    cited_ids = set(re.findall(r"\[(\d+)\]", answer))
    invalid_ids = sorted(cited_ids - valid_ids)
    if invalid_ids:
        event(job_id, "reasoning", "summary", "Draft contained invalid citation IDs", ", ".join(invalid_ids))
    prompt = render(prompts["citation_review"], rewritten_question=rewritten_question,
                    evidence=evidence_text[:55_000], answer=answer[:30_000])
    if allow_indicative:
        prompt = ("Citation invariant: preserve the clearly labelled, uncited indicative model-knowledge budget because "
                  "the retained web evidence contains no usable commercial price. It must say not web-verified.\n\n" + prompt)
    try:
        result = ollama_json(settings["ollama_url"], model, prompt)
        final_answer = str(result.get("final_answer") or "").strip()
        issues = clean_items(result.get("issues", []), 8)
        if not final_answer:
            event(job_id, "reasoning", "failed", "Citation verification returned no answer", "Using reviewed draft")
            return answer
        final_ids = set(re.findall(r"\[(\d+)\]", final_answer))
        if final_ids - valid_ids:
            event(job_id, "reasoning", "failed", "Citation verification introduced invalid IDs", "Using reviewed draft")
            return answer
        event(job_id, "reasoning", "returned", "Citation verification passed" if result.get("valid") is True else "Citations corrected",
              "; ".join(issues) if issues else "Claims checked against retained passages")
        return final_answer
    except Exception as exc:
        event(job_id, "reasoning", "failed", "Citation verification unavailable", str(exc))
        return answer


def analyse_source(prompts, settings, model, query, title, url, content):
    prompt = render(prompts["source_review"], query=query, title=title, url=url, content=content[:6_000])
    try:
        result = ollama_json(settings["ollama_url"], model, prompt)
    except Exception as exc:
        return "review_failed", f"Quality check failed: {exc}", []
    verdict = str(result.get("verdict") or "").strip().lower()
    reason = clean_text(result.get("reason"), "No useful query-related evidence found")[:300]
    claims = clean_items(result.get("claims", []), 5)
    return ("useful", reason, claims) if verdict == "useful" else ("unusable", reason, [])


def review_source(prompts, settings, model, query, title, url, content):
    """Backward-compatible two-value source review API."""
    verdict, reason, _ = analyse_source(prompts, settings, model, query, title, url, content)
    return verdict, reason
