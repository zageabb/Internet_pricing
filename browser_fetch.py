from __future__ import annotations

import os
import queue
import re
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from urllib.parse import urlparse

import search


PRICE_RE = re.compile(
    r"(?:GBP|USD|EUR|CAD|AUD|INR|CNY|JPY|CHF|£|€|\$|₹|¥)\s*[\d,.]+|"
    r"[\d,.]+\s*(?:GBP|USD|EUR|CAD|AUD|INR|CNY|JPY|CHF)",
    re.I,
)
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
AD_HOST_TOKENS = (
    "doubleclick.", "googlesyndication.", "google-analytics.", "adservice.",
    "adnxs.", "facebook.net", "hotjar.", "scorecardresearch.",
)
GENERIC_TERMS = {
    "price", "prices", "pricing", "cost", "costs", "buy", "online", "retailer", "supplier",
    "manufacturer", "distributor", "catalogue", "catalog", "quote", "quotation", "current", "new",
}


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def browser_fallback_enabled() -> bool:
    return _env_bool("INTERNET_PRICING_BROWSER_FALLBACK", True)


def browser_page_limit() -> int:
    return _env_int("INTERNET_PRICING_BROWSER_MAX_PAGES", 3, 0, 5)


def browser_timeout_ms() -> int:
    return _env_int("INTERNET_PRICING_BROWSER_TIMEOUT_MS", 15_000, 5_000, 30_000)


def browser_settle_ms() -> int:
    return _env_int("INTERNET_PRICING_BROWSER_SETTLE_MS", 1_500, 0, 5_000)


def has_price_signal(value: str) -> bool:
    return bool(PRICE_RE.search(str(value or "")))


def should_render_candidate(candidate: dict, page: dict) -> bool:
    """Use Chromium only for relevant commercial pages whose light fetch still lacks a visible price."""
    if not browser_fallback_enabled() or browser_page_limit() <= 0:
        return False
    url = str(candidate.get("url") or "")
    if not search.public_url(url):
        return False
    content_type = str(page.get("content_type") or "").lower()
    if "pdf" in content_type or "+rendered" in content_type:
        return False
    if str(page.get("error") or "").startswith("Blocked non-public"):
        return False

    query = str(candidate.get("query") or "")
    category = search.pricing_category(query)
    if category in {"hv-equipment", "service-project"}:
        return False

    title = str(candidate.get("title") or "")
    snippet = str(candidate.get("snippet") or "")
    page_text = str(page.get("text") or "")
    corpus = f"{title} {snippet} {page_text}"
    if has_price_signal(corpus):
        return False

    if category == "consumer-retail":
        return bool(search.subject_relevant_candidates([candidate], query, category))

    anchors = search.terms(query) - GENERIC_TERMS
    candidate_terms = search.terms(f"{title} {snippet}")
    return bool(anchors & candidate_terms) or bool(snippet.strip() and candidate.get("rank", 99) <= 3)


