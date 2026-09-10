from app import app


def test_classifications_page_renders_category_sections():
    client = app.test_client()
    response = client.get("/classifications")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Classifications &amp; Rules" in html or "Classifications & Rules" in html
    assert "HV equipment" in html
    assert "Consumer / retail" in html
    assert "Evidence requirements" in html
    assert "Stopping rules" in html
    assert "Fallback &amp; enrichment" in html or "Fallback & enrichment" in html
    assert "Category extensions / notes" in html


def test_classification_api_identifies_x1_carbon_as_consumer_retail():
    client = app.test_client()
    response = client.post("/api/classifications/test", json={
        "query": "Lenovo ThinkPad X1 Carbon Gen 13 Aura Edition 32GB 1TB price"
    })
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["category"] == "consumer-retail"
    assert result["min_priced_sources"] == 3
    assert result["require_independent_domains"] is True
