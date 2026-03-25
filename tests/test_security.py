"""Tests for security: SSRF protection, XSS sanitization, FTS5 injection."""

import pytest

from recipe_app.scraper import validate_url, sanitize_field, sanitize_fts5_query


class TestSSRFProtection:
    def test_blocks_localhost(self):
        with pytest.raises(ValueError, match="blocked"):
            validate_url("http://127.0.0.1/recipe")

    def test_blocks_private_10(self):
        with pytest.raises(ValueError, match="blocked"):
            validate_url("http://10.0.0.1/recipe")

    def test_blocks_private_172(self):
        with pytest.raises(ValueError, match="blocked"):
            validate_url("http://172.16.0.1/recipe")

    def test_blocks_private_192(self):
        with pytest.raises(ValueError, match="blocked"):
            validate_url("http://192.168.1.1/recipe")

    def test_blocks_link_local(self):
        with pytest.raises(ValueError, match="blocked"):
            validate_url("http://169.254.1.1/recipe")

    def test_blocks_ftp_scheme(self):
        with pytest.raises(ValueError, match="scheme"):
            validate_url("ftp://example.com/recipe")

    def test_blocks_file_scheme(self):
        with pytest.raises(ValueError, match="scheme"):
            validate_url("file:///etc/passwd")

    def test_blocks_javascript_scheme(self):
        with pytest.raises(ValueError, match="scheme"):
            validate_url("javascript:alert(1)")

    def test_blocks_empty_hostname(self):
        with pytest.raises(ValueError):
            validate_url("http:///recipe")

    def test_allows_public_https(self):
        url, resolved_ip = validate_url("https://www.google.com")
        assert url == "https://www.google.com"
        assert resolved_ip is not None


class TestXSSSanitization:
    def test_strips_script_tags(self):
        result = sanitize_field('<script>alert("xss")</script>Safe text')
        assert "<script>" not in result
        assert "</script>" not in result
        assert "Safe text" in result

    def test_strips_onclick(self):
        result = sanitize_field('<div onclick="alert(1)">Content</div>')
        assert "onclick" not in result

    def test_allows_safe_tags(self):
        result = sanitize_field("<b>Bold</b> and <em>italic</em>")
        assert "<b>Bold</b>" in result
        assert "<em>italic</em>" in result

    def test_allows_lists(self):
        result = sanitize_field("<ul><li>Item 1</li><li>Item 2</li></ul>")
        assert "<ul>" in result
        assert "<li>" in result

    def test_handles_none(self):
        assert sanitize_field(None) == ""

    def test_handles_empty_string(self):
        assert sanitize_field("") == ""

    def test_strips_img_with_onerror(self):
        result = sanitize_field('<img src="x" onerror="alert(1)">')
        assert "onerror" not in result


class TestFTS5Sanitization:
    def test_basic_query(self):
        result = sanitize_fts5_query("chicken garlic")
        assert result == '"chicken" "garlic"'

    def test_strips_operators(self):
        result = sanitize_fts5_query("chicken AND garlic NOT onion")
        assert "AND" not in result
        assert "NOT" not in result

    def test_strips_special_chars(self):
        result = sanitize_fts5_query('chicken* OR "garlic"')
        assert "*" not in result
        # The quotes from the input should be stripped, tokens re-quoted
        assert "OR" not in result

    def test_empty_input(self):
        result = sanitize_fts5_query("")
        assert result == '""'

    def test_only_operators(self):
        result = sanitize_fts5_query("AND OR NOT")
        assert result == '""'

    def test_hyphenated_words(self):
        result = sanitize_fts5_query("sugar-free gluten-free")
        assert "sugar-free" in result
        assert "gluten-free" in result

    def test_unicode(self):
        result = sanitize_fts5_query("café résumé")
        assert "café" in result
        assert "résumé" in result
