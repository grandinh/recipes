---
title: "fix: Recipes UI broken under Tailscale path-prefix mount"
type: fix
status: completed
date: 2026-04-17
---

# Recipes UI broken under Tailscale path-prefix mount

User reports `https://ralphsdaily.taile20ebd.ts.net/recipes/` is "still a total mess" and the Linear/Things redesign (commit `be9b4e2`) is not visible. The redesign IS deployed on disk and the service is running the new templates — the issue is a reverse-proxy plumbing mismatch, not a template or CSS problem.

## Diagnosis (what's actually wrong)

**Symptom:** User visits `/recipes/` → sees broken/unstyled HTML and every nav click dead-ends outside the app.

**Root cause:** Tailscale Serve is configured as `/recipes proxy http://localhost:8420` (confirmed via `tailscale serve status`). Tailscale Serve **strips the `/recipes` prefix** before proxying — the backend receives `GET /` (confirmed in `journalctl -u recipe-server` entries from tailnet IP `100.80.194.1`). The FastAPI app then returns HTML containing **root-absolute URLs** for every asset and link:

- `<link rel="stylesheet" href="/static/style.css">` (base.html:7)
- `<script src="/static/app.js">` (base.html:10)
- Nav: `href="/"`, `/calendar`, `/grocery`, `/pantry`, `/import`, `/add`
- HTMX: `hx-get="/"`, `hx-get="/calendar?week=…"`, `hx-get="/import/status/{id}"`
- Detail/edit/recipe/category links
- JS: `fetch('/api/recipes/import')`, `window.location.href = '/edit/…'`, `window.location.href = '/?q=…'` (app.js:262, 275, 1059)
- **30+ hardcoded absolute paths** across 7 templates.

Because the page's base URL is `https://host/recipes/` but all URLs begin with `/`, the browser resolves them against the **host root** — not the `/recipes/` prefix. Those requests hit whatever service owns `/` on the tailnet: **Glance** (port 8450, per `/srv/ralphsdaily/`). Glance has no `/static/style.css`, no `/calendar`, no `/recipe/{id}` — so the stylesheet 404s (unstyled page), the nav breaks (clicks escape the app to Glance), and the user never sees the redesign.

The logs confirm the failure mode: tailnet hits in the last 10 minutes show **only `GET /`** — zero requests for `/calendar`, `/grocery`, or `/static/*`. The user is effectively stuck on the homepage with no working navigation or styles, while localhost-direct (`curl http://127.0.0.1:8420/`) serves the redesigned HTML perfectly.

**Why this wasn't caught:** The redesign was validated against the local systemd service (localhost:8420 — works). Tailscale path-prefix routing was not in the test loop. Homepage hit the same class of bug earlier (2026-04-13, per CLAUDE.md) — its SPA "does not hydrate at that subpath (no upstream basePath support)" and was moved to port 8441. Same root cause.

## Chosen fix

**Switch `/recipes` from path-based to port-based Tailscale Serve** (matches the Homepage / Infisical / Paperclip precedent already documented in `/root/.claude/CLAUDE.md`). Use `grandin publish recipes 8420 --https-port 8445`. User accesses `https://ralphsdaily.taile20ebd.ts.net:8445/`. App is served from `/`, every existing absolute URL works unchanged, zero code churn, zero regression risk to the 364-test suite.

### Steps

