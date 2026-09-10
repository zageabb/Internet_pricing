import unittest

import search
from classification_policy import install_classification_policy
from research_core_adapter import install_research_core_pricing
from settings_store import DEFAULTS, PROMPTS


class PricingPromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_research_core_pricing()
        install_classification_policy(search)

    def test_litre_product_is_consumer_retail(self):
        self.assertEqual(search.pricing_category("3 litre pepsi max price"), "consumer-retail")

    def test_consumer_queries_prioritise_retail(self):
        queries = search.pricing_queries("3 litre pepsi max price", [], "consumer-retail")
        self.assertTrue(any("supermarket" in query for query in queries))
        self.assertFalse(any("supplier distributor" in query for query in queries))

    def test_pack_specs_normalize_litre_spelling(self):
        self.assertEqual(search.pack_specs("3 litre and 1.5 liters"), {"3l", "1.5l"})

    def test_different_pack_price_is_not_exact(self):
        candidate = {"title": "Pepsi Max Tropical cans", "snippet": "24 x 0.33 litre, EUR 17.50"}
        self.assertFalse(search.exact_priced_product_candidate(candidate, "3 litre Pepsi Max price", ""))

    def test_one_exact_pack_price_does_not_end_consumer_market_research(self):
        evidence = [{"title": "Pepsi Max 3L bottle", "url": "https://shop1.example/pepsi",
                     "text": "Pepsi Max 3 litre bottle £3.00", "snippet": "", "query": "Pepsi Max 3L price"}]
        self.assertFalse(search.has_sufficient_commercial_benchmark(
            evidence, "3 litre Pepsi Max price", "consumer-retail"))

    def test_three_independent_exact_prices_end_consumer_market_research(self):
        evidence = [
            {"title": f"Pepsi Max 3L bottle {i}", "url": f"https://shop{i}.example/pepsi",
             "text": f"Pepsi Max 3 litre bottle £{3 + i / 10:.2f}", "snippet": "", "query": "Pepsi Max 3L price"}
            for i in range(1, 4)
        ]
        self.assertTrue(search.has_sufficient_commercial_benchmark(
            evidence, "3 litre Pepsi Max price", "consumer-retail"))

    def test_different_pack_price_does_not_end_consumer_research(self):
        evidence = [{"title": "Pepsi Max Tropical cans", "url": "https://shop.example/cans",
                     "text": "24 x 0.33 litre case EUR 17.50", "snippet": "", "query": "Pepsi Max price"}]
        self.assertFalse(search.has_sufficient_commercial_benchmark(
            evidence, "3 litre Pepsi Max price", "consumer-retail"))

    def test_pricing_defaults_request_deeper_research(self):
        self.assertGreaterEqual(DEFAULTS["max_search_rounds"], 3)
        self.assertGreaterEqual(DEFAULTS["max_pages_to_read"], 12)

    def test_planner_forces_web_for_price_requests(self):
        planning = PROMPTS.defaults["planning"].lower()
        self.assertIn("price", planning)
        self.assertIn("procurement", planning)
        self.assertIn("schedule", planning)
        self.assertIn("manufacturer-neutral", planning)
        self.assertIn("explicitly names a manufacturer", planning)
        self.assertIn("tender award", planning)
        self.assertIn("145 kv-class", planning)

    def test_answer_prompt_preserves_budget_structure(self):
        answer = PROMPTS.defaults["answer"].lower()
        self.assertIn("low/base/high", answer)
        self.assertIn("equipment-only", answer)
        self.assertIn("installed-package", answer)
        self.assertIn("date the price was obtained", answer)
        self.assertIn("usd, eur, and gbp", answer)
        self.assertIn("approximate", answer)
        self.assertIn("not web-verified", answer)

    def test_model_knowledge_fallback_is_a_persistent_prompt_contract(self):
        direct = PROMPTS.defaults["direct_answer"].lower()
        answer = PROMPTS.defaults["answer"].lower()
        review = PROMPTS.defaults["citation_review"].lower()

        self.assertIn("model-knowledge figure", direct)
        self.assertIn("indicative model-knowledge budget range", answer)
        self.assertIn("uncited model-knowledge budget range is permitted", review)
        self.assertIn("not web-verified", direct)
        self.assertIn("not web-verified", answer)
        self.assertIn("not web-verified", review)


if __name__ == "__main__":
    unittest.main()
