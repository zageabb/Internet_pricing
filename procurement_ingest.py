from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from procurement_index import DEFAULT_INDEX, index_payload


FIND_TENDER = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
SELL2WALES = "https://api.sell2wales.gov.wales/v1/Notices"


def request_json(url):
    response = requests.get(url, headers={"Accept": "application/json", "User-Agent": "InternetPricing/1.0"},
                            timeout=(10, 60))
    response.raise_for_status()
    return response.json()


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
        url = str((payload.get("links") or {}).get("next") or "")
    return pages, total


def ingest_sell2wales(path, months):
    today = date.today()
    total, requests_made = 0, 0
    notice_types = (2, 3, 5, 6, 51, 53)
    for offset in range(months):
        absolute_month = today.year * 12 + today.month - 1 - offset
        year, month_index = divmod(absolute_month, 12)
        month = month_index + 1
        for notice_type in notice_types:
            query = urlencode({"dateFrom": f"{month:02d}-{year}", "noticeType": notice_type,
                               "outputType": 0, "locale": 2057})
            payload = request_json(f"{SELL2WALES}?{query}")
            total += index_payload(payload, "sell2wales", path)
            requests_made += 1
    return requests_made, total


def main():
    parser = argparse.ArgumentParser(description="Build the free local OCDS procurement index.")
    parser.add_argument("--database", default=str(DEFAULT_INDEX))
    parser.add_argument("--find-tender-days", type=int, default=90)
    parser.add_argument("--find-tender-max-pages", type=int, default=25)
    parser.add_argument("--sell2wales-months", type=int, default=6)
    args = parser.parse_args()
    ft_pages, ft_notices = ingest_find_tender(args.database, max(1, args.find_tender_days),
                                               max(1, args.find_tender_max_pages))
    sw_requests, sw_notices = ingest_sell2wales(args.database, max(1, args.sell2wales_months))
    print(f"Find a Tender: {ft_notices} notices from {ft_pages} pages")
    print(f"Sell2Wales: {sw_notices} notices from {sw_requests} monthly feeds")
    print(f"Index: {args.database}")


if __name__ == "__main__":
    main()
