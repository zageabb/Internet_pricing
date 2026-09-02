import tempfile
import unittest
from pathlib import Path

from retrieval_cache import load_page, store_page


class RetrievalCacheTest(unittest.TestCase):
    def test_stores_and_loads_successful_page(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "cache.sqlite3"
            store_page("https://example.com/report", {
                "text": "A procurement report with a price of GBP 500,000.",
                "url": "https://example.com/report",
                "content_type": "text/html",
                "published_at": "2025-08-04",
            }, database)
            loaded = load_page("https://example.com/report", path=database)

        self.assertEqual(loaded["cache_status"], "fresh")
        self.assertIn("GBP 500,000", loaded["text"])

    def test_does_not_store_empty_or_failed_page(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "cache.sqlite3"
            store_page("https://example.com/failure", {"text": "", "error": "HTTP 403"}, database)
            self.assertIsNone(load_page("https://example.com/failure", path=database))


if __name__ == "__main__":
    unittest.main()
