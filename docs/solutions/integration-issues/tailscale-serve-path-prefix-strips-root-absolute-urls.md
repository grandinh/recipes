---
title: Tailscale Serve path-prefix mount strips the prefix — breaks apps with root-absolute URLs
problem_type: integration_issue
component: Tailscale Serve + recipe-server (FastAPI) — any app rendered under `/NAME` via `grandin publish NAME PORT`
date: 2026-04-17
tags:
  - tailscale
  - reverse-proxy
  - path-prefix
  - grandin-hub
  - absolute-urls
  - deployment
  - silent-failure
symptoms:
  - "App loads at `https://host/NAME/` but looks unstyled, half-broken, or shows the wrong service's content"
  - "Nav links and HTMX swaps escape the app to whichever service owns `/` on the tailnet (e.g. Glance)"
  - "`journalctl -u <service>` shows only `GET /` hits from the tailnet — never `/calendar`, `/grocery`, `/static/*`"
  - "Loading the same app via `http://127.0.0.1:PORT/` directly works perfectly"
error_messages: []
related_memory: []
---

# Tailscale Serve path-prefix mount strips the prefix — breaks apps with root-absolute URLs

## Problem

The user reported the recipes UI was "a total mess" at `https://ralphsdaily.taile20ebd.ts.net/recipes/` — none of the shipped Linear/Things redesign (`be9b4e2`) was visible. Localhost-direct (`curl http://127.0.0.1:8420/`) returned the correct redesigned HTML, 45kb with sticky header, tabbed detail, Tweaks panel. Via the tailnet URL, the page was unstyled and every nav click dead-ended.

Same class of bug had already bitten Homepage earlier (moved to port `:8441` on 2026-04-13) and is the reason Infisical and Paperclip are published port-based.

## Root cause

**Tailscale Serve strips the path prefix before proxying.** A `grandin publish recipes 8420` registers `/recipes proxy http://localhost:8420`. When a tailnet client requests `https://host/recipes/foo`, Tailscale proxies the rewritten request `GET /foo` to `localhost:8420`. The backend never sees `/recipes` in the URL.

That's fine for the HTML round-trip — the backend returns its homepage HTML as `GET /` would always have. But the returned HTML contains **root-absolute URLs**:

```html
<link rel="stylesheet" href="/static/style.css">      <!-- base.html:7 -->
<a href="/calendar" hx-boost="true">Calendar</a>       <!-- base.html:35 -->
<a href="/recipe/{{ id }}" hx-boost="true">...</a>     <!-- recipes.html -->
```

```js
fetch('/api/recipes/import')                           // app.js:262
window.location.href = '/edit/' + id                   // app.js:275
window.location.href = '/?q=' + encodeURIComponent(q)  // app.js:1059
```

The page's base URL is `https://host/recipes/`, but every one of those URLs begins with `/`. Per [RFC 3986 §5.2](https://www.rfc-editor.org/rfc/rfc3986#section-5.2), the browser resolves them against the **host root**, not the `/recipes/` prefix. Those requests hit whichever service owns `/` — currently Glance at port `8450`. Glance has no `/static/style.css`, no `/calendar`, no `/recipe/2` — so the stylesheet 404s (unstyled page), HTMX nav breaks, JS redirects send the user into Glance.

**Why unit tests didn't catch it.** The full 364-test suite exercises `http://127.0.0.1:8420/*` via httpx. Every route returned 200, every template rendered, every fragment swapped. The test surface never touches Tailscale's proxy layer. The bug lives entirely in the interaction between (a) Tailscale's prefix-stripping semantics and (b) the app's unqualified URL conventions — neither side is wrong in isolation.

## Fix

**Port-based Tailscale Serve mount. Zero code change.**

```bash
sudo tailscale serve --set-path=/NAME off
sudo -u grandin grandin publish NAME PORT --https-port HTTPS_PORT --group Apps --description "..."
```

New URL becomes `https://host:HTTPS_PORT/`. App serves from `/`, every existing root-absolute URL resolves correctly, no regression risk. Matches the precedent already set by Homepage (`:8441`), Infisical (`:8443`), Paperclip (`:8444`), and now recipes (`:8445`).

For the recipes repo specifically (2026-04-17):

```bash
sudo tailscale serve --set-path=/recipes off
sudo -u grandin grandin publish recipes 8420 --https-port 8445 --group Apps --description "Recipe manager"
# https://ralphsdaily.taile20ebd.ts.net:8445/
```

`grandin publish` writes `overrides.yaml` atomically (`https_port: 8445`, drops the stale `path:` key), triggers `hub-healthcheck.service`, and Homepage refreshes its tile on the next poll (≤5 min).

## Why not `root_path="/recipes"` + `url_for()`

The "correct" path-based fix is to tell FastAPI the app lives under `/recipes` (`uvicorn --root-path /recipes`) and convert every absolute URL in templates and JS to framework-generated URLs. Starlette then prefixes generated URLs with `/recipes` automatically.

Rejected for this app because:

- **Surface area.** 30+ absolute URLs across 7 templates, 3 in `app.js`, every HTMX `hx-get`/`hx-post` attribute.
- **Silent-failure-prone.** A missed URL still works on localhost (the test surface) and only breaks in production. No CI signal.
- **Test suite is localhost-only.** The httpx test client never runs under `root_path`, so the tests don't exercise the url-generation path that would be the real regression surface.
- **Marginal user benefit.** The pretty URL isn't worth the churn when port-based mounts are well-understood and already used for three other hub services.

Revisit if/when the app has a legitimate reason to share a host with other path-mounted services (e.g. one subdomain serving many apps). Until then, port-based is the cheaper answer.

## How to detect this class of bug

Three leading indicators, any one of which reveals the problem in under a minute:

1. **Diff localhost vs tailnet.** `diff <(curl -s http://127.0.0.1:PORT/) <(curl -s https://host/NAME/)` — if they differ, the proxy is doing something unexpected.
2. **Watch the backend log after a tailnet click-through.** `journalctl -u <service> -f` then click nav links. If only `GET /` hits arrive and nothing else, the client is navigating to URLs that don't route back to the backend.
3. **Grep the rendered HTML for `href="/` and `src="/`.** If the app uses root-absolute URLs and you're mounting under a path prefix, stop and switch to port-based.

## Prevention

- **Default to port-based (`--https-port`) for any SPA or server-rendered app with root-absolute URLs.** Path-based is only safe for apps that either use relative URLs throughout, or support a `basePath` / `root_path` and have tests that exercise it.
- When adding a new hub service, test the tailnet URL, not just localhost. Homepage, recipes, and (in a different repo) Infisical have all hit this — it's a pattern, not a one-off.
- `grandin publish --https-port` exists specifically for this case. Use it.
