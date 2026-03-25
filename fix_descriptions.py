#!/usr/bin/env python3
"""Fix broken recipe descriptions that contain website hostnames instead of real descriptions.

During initial URL import, scraper.host() was used instead of scraper.description(),
so recipes have website hostnames (e.g. "seriouseats.com") instead of real descriptions.
This script re-fetches the source URLs and extracts proper descriptions.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path

# Ensure src/ is on the import path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import recipe_scrapers  # noqa: E402

from recipe_app.db import connect, update_recipe  # noqa: E402
from recipe_app.models import RecipeUpdate  # noqa: E402
from recipe_app.scraper import fetch_url_safely, sanitize_field  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Pattern to detect hostname-like descriptions:
# No spaces, ends in a common TLD
_HOSTNAME_RE = re.compile(
    r"^[^\s]+\.(com|org|net|co\.uk|io|edu|gov|co|me|info|biz|us|ca|de|fr|uk|au)$",
    re.IGNORECASE,
)


def _looks_like_hostname(desc: str | None) -> bool:
    """Return True if the description is NULL or looks like a bare hostname."""
    if desc is None or desc.strip() == "":
        return True
    return bool(_HOSTNAME_RE.match(desc.strip()))


async def main() -> None:
    log.info("Connecting to database...")
    db = await connect()

    try:
        # Find all recipes with a source_url where description looks broken
        cursor = await db.execute(
            "SELECT id, description, source_url FROM recipes WHERE source_url IS NOT NULL"
        )
        all_rows = await cursor.fetchall()

        candidates = [
            row for row in all_rows if _looks_like_hostname(row["description"])
        ]

        total = len(candidates)
        log.info(
            "Found %d candidate recipes out of %d with source_url",
            total,
            len(all_rows),
        )

        fixed = 0
        skipped = 0
        failed = 0

        for i, row in enumerate(candidates, 1):
            recipe_id = row["id"]
            url = row["source_url"]
            old_desc = row["description"]

            log.info(
                "[%d/%d] id=%d  old_desc=%r  url=%s",
                i, total, recipe_id, old_desc, url,
            )

            try:
                html = await fetch_url_safely(url)

                scraper = recipe_scrapers.scrape_html(
                    html, org_url=url, supported_only=False,
                )

                raw_desc = scraper.description()
                new_desc = sanitize_field(raw_desc) if raw_desc else ""

                if not new_desc or _looks_like_hostname(new_desc):
                    log.info(
                        "  SKIP — scraped description is empty or still hostname-like: %r",
                        new_desc,
                    )
                    skipped += 1
                else:
                    await update_recipe(db, recipe_id, RecipeUpdate(description=new_desc))
                    log.info("  FIXED — new description: %.120s", new_desc)
                    fixed += 1

            except Exception as exc:
                log.warning("  FAILED — %s: %s", type(exc).__name__, exc)
                failed += 1

            # Polite delay between requests
            if i < total:
                await asyncio.sleep(1)

        log.info("=" * 60)
        log.info("DONE — fixed: %d, skipped: %d, failed: %d (of %d)", fixed, skipped, failed, total)

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