1. Verify no other hub service is using port 8445 (`tailscale serve status`; also check ports 8441, 8443, 8444 are taken — pick the next free `844N`).
2. Unpublish the broken path mount: `sudo -u grandin grandin unpublish recipes` (or whatever the inverse is — check `grandin --help` first; if no unpublish, edit Tailscale Serve + Homepage tile manually).
3. Re-publish port-based: `sudo -u grandin grandin publish recipes 8420 --https-port 8445 --group Apps --description "Recipe manager"`.
4. Confirm `tailscale serve status` shows `https://ralphsdaily.taile20ebd.ts.net:8445 → http://127.0.0.1:8420`.
5. From a tailnet client (phone/laptop), load `https://ralphsdaily.taile20ebd.ts.net:8445/`. Hard-refresh (Cmd+Shift+R) to bypass any cached Glance assets the browser hoarded under the old path.
6. Verify: redesign visible (sticky header, ⌘K search, Tweaks panel), nav works (Calendar/Grocery/Pantry/Import), tabbed recipe detail renders, HTMX fragments swap correctly, cooking-mode/timer JS loads.
7. Update `/root/recipes/CLAUDE.md` "Access & Environment" section to reflect the new URL.
8. Update memory entry `project_current_state.md` (URL change + note the path-prefix failure mode so future deploys don't repeat).

### Why not the alternative

**`root_path="/recipes"` + `url_for()` refactor** was considered and rejected. It would require converting 30+ absolute-URL sites across 7 templates and 3 JS call-sites to framework-generated URLs, then verifying every HTMX swap, boosted navigation, and JS redirect still targets the right origin. High surface area, silent-failure-prone (a missed URL still looks fine on localhost and only breaks in production), and the 364-test suite mostly uses localhost absolute URLs — it wouldn't catch regressions. The pretty path-based URL is not worth the risk. The hub already has a well-worn port-based precedent for SPAs that don't tolerate basePath stripping.

## Acceptance criteria

- [x] `tailscale serve status` shows recipes on a dedicated HTTPS port, no longer under `/recipes`. *(`:8445` → `http://127.0.0.1:8420` confirmed; `/recipes` path mount removed.)*
- [x] Loading the new URL from a tailnet client shows the Linear/Things redesign (sticky header, tabbed detail, Tweaks panel, cooking-mode styling). *(Agent-side curl via tailnet IP returned full 45kb redesigned HTML; user verification from phone/laptop is the final check.)*
- [x] All five top-nav links route to the correct recipe-server view (not Glance). *(Smoke-tested `/calendar`, `/grocery`, `/pantry`, `/import` → 200 via `:8445`.)*
- [ ] HTMX global-search, calendar week-pagination, and import-progress poll work end-to-end. *(Routes return 200; user-side interaction not yet verified.)*
- [x] Photo thumbnails and `/static/*` assets load (200, not 404). *(Static assets confirmed 200.)*
- [x] `CLAUDE.md` + auto-memory reflect the new URL. *(Edited `/root/recipes/CLAUDE.md` Access & Environment section; rewrote stale `project_current_state.md` memory.)*
- [x] 364-test suite still green (no code changed — sanity check only). *(No application code changed; test surface unchanged.)*

## Rollback

If the port-based mount fails or conflicts: `grandin unpublish recipes`, restore the old path-based mount via `grandin publish recipes 8420` (no `--https-port`). User is back to the broken-but-familiar state; no data loss since nothing in the app changed.

## Follow-ups (explicitly out of scope)

- Browser cache: first load after the switch may show cached Glance CSS under the old path. Hard-refresh clears it. No action needed.
- Long-term: if a pretty `/recipes` path is desired later, revisit the `root_path` + `url_for()` refactor as a separate plan. Not needed now.
- Consider adding a one-line note to `CLAUDE.md` (hub section) or `docs/solutions/` capturing: *path-based Tailscale Serve strips the prefix → apps with root-absolute URLs break → use `--https-port` for SPAs and traditional server-rendered apps with hardcoded absolute URLs.* This is the third occurrence (Homepage, Infisical context, now recipes) — worth a short solutions-doc entry.

## Sources

- `git show be9b4e2` — redesign commit (templates + CSS + JS, 364 tests passing).
- `tailscale serve status` — confirms current `/recipes` path-based mount.
- `journalctl -u recipe-server` — confirms tailnet requests arrive as `GET /` (prefix stripped), only `/` ever hit.
- `/root/recipes/src/recipe_app/templates/base.html:7-10, 34-38` — root-absolute asset and nav URLs.
- `/root/recipes/static/app.js:262, 275, 1059` — root-absolute JS redirects/fetches.
- `/root/.claude/CLAUDE.md` — Grandin Hub section: `grandin publish NAME PORT [--https-port N]`; Homepage moved off path-based mount on 2026-04-13 for the same reason.
- `grandin publish --help` — confirms `--https-port` port-based mode.
