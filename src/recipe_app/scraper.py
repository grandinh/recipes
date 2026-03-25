"""URL import, sanitization, and SSRF protection for recipe scraping."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from urllib.parse import urlparse

import bleach
import httpx
import recipe_scrapers

from .config import settings

# ---------------------------------------------------------------------------
# Bleach allow-list for sanitising recipe text
# ---------------------------------------------------------------------------
ALLOWED_TAGS: list[str] = [
    "b", "i", "em", "strong", "ul", "ol", "li", "p", "br",
]

# FTS5 operators that must be stripped from user search input
_FTS5_OPERATORS = re.compile(r"\b(AND|OR|NOT|NEAR)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the IP is private, reserved, loopback, or link-local."""
    return (
        ip.is_private
        or ip.is_reserved
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified  # 0.0.0.0, ::
    )


def validate_url(url: str) -> tuple[str, str]:
    """Parse *url*, enforce http(s) scheme, and reject private/reserved IPs.

    Returns ``(validated_url, resolved_ip)`` so callers can connect to the
    resolved IP directly, preventing DNS rebinding / TOCTOU attacks.
    Raises ``ValueError`` when the URL is blocked or malformed.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    # Resolve every address the hostname maps to and check each one.
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname {hostname!r}: {exc}") from exc

    if not addrinfos:
        raise ValueError(f"Could not resolve hostname {hostname!r}")

    # Check ALL resolved IPs — block if any is private/reserved
    resolved_ip = None
    for family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise ValueError(
                f"Access to {hostname!r} ({ip}) is blocked (private/reserved network)"
            )
        if resolved_ip is None:
            resolved_ip = str(ip)

    return url, resolved_ip


def sanitize_field(value: str | None) -> str:
    """Sanitise a recipe text field using the ``ALLOWED_TAGS`` allow-list.

    Returns an empty string when *value* is ``None``.
    """
    if value is None:
        return ""
    return bleach.clean(value, tags=ALLOWED_TAGS, strip=True)


def sanitize_fts5_query(user_input: str) -> str:
    """Produce a safe FTS5 query string from arbitrary user input.

    * Strips characters that are not word-chars, spaces, or hyphens.
    * Removes FTS5 operators (AND / OR / NOT / NEAR).
    * Wraps every remaining token in double-quotes.
    * Returns ``'""'`` when input is empty or reduces to nothing.
    """
    cleaned = re.sub(r"[^\w\s\-]", "", user_input)
    cleaned = _FTS5_OPERATORS.sub("", cleaned)
    tokens = cleaned.split()
    if not tokens:
        return '""'
    return " ".join(f'"{token}"' for token in tokens)


def parse_time_minutes(value) -> int | None:
    """Convert a scrapers time value to an ``int`` of minutes, or ``None``.

    Accepts ``int``, numeric ``str`` (e.g. ``"45"``), or ``None``.
    """
    if value is None:
        return None
    try:
        minutes = int(value)
        return minutes if minutes > 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

async def fetch_url_safely(url: str) -> bytes:
    """Validate *url* then fetch it, enforcing size and content-type limits.

    Connects to the pre-resolved IP to prevent DNS rebinding attacks.
    Returns the response body as ``bytes``.
    Raises ``ValueError`` on validation / content-type failures and
    ``httpx.HTTPStatusError`` on non-2xx responses.
    """
    url, resolved_ip = validate_url(url)

    # Pin the resolved IP to prevent DNS rebinding (TOCTOU).
    # We connect to the IP directly but send the original Host header.
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    pinned_url = f"{parsed.scheme}://{resolved_ip}:{port}{parsed.path}"
    if parsed.query:
        pinned_url += f"?{parsed.query}"

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout),
        max_redirects=0,  # Disable redirects on pinned IP — could redirect to internal
        follow_redirects=False,
        headers={
            "User-Agent": "RecipeApp/1.0",
            "Host": parsed.hostname,
        },
        verify=False if parsed.scheme == "https" else True,  # TLS CN won't match IP
    ) as client:
        async with client.stream("GET", pinned_url) as response:
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                raise ValueError(
                    f"Expected text/html content-type, got {content_type!r}"
                )

            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes(chunk_size=8192):
                total += len(chunk)
                if total > settings.max_response_size:
                    raise ValueError(
                        f"Response exceeds maximum size of "
                        f"{settings.max_response_size} bytes"
                    )
                chunks.append(chunk)

    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Main import entry-point
# ---------------------------------------------------------------------------

async def import_from_url(url: str) -> tuple[dict, list[str]]:
    """Scrape a recipe from *url* and return ``(recipe_dict, warnings)``.

    ``recipe_dict`` uses field names that match
    :class:`~recipe_app.models.RecipeCreate`.
    """
    html = await fetch_url_safely(url)
    warnings: list[str] = []

    try:
        scraper = recipe_scrapers.scrape_html(
            html, org_url=url, supported_only=False,
        )
    except Exception as exc:
        raise ValueError(f"Failed to parse recipe from URL: {exc}") from exc

    # -- title (required) ---------------------------------------------------
    try:
        title = sanitize_field(scraper.title())
    except Exception:
        title = ""
        warnings.append("Could not extract title")

    if not title:
        title = "Untitled Recipe"
        if "Could not extract title" not in warnings:
            warnings.append("Could not extract title")

    # -- description --------------------------------------------------------
    description: str | None = None
    try:
        desc = scraper.description()
        if desc:
            description = sanitize_field(desc)
    except Exception:
        warnings.append("Could not extract description")

    # -- ingredients --------------------------------------------------------
    ingredients: list[str] | None = None
    try:
        raw = scraper.ingredients()
        if raw:
            ingredients = [sanitize_field(i) for i in raw]
    except Exception:
        warnings.append("Could not extract ingredients")

    # -- directions ---------------------------------------------------------
    directions: str | None = None
    try:
        raw_instructions = scraper.instructions()
        if raw_instructions:
            directions = sanitize_field(raw_instructions)
    except Exception:
        warnings.append("Could not extract directions")

    # -- image URL ----------------------------------------------------------
    image_url: str | None = None
    try:
        image_url = scraper.image()
    except Exception:
        warnings.append("Could not extract image URL")

    # -- time fields --------------------------------------------------------
    total_time: int | None = None
    try:
        total_time = parse_time_minutes(scraper.total_time())
    except Exception:
        warnings.append("Could not extract total time")

    prep_time: int | None = None
    try:
        prep_time = parse_time_minutes(scraper.prep_time())
    except Exception:
        warnings.append("Could not extract prep time")

    cook_time: int | None = None
    try:
        cook_time = parse_time_minutes(scraper.cook_time())
    except Exception:
        warnings.append("Could not extract cook time")

    # -- servings -----------------------------------------------------------
    servings: str | None = None
    try:
        raw_yields = scraper.yields()
        if raw_yields:
            servings = sanitize_field(str(raw_yields))
    except Exception:
        warnings.append("Could not extract servings")

    # -- nutritional info ---------------------------------------------------
    nutritional_info: dict | None = None
    try:
        nutrients = scraper.nutrients()
        if nutrients and isinstance(nutrients, dict):
            nutritional_info = nutrients
    except Exception:
        warnings.append("Could not extract nutritional info")

    # -- category -----------------------------------------------------------
    categories: list[str] | None = None
    try:
        cat = scraper.category()
        if cat:
            # category() may return a comma-separated string
            categories = [
                sanitize_field(c.strip()) for c in str(cat).split(",") if c.strip()
            ]
    except Exception:
        warnings.append("Could not extract category")

    # -- assemble recipe dict -----------------------------------------------
    recipe_dict: dict = {
        "title": title,
        "description": description,
        "ingredients": ingredients,
        "directions": directions,
        "source_url": url,
        "image_url": image_url,
        "prep_time_minutes": prep_time,
        "cook_time_minutes": cook_time,
        "servings": servings,
        "nutritional_info": nutritional_info,
        "categories": categories,
    }

    return recipe_dict, warnings
