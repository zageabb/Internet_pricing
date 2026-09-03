import unittest

from search import extract_html, has_commercial_price


class WebExtractionTest(unittest.TestCase):
    def test_extracts_json_ld_product_offer_and_date(self):
        payload = b'''<html><head>
        <script type="application/ld+json">{
          "@context": "https://schema.org", "@type": "Product",
          "name": "Pepsi Max No Sugar Cola Bottle 3L", "sku": "65372",
          "brand": {"@type": "Brand", "name": "Pepsi"},
          "dateModified": "2026-09-03",
          "offers": {"@type": "Offer", "price": "3.00", "priceCurrency": "GBP",
                     "availability": "https://schema.org/InStock"}
        }</script></head><body><main>Buy Pepsi Max online for home delivery today.</main></body></html>'''

        text, published = extract_html(payload)

        self.assertIn("Structured commercial data (JSON-LD)", text)
        self.assertIn("Product: name=Pepsi Max No Sugar Cola Bottle 3L; brand=Pepsi; sku=65372", text)
        self.assertIn("price=GBP 3.00", text)
        self.assertIn("availability=InStock", text)
        self.assertEqual(published, "2026-09-03")
        self.assertTrue(has_commercial_price([{
            "source_id": 1, "title": "Pepsi", "url": "https://example.test/pepsi",
            "query": "Pepsi Max 3L price", "text": text,
        }]))

    def test_extracts_product_price_metadata(self):
        payload = b'''<html><head>
          <meta property="og:title" content="BenQ GW2480 Monitor">
          <meta property="product:price:amount" content="119.99">
          <meta property="product:price:currency" content="GBP">
          <meta property="product:availability" content="in stock">
        </head><body><main>BenQ GW2480 Full HD monitor product page.</main></body></html>'''

        text, _ = extract_html(payload)

        self.assertIn("product title: BenQ GW2480 Monitor", text)
        self.assertIn("price: 119.99", text)
        self.assertIn("currency: GBP", text)
        self.assertIn("Offer price: GBP 119.99", text)
        self.assertIn("availability: in stock", text)

    def test_extracts_embedded_application_price_state(self):
        payload = b'''<html><head><script id="__NEXT_DATA__" type="application/json">{
          "props": {"product": {"productName": "Lenovo V15 16GB 512GB",
          "currentPrice": 429.99, "currencyCode": "GBP"}}
        }</script></head><body><main>Lenovo V15 product details.</main></body></html>'''

        text, _ = extract_html(payload)

        self.assertIn("Embedded offer: product=Lenovo V15 16GB 512GB; price=GBP 429.99", text)

    def test_extracts_hv_specification_and_price_table(self):
        payload = b'''<html><body><table>
          <tr><th>Description</th><th>Voltage</th><th>Unit price</th></tr>
          <tr><td>Three-pole disconnector with earth switch</td><td>145 kV</td><td>GBP 30,000</td></tr>
        </table><footer>Unrelated footer links</footer></body></html>'''

        text, _ = extract_html(payload)

        self.assertIn("Commercial/specification tables", text)
        self.assertIn("Three-pole disconnector with earth switch | 145 kV | GBP 30,000", text)
        self.assertNotIn("Unrelated footer links", text)


if __name__ == "__main__":
    unittest.main()
