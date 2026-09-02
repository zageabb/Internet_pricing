import requests

import procurement_ingest


def test_find_tender_next_url_escapes_timezone_plus_signs():
    url = "https://example.test/feed?updatedFrom=2026-09-01T00:00:00+00:00&cursor=abc=="

    normalized = procurement_ingest.normalize_next_url(url)

    assert "00%2B00:00" in normalized
    assert "cursor=abc==" in normalized


def test_sell2wales_uses_documented_fallback(monkeypatch):
    calls = []

    def fake_request(url):
        calls.append(url)
        if "api.sell2wales.gov.wales" in url:
            raise requests.exceptions.SSLError("bad certificate chain")
        return {"releases": []}

    monkeypatch.setattr(procurement_ingest, "request_json", fake_request)

    assert procurement_ingest.sell2wales_json("noticeType=5") == {"releases": []}
    assert len(calls) == 2
    assert "api-sell2wales.klickstream.com" in calls[1]
