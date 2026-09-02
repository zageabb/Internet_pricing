import requests

import procurement_ingest


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
