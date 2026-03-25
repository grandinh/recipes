"""Shared HTML sanitization for all write paths (web forms, API, MCP)."""

import bleach

# Allowed HTML tags — same set used by the scraper
ALLOWED_TAGS = list(bleach.ALLOWED_TAGS) + [
    "p", "br", "h1", "h2", "h3", "h4", "ul", "ol", "li", "img",
]
ALLOWED_ATTRS = {**bleach.ALLOWED_ATTRIBUTES, "img": ["src", "alt"]}


def sanitize_field(value: str | None) -> str | None:
    """Sanitize a text field using bleach. Returns None if input is None."""
    if value is None:
        return None
    return bleach.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)


def sanitize_url(value: str | None) -> str | None:
    """Validate that a URL uses http/https scheme. Returns None for invalid URLs."""
    if value is None:
        return None
    value = value.strip()
    if value and not value.lower().startswith(("http://", "https://")):
        return None
    return value
