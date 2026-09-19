from core.normalize import extract_keywords


def test_keywords_exclude_urls_and_legal_boilerplate():
    text = """Product Manager
OpenAI
San Francisco
https://jobs.example.com/role
Build AI workflows and internal products.
Qualified applicants are considered under the Fair Chance Ordinance.
See https://example.com/privacy-policy."""
    keywords = extract_keywords(text)
    assert "https" not in keywords
    assert "fair chance" not in keywords
    assert "openai" not in keywords
    assert "workflows" in keywords
