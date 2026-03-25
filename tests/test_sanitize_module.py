"""Unit tests for sanitize.py — the DB write-path sanitizer.

NOTE: This tests recipe_app.sanitize (used by db.py), NOT recipe_app.scraper
which has a different sanitize_field with narrower allowed tags.
"""

from recipe_app.sanitize import sanitize_field, sanitize_url


class TestSanitizeField:
    def test_strips_script(self):
        result = sanitize_field("<script>alert(1)</script>Hello")
        assert "<script>" not in result
        assert "Hello" in result

    def test_allows_safe_tags(self):
        html = "<b>bold</b> <ul><li>item</li></ul>"
        result = sanitize_field(html)
        assert "<b>" in result
        assert "<ul>" in result
        assert "<li>" in result

    def test_allows_img_tag(self):
        html = '<img src="photo.jpg" alt="food">'
        result = sanitize_field(html)
        assert "<img" in result
        assert 'src="photo.jpg"' in result

    def test_strips_onclick(self):
        result = sanitize_field('<div onclick="evil()">text</div>')
        assert "onclick" not in result

    def test_strips_onerror(self):
        result = sanitize_field('<img src="x" onerror="alert(1)">')
        assert "onerror" not in result

    def test_strips_iframe(self):
        result = sanitize_field("<iframe src='evil.com'></iframe>")
        assert "<iframe" not in result

    def test_none_returns_none(self):
        assert sanitize_field(None) is None

    def test_empty_string(self):
        assert sanitize_field("") == ""

    def test_plain_text_unchanged(self):
        assert sanitize_field("Just some text") == "Just some text"


class TestSanitizeUrl:
    def test_valid_https(self):
        assert sanitize_url("https://example.com") == "https://example.com"

    def test_valid_http(self):
        assert sanitize_url("http://example.com") == "http://example.com"

    def test_javascript_scheme(self):
        assert sanitize_url("javascript:alert(1)") is None

    def test_data_scheme(self):
        assert sanitize_url("data:text/html,<h1>hi</h1>") is None

    def test_ftp_scheme(self):
        assert sanitize_url("ftp://example.com") is None

    def test_empty_string(self):
        # Empty string passes through (not a URL but no invalid scheme either)
        assert sanitize_url("") == ""

    def test_none_returns_none(self):
        assert sanitize_url(None) is None

    def test_strips_whitespace(self):
        assert sanitize_url("  https://example.com  ") == "https://example.com"