class BrowserRenderer:
    """Own one Playwright browser on a dedicated thread and isolate each rendered page in a fresh context."""

    def __init__(self):
        self._queue: queue.Queue[tuple[str, int, Future]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def render(self, url: str, timeout_ms: int) -> dict:
        self._ensure_worker()
        future: Future = Future()
        self._queue.put((url, timeout_ms, future))
        try:
            return future.result(timeout=(timeout_ms / 1000) + 12)
        except FutureTimeoutError:
            return {"text": "", "error": "Headless Chromium rendering exceeded its bounded timeout"}

    def _ensure_worker(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="internet-pricing-browser", daemon=True)
            self._thread.start()

    def _run(self):
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
        except Exception as exc:
            self._fail_requests(f"Playwright is unavailable: {exc}")
            return

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, chromium_sandbox=True)
                while True:
                    url, timeout_ms, future = self._queue.get()
                    if future.cancelled():
                        continue
                    try:
                        if not browser.is_connected():
                            browser = playwright.chromium.launch(headless=True, chromium_sandbox=True)
                        result = self._render_one(browser, url, timeout_ms, PlaywrightTimeoutError)
                    except Exception as exc:
                        result = {"text": "", "error": f"Headless Chromium failed: {search.request_error(exc)}"}
                    if not future.done():
                        future.set_result(result)
        except Exception as exc:
            self._fail_requests(f"Headless Chromium could not start: {search.request_error(exc)}")

    def _fail_requests(self, message: str):
        while True:
            url, timeout_ms, future = self._queue.get()
            if not future.done():
                future.set_result({"text": "", "error": message})

    @staticmethod
    def _render_one(browser, url: str, timeout_ms: int, playwright_timeout_error) -> dict:
        if not search.public_url(url):
            return {"text": "", "error": "Blocked non-public or invalid URL"}

        context = browser.new_context(
            locale="en-GB",
            java_script_enabled=True,
            service_workers="block",
            accept_downloads=False,
        )
        page = context.new_page()

        def route_request(route):
            request = route.request
            if request.resource_type in BLOCKED_RESOURCE_TYPES:
                route.abort()
                return
            request_url = request.url
            parsed = urlparse(request_url)
            if parsed.scheme in {"data", "blob", "about"}:
                route.continue_()
                return
            host = (parsed.hostname or "").lower()
            if any(token in host for token in AD_HOST_TOKENS):
                route.abort()
                return
            if parsed.scheme not in {"http", "https"} or not search.public_url(request_url):
                route.abort()
                return
            route.continue_()

        try:
            context.route("**/*", route_request)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_function(
                    """() => {
                        const text = document.body?.innerText || '';
                        return /(?:GBP|USD|EUR|£|€|\\$)\\s*[\\d,.]+|[\\d,.]+\\s*(?:GBP|USD|EUR)/i.test(text)
                            || !!document.querySelector('[itemprop="price"], meta[property="product:price:amount"], script[type="application/ld+json"]');
                    }""",
                    timeout=min(3_000, max(500, timeout_ms // 4)),
                )
            except playwright_timeout_error:
                pass
            settle_ms = browser_settle_ms()
            if settle_ms:
                page.wait_for_timeout(settle_ms)

            final_url = page.url
            if not search.public_url(final_url):
                return {"text": "", "error": "Browser redirected to a non-public or invalid URL"}
            html = page.content()
            if len(html.encode("utf-8", errors="ignore")) > search.MAX_WEB_BYTES:
                return {"text": "", "error": f"Rendered page exceeds the {search.MAX_WEB_BYTES // 1_000_000} MB limit"}
            text, published_at = search.extract_html(html.encode("utf-8"))
            return {
                "text": text,
                "url": final_url,
                "content_type": "text/html+rendered",
                "published_at": published_at,
            }
        finally:
            context.close()


_RENDERER = BrowserRenderer()
_ORIGINAL_FETCH_PAGES = None


def install_browser_fallback():
    """Wrap the existing light page fetcher without changing its HTTP/PDF-first behaviour."""
    global _ORIGINAL_FETCH_PAGES
    if getattr(search.fetch_pages, "_playwright_fallback", False):
        return
    _ORIGINAL_FETCH_PAGES = search.fetch_pages

    def fetch_pages_with_browser(job_id, candidates, workers):
        results = _ORIGINAL_FETCH_PAGES(job_id, candidates, workers)
        remaining = browser_page_limit()
        if not browser_fallback_enabled() or remaining <= 0:
            return results

        for candidate in candidates:
            if remaining <= 0:
                break
            url = candidate.get("url")
            page = results.get(url, {})
            if not should_render_candidate(candidate, page):
                continue
            remaining -= 1
            search.event(
                job_id, "site", "initiated", candidate.get("title") or url,
                "Lightweight fetch did not expose a price; trying bounded headless Chromium rendering",
                url, "Rendering dynamic pages",
            )
            rendered = _RENDERER.render(url, browser_timeout_ms())
            if rendered.get("text"):
                results[url] = rendered
                search.store_page(url, rendered)
                price_detail = "price signal found" if has_price_signal(rendered["text"]) else "rendered content returned"
                search.event(job_id, "site", "returned", candidate.get("title") or url,
                             f"Headless Chromium {price_detail}", url)
            else:
                search.event(job_id, "site", "partial", candidate.get("title") or url,
                             rendered.get("error") or "Headless Chromium returned no readable content", url)
        return results

    fetch_pages_with_browser._playwright_fallback = True
    search.fetch_pages = fetch_pages_with_browser
