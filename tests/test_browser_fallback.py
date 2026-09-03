import unittest
from unittest.mock import patch

from browser_fetch import has_price_signal, should_render_candidate


class BrowserFallbackTest(unittest.TestCase):
    def test_detects_visible_currency_price(self):
        self.assertTrue(has_price_signal("Offer price: GBP 429.99"))
        self.assertTrue(has_price_signal("Now £3.00"))
        self.assertFalse(has_price_signal("Price available after JavaScript loads"))

    @patch("browser_fetch.search.public_url", return_value=True)
    def test_renders_relevant_consumer_page_when_price_missing(self, _public_url):
        candidate = {
            "title": "Pepsi Max Cola 3L",
            "url": "https://shop.example/pepsi-max",
            "snippet": "Pepsi Max cola bottle, 3 litre product page",
            "query": "Pepsi Max cola 3L price",
            "rank": 1,
        }
        page = {"text": "Pepsi Max cola 3L product details", "content_type": "text/html"}
        self.assertTrue(should_render_candidate(candidate, page))

    @patch("browser_fetch.search.public_url", return_value=True)
    def test_skips_browser_when_search_or_page_already_has_price(self, _public_url):
        candidate = {
            "title": "Pepsi Max Cola 3L",
            "url": "https://shop.example/pepsi-max",
            "snippet": "Pepsi Max cola 3L - £3.00",
            "query": "Pepsi Max cola 3L price",
            "rank": 1,
        }
        page = {"text": "Product details", "content_type": "text/html"}
        self.assertFalse(should_render_candidate(candidate, page))

    @patch("browser_fetch.search.public_url", return_value=True)
    def test_skips_hv_procurement_pages(self, _public_url):
        candidate = {
            "title": "145 kV disconnector tender",
            "url": "https://procurement.example/tender",
            "snippet": "Utility tender for 145 kV disconnector",
            "query": "132 kV 145 kV disconnector earth switch tender award procurement price",
            "rank": 1,
        }
        page = {"text": "Tender notice without a visible unit price", "content_type": "text/html"}
        self.assertFalse(should_render_candidate(candidate, page))

    @patch("browser_fetch.search.public_url", return_value=True)
    def test_skips_already_rendered_cached_page(self, _public_url):
        candidate = {
            "title": "10 kW inverter",
            "url": "https://supplier.example/inverter",
            "snippet": "10 kW inverter product page",
            "query": "10 kW inverter price",
            "rank": 1,
        }
        page = {"text": "Rendered product data", "content_type": "text/html+rendered"}
        self.assertFalse(should_render_candidate(candidate, page))


if __name__ == "__main__":
    unittest.main()
