from importlib.metadata import version

from ddgs.engines import ENGINES
from ddgs.http_client import HttpClient


def test_search_dependency_versions_are_pinned():
    assert version("ddgs") == "9.16.0"
    assert version("primp") == "2.0.1"


def test_ddgs_uses_primp_random_impersonation(monkeypatch):
    captured = {}

    class DummyClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("ddgs.http_client.primp.Client", DummyClient)
    HttpClient(timeout=1)

    assert captured["impersonate"] == "random"
    assert captured["impersonate_os"] == "random"


def test_configured_text_backends_remain_available():
    available = set(ENGINES["text"])
    assert {"duckduckgo", "mojeek", "startpage", "yahoo"} <= available
