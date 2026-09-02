from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from procurement_index import DEFAULT_INDEX, index_payload


FIND_TENDER = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
SELL2WALES_ENDPOINTS = (
    "https://api.sell2wales.gov.wales/v1/Notices",
    # This is the TLS-valid host used by the official Sell2Wales API guide.
    "https://api-sell2wales.klickstream.com/v1/Notices",
)


def request_json(url):
    response = requests.get(url, headers={"Accept": "application/json", "User-Agent": "InternetPricing/1.0"},
                            timeout=(10, 60))
    response.raise_for_status()
    return response.json()


def normalize_next_url(url):
    """Escape literal timezone plus signs in pagination links emitted by FTS."""
    return str(url or "").replace("+", "%2B")


def ingest_find_tender(path, days, max_pages):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    query = urlencode({"updatedFrom": start.isoformat(timespec="seconds"),
                       "updatedTo": end.isoformat(timespec="seconds"), "limit": 100})
    url, pages, total = f"{FIND_TENDER}?{query}", 0, 0
    while url and pages < max_pages:
        payload = request_json(url)
        total += index_payload(payload, "find-tender", path)
        pages += 1
        url = normalize_next_url((payload.get("links") or {}).get("next"))
    return pages, total


def sell2wales_json(query):
    errors = []
    for endpoint in SELL2WALES_ENDPOINTS:
        try:
            return request_json(f"{endpoint}?{query}")
        except requests.RequestException as exc:
            errors.append(f"{endpoint}: {exc}")
    raise requests.RequestException("; ".join(errors))


def ingest_sell2wales(path, months):
    today = date.today()
    total, requests_made, attempted = 0, 0, 0
    notice_types = (2, 3, 5, 6, 51, 53)
    # Completed calendar months are stable; the API often returns 500 while the
    # current month's OCDS export is still being assembled.
    for offset in range(1, months + 1):
        absolute_month = today.year * 12 + today.month - 1 - offset
        year, month_index = divmod(absolute_month, 12)
        month = month_index + 1
        for notice_type in notice_types:
            attempted += 1
            query = urlencode({"dateFrom": f"{month:02d}-{year}", "noticeType": notice_type,
                               "outputType": 0, "locale": 2057})
            try:
                payload = sell2wales_json(query)
            except requests.RequestException as exc:
                print(f"WARNING: Sell2Wales {month:02d}-{year} type {notice_type}: {exc}",
                      file=sys.stderr)
                continue
            total += index_payload(payload, "sell2wales", path)
            requests_made += 1
    if not requests_made:
        raise requests.RequestException(f"all {attempted} monthly feeds failed")
    return requests_made, total


def main():
    parser = argparse.ArgumentParser(description="Build the free local OCDS procurement index.")
    parser.add_argument("--database", default=str(DEFAULT_INDEX))
    parser.add_argument("--find-tender-days", type=int, default=90)
    parser.add_argument("--find-tender-max-pages", type=int, default=25)
    parser.add_argument("--sell2wales-months", type=int, default=6)
    args = parser.parse_args()
    failures = []
    try:
        ft_pages, ft_notices = ingest_find_tender(args.database, max(1, args.find_tender_days),
                                                   max(1, args.find_tender_max_pages))
        print(f"Find a Tender: {ft_notices} notices from {ft_pages} pages")
    except requests.RequestException as exc:
        failures.append(f"Find a Tender: {exc}")
    try:
        sw_requests, sw_notices = ingest_sell2wales(args.database, max(1, args.sell2wales_months))
        print(f"Sell2Wales: {sw_notices} notices from {sw_requests} monthly feeds")
    except requests.RequestException as exc:
        failures.append(f"Sell2Wales: {exc}")
    print(f"Index: {args.database}")
    for failure in failures:
        print(f"WARNING: {failure}", file=sys.stderr)
    if len(failures) == 2:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
