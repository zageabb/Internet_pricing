import unittest
import json
from datetime import date
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from pathlib import Path

from search import (best_passages, canonical_url, clean_queries, configured_search_backends,
                    cosine_similarity, evidence_ledger,
                    currency_conversion_evidence, extract_html, fetch_page, freshness_score,
                    has_commercial_price, market_context, pricing_queries, pricing_request,
                    public_url, rank_candidates, search_web, subject_relevant_candidates)
import settings_store


class ResearchPipelineTest(unittest.TestCase):
    def test_auto_search_uses_only_free_backends(self):
        self.assertEqual(configured_search_backends("auto"), ["duckduckgo", "mojeek", "startpage", "yahoo"])

    def test_canonical_url_removes_tracking_and_fragments(self):
        url = canonical_url("HTTPS://Example.COM/report?ID=7&utm_source=test#section")
        self.assertEqual(url, "https://example.com/report?ID=7")

    @patch("search.DDGS")
    def test_search_web_merges_and_deduplicates_two_free_engines(self, ddgs):
        ddgs.return_value.text.side_effect = [
            [{"title": "One", "href": "https://example.com/a?utm_source=x", "body": "first"}],
            [{"title": "One duplicate", "href": "https://example.com/a", "body": "same"},
             {"title": "Two", "href": "https://example.org/b", "body": "second"}],
        ]

        rows, status = search_web("switchboard price", "auto", 6)

        self.assertEqual([row["href"] for row in rows], ["https://example.com/a", "https://example.org/b"])
        self.assertEqual([row["search_backend"] for row in rows], ["duckduckgo", "mojeek"])
        self.assertEqual(status, ["duckduckgo: 1", "mojeek: 2"])
        self.assertEqual(ddgs.return_value.text.call_count, 2)

    def test_blank_or_global_country_uses_global_market(self):
        self.assertEqual(market_context({"market_country": ""}), "Global")
        self.assertEqual(market_context({"market_country": "Worldwide", "market_region": "Europe"}), "Global")

    def test_specific_country_builds_market_context(self):
        settings = {"market_country": "GB", "market_region": "England", "market_city": "London"}
        self.assertEqual(market_context(settings), "London, England, GB")

    def test_pricing_request_detection(self):
        self.assertTrue(pricing_request("Provide a budget estimate for a transformer"))
        self.assertFalse(pricing_request("Explain how a transformer works"))

    def test_pricing_queries_add_specific_commercial_benchmarks(self):
        queries = pricing_queries("pricing for 132kv disconnectors with earthing", ["Global prices for disconnectors"])
        joined = " ".join(queries).lower()
        self.assertNotIn("global prices", joined)
        self.assertIn("132 kv 145 kv disconnector earth switch tender award", joined)
        self.assertIn("schedule of rates cost data pdf", joined)
        self.assertIn("framework contract award lot value", joined)

    def test_subject_filter_removes_generic_price_results(self):
        candidates = [
            {"title": "Bitcoin global market price", "snippet": "BTC price today"},
            {"title": "132 kV surge arrester disconnector", "snippet": "Surge arrester spare part"},
            {"title": "132 kV cable termination price", "snippet": "Cable accessory quotation"},
            {"title": "132 kV disconnectors", "snippet": "Disconnector with earthing switch"},
        ]
        filtered = subject_relevant_candidates(candidates, "Pricing for 132 kV disconnectors with earthing")
        self.assertEqual([row["title"] for row in filtered], ["132 kV disconnectors"])

    def test_commercial_price_detection(self):
        priced = [{"source_id": 1, "title": "Award", "url": "https://example.com", "query": "award",
                   "claims": ["The lot value was GBP 91,380."], "passages": []}]
        technical = [{"source_id": 1, "title": "Specification", "url": "https://example.com", "query": "spec",
                      "claims": ["The rated voltage is 145 kV."], "passages": []}]
        self.assertTrue(has_commercial_price(priced))
        self.assertFalse(has_commercial_price(technical))

    @patch("search.requests.get")
    def test_currency_conversion_evidence_builds_three_currency_cross_rates(self, get):
        get.return_value.json.return_value = [
            {"date": "2026-09-02", "base": "EUR", "quote": "EUR", "rate": 1.0},
            {"date": "2026-09-02", "base": "EUR", "quote": "GBP", "rate": 0.8},
            {"date": "2026-09-02", "base": "EUR", "quote": "USD", "rate": 1.2},
            {"date": "2026-09-02", "base": "EUR", "quote": "JPY", "rate": 180.0},
        ]
        evidence = [{"source_id": 1, "title": "Price", "url": "https://example.com", "query": "price",
                     "claims": ["The listed price is JPY 18,000."], "passages": []}]

        fx = currency_conversion_evidence(evidence)

        self.assertEqual(fx["published_at"], "2026-09-02")
        self.assertTrue(any("1 JPY" in claim and "USD" in claim and "EUR" in claim and "GBP" in claim
                            for claim in fx["claims"]))
        get.return_value.raise_for_status.assert_called_once()

    def test_unusable_domain_is_not_added_to_blocklist(self):
        with TemporaryDirectory() as directory:
            settings_file = Path(directory) / "settings.json"
            settings_file.write_text(json.dumps({
                "allowed_domains": "useful.example",
                "blocked_domains": "manual.example",
            }))
            with patch.object(settings_store, "SETTINGS_FILE", settings_file):
                settings_store.record_domain_verdict("failed.example", False)
                saved = settings_store.get_settings()

        self.assertEqual(saved["allowed_domains"], "useful.example")
        self.assertEqual(saved["blocked_domains"], "manual.example")

    def test_rank_candidates_prefers_relevance_and_authority(self):
        candidates = [
            {"title": "Generic home page", "url": "https://example.com/", "snippet": "Welcome to our site", "query": "battery safety report"},
            {"title": "Battery safety annual report", "url": "https://agency.gov.uk/research/battery-safety", "snippet": "Official battery incident statistics and safety findings", "query": "battery safety report"},
        ]

        ranked = rank_candidates(candidates, "What do official reports say about battery safety?", [], [])

        self.assertEqual(ranked[0]["url"], "https://agency.gov.uk/research/battery-safety")
        self.assertEqual([row["rank"] for row in ranked], [1, 2])

    def test_best_passages_finds_relevant_text_beyond_page_start(self):
        content = "\n".join([
            "This introductory material discusses the organisation and its history in broad terms.",
            "Navigation information and general contact details are available elsewhere on the website.",
            "The 2026 battery safety study recorded a 24 percent reduction in thermal incidents after the new standard.",
            "An unrelated closing paragraph describes office opening hours and mailing addresses.",
        ])

        passages = best_passages(content, "2026 battery safety thermal incident reduction", limit=2)

        self.assertTrue(any("24 percent reduction" in passage for passage in passages))

    def test_evidence_ledger_preserves_claims_passages_and_ids(self):
        ledger = evidence_ledger([{
            "source_id": 1,
            "title": "Official report",
            "url": "https://example.gov/report",
            "query": "official report",
            "claims": ["Incidents declined in 2026."],
            "passages": ["The report recorded fewer incidents in 2026."],
        }])

        self.assertIn("[1] Official report", ledger)
        self.assertIn("Incidents declined in 2026.", ledger)
        self.assertIn("Passage 1:", ledger)
        self.assertRegex(ledger, r"Obtained: \d{4}-\d{2}-\d{2}")

    def test_clean_queries_rejects_malformed_model_output(self):
        self.assertEqual(clean_queries("not a JSON list"), [])

    def test_html_extraction_preserves_publication_date(self):
        text, published = extract_html(b"""<html><head><meta property="article:published_time" content="2026-08-20"></head>
            <body><nav>Navigation should disappear from this page.</nav><main>A sufficiently detailed research finding remains visible here.</main></body></html>""")
        self.assertEqual(published, "2026-08-20")
        self.assertIn("research finding", text)
        self.assertNotIn("Navigation", text)

    def test_freshness_and_cosine_helpers(self):
        self.assertGreater(freshness_score(date.today().isoformat()), freshness_score("2020-01-01"))
        self.assertAlmostEqual(cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1, 0], [0, 1]), 0.0)

    def test_private_and_credentialed_urls_are_rejected(self):
        self.assertFalse(public_url("http://127.0.0.1/private"))
        self.assertFalse(public_url("https://user:password@example.com/report"))

    @patch("search.requests.get")
    @patch("search.public_url", side_effect=[True, False])
    def test_redirect_destination_is_revalidated(self, _public_url, get):
        redirect = Mock(status_code=302, headers={"location": "http://127.0.0.1/private"})
        get.return_value = redirect

        result = fetch_page("https://public.example/report")

        self.assertIn("Blocked non-public", result["error"])
        self.assertEqual(get.call_count, 1)
        redirect.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
