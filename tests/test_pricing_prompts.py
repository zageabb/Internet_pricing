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

    def test_answer_prompt_preserves_budget_structure(self):
        answer = PROMPTS.defaults["answer"].lower()
        self.assertIn("low/base/high", answer)
        self.assertIn("equipment-only", answer)
        self.assertIn("installed-package", answer)
        self.assertIn("date the price was obtained", answer)
        self.assertIn("usd, eur, and gbp", answer)
        self.assertIn("approximate", answer)


if __name__ == "__main__":
    unittest.main()
