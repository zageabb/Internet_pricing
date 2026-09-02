import tempfile
import unittest
from pathlib import Path

from procurement_index import index_payload, search_procurement


class ProcurementIndexTest(unittest.TestCase):
    def test_indexes_and_searches_structured_ocds_values(self):
        payload = {
            "uri": "https://procurement.example/api/releases",
            "releases": [{
                "id": "notice-1",
                "ocid": "ocds-test-1",
                "date": "2025-08-04T10:00:00Z",
                "buyer": {"name": "Example Hospital"},
                "tender": {
                    "title": "11 kV main intake switchboard",
                    "description": "Design, manufacture, delivery, erection, testing and commissioning.",
                    "value": {"amount": 500000, "currency": "GBP"},
                    "documents": [{"url": "https://procurement.example/notices/1"}],
                },
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "procurement.sqlite3"
            self.assertEqual(index_payload(payload, "test", database), 1)
            results = search_procurement("pricing for an 11 kV AIS switchboard", path=database)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://procurement.example/notices/1")
        self.assertIn("500000 GBP", results[0]["indexed_text"])
        self.assertEqual(results[0]["search_backend"], "procurement-index:test")

    def test_upsert_replaces_previous_notice_value(self):
        release = {"id": "notice-1", "ocid": "ocds-test-1", "tender": {
            "title": "132 kV disconnectors and earth switches",
            "description": "Framework procurement",
            "value": {"amount": 90000, "currency": "GBP"},
        }}
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "procurement.sqlite3"
            index_payload({"releases": [release]}, "test", database)
            release["tender"]["value"]["amount"] = 120000
            index_payload({"releases": [release]}, "test", database)
            results = search_procurement("132 kV disconnectors", path=database)

        self.assertEqual(len(results), 1)
        self.assertIn("120000 GBP", results[0]["indexed_text"])
        self.assertNotIn("90000 GBP", results[0]["indexed_text"])

    def test_known_switchboard_case_does_not_match_unrelated_notice_first(self):
        relevant = {"id": "switchboard", "ocid": "ocds-switchboard", "tender": {
            "title": "11 kV main intake switchboard upgrade",
            "description": "Design and manufacture of an AIS board with 18 circuit breakers and 2000 A busbars",
            "value": {"amount": 500000, "currency": "GBP"},
        }}
        unrelated = {"id": "software", "ocid": "ocds-software", "tender": {
            "title": "Hospital software upgrade",
            "description": "Global pricing and support contract",
            "value": {"amount": 900000, "currency": "GBP"},
        }}
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "procurement.sqlite3"
            index_payload({"releases": [unrelated, relevant]}, "test", database)
            results = search_procurement("11 kV AIS 2000 A switchboard pricing", path=database)

        self.assertEqual(results[0]["title"], "11 kV main intake switchboard upgrade")


if __name__ == "__main__":
    unittest.main()
