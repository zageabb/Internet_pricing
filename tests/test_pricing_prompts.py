import unittest

from settings_store import DEFAULTS, PROMPTS


class PricingPromptTest(unittest.TestCase):
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
