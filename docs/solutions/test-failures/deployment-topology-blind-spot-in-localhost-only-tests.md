---
title: Green test suite, broken production — when the test surface doesn't include the deployment topology
problem_type: coverage_gap
component: test suite + deployment layer (any app behind a reverse proxy, path-prefix mount, CDN, or auth edge)
date: 2026-04-17
tags:
  - testing
  - coverage-gap
  - deployment
  - reverse-proxy
  - smoke-test
  - integration-testing
  - process
  - silent-failure
symptoms:
  - "Full test suite passes (364/364 in our case) but the user reports the deployed app is visibly broken"
  - "`curl` against `http://127.0.0.1:PORT/` returns correct output; the external/tailnet URL returns something different or nothing useful"
  - "The diff between them is entirely plumbing: TLS termination, reverse-proxy path stripping, DNS routing, auth edge, CDN rewriting — none of which the app itself controls"
related_memory: []
---

# Green test suite, broken production — when the test surface doesn't include the deployment topology

## Problem

On 2026-04-17, a shipped UI redesign (`be9b4e2`, 364 tests passing) was entirely invisible to the user at `https://ralphsdaily.taile20ebd.ts.net/recipes/`. The fix was operational — republish port-based via `grandin publish recipes 8420 --https-port 8445` — and the specific mechanism is captured in `docs/solutions/integration-issues/tailscale-serve-path-prefix-strips-root-absolute-urls.md`.

This doc is the *meta*-lesson: **why the test suite didn't protect us, and what to do about it going forward.**

## Root cause of the coverage gap

Tests in `tests/` drive the app via `httpx.AsyncClient(transport=ASGITransport(app=app))` or equivalent. They exercise:

- Every route returning the right status code
- Every HTMX fragment rendering with the right structure
- Every form accepting and rejecting the right payloads
- Every DB write landing correctly

What they **do not** exercise:

- Reverse-proxy path rewriting (Tailscale Serve `/recipes` → `/`)
- Root-absolute URLs (`/static/style.css`, `/calendar`, `fetch('/api/…')`) being resolved by a real browser against the actual page URL
- TLS termination, HTTP/2 upgrade, HSTS
- DNS routing via MagicDNS
- Any upstream auth/CDN/WAF layer

Call this the **deployment topology** — everything the request traverses before and after the ASGI app. Our tests validate the app's internal correctness. They say nothing about whether the topology delivers the app's output intact to a real client.

When the topology changes a request in any way — prefix stripping, header rewriting, cookie scoping, caching — and the app's output depends on the untransformed version, the test suite is green and production is broken. The test surface and the production surface are different surfaces.

This is not a Tailscale-specific issue. The same class of blind spot applies to:

| Deployment layer | Potential silent mismatches |
|---|---|
| Nginx / reverse proxy | `X-Forwarded-*` headers, path rewrites, buffer sizes |
| Kubernetes Ingress | TLS passthrough vs termination, path stripping |
| Cloudflare / Vercel Edge | URL rewrites, caching, bot protection, geolocation |
| AWS API Gateway | Stage-based path prefixes, binary-type handling |
| Auth middleware (Auth0, Clerk) | Session cookie scope, redirect_uri mismatch |
| CDN (Fastly, CloudFront) | ETag/Vary-based cache poisoning, range requests |

In each case, a test suite that hits the app directly misses the layer that will, in production, be the actual thing that breaks.

## Why the miss was predictable (in hindsight)

Three signals, any of which should have raised a flag before shipping the redesign:

1. **We changed the app's output shape (templates, asset URLs, inline JS).** Whenever the output shape changes, the deployment topology should be re-verified — not just the app internals. The redesign changed every HTML page; the tests only verified that the HTML existed.
2. **The app uses root-absolute URLs.** `href="/static/style.css"` only works correctly if the app is served from the same origin root as its links. Anything that mounts the app under a path prefix breaks that assumption. `grep -rn 'href="/' templates/` returns 30+ hits — that's a flag.
3. **The hub has precedent for this exact failure mode.** Homepage (2026-04-13) was moved from path-based to port-based publishing for the same reason. Infisical was set up port-based from the start. Three occurrences is no longer bad luck.

## Prevention — pick the simplest that applies

The goal isn't a test-topology framework. It's one cheap check that catches the gap.

### Option A (cheapest): a post-deploy smoke ping in the deploy ritual

Add a one-liner to the shipping checklist: **"curl the external URL, not the internal port, and confirm the HTML looks right."** Literally:

```bash
# After any deploy that affects frontend output shape:
curl -sk --resolve "$HOST:$PORT:$TAILNET_IP" "https://$HOST:$PORT/" \
  | grep -c '<link rel="stylesheet"' # >0 means asset link exists
# Then open in a real browser, hard-refresh, click two nav links.
```

This is free and catches ~every topology mismatch in under 30 seconds. It's what we ended up doing manually during the fix.

### Option B (lightweight): a single smoke test file

For an app that sits behind a topology layer in a known location (tailnet URL for hub apps, Vercel preview for a deployed site), add one smoke test that hits the *external* URL and asserts the minimum:

```python
# tests/smoke/test_external_url.py — runs only in post-deploy, not in unit CI
@pytest.mark.smoke
async def test_external_url_serves_styled_html():
    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(EXTERNAL_URL, timeout=5.0)
    assert r.status_code == 200
    assert '<link rel="stylesheet" href="/static/style.css">' in r.text
    # Now fetch the stylesheet via the SAME base URL and confirm it resolves
    r2 = await client.get(f"{BASE_URL}/static/style.css", timeout=5.0)
    assert r2.status_code == 200, f"stylesheet unreachable under deploy topology"
```

One test. Guards the specific failure mode. Runs out-of-band after deploy, not in CI (which has no tailnet access). Skip if it's too much ceremony for the project.

### Option C (overkill for this project): full deployment-parity test environment

Docker Compose with the same reverse-proxy config as production, run pytest against that. Necessary for enterprise apps; absolute overkill for a personal recipe manager. Mentioned only so the option space is visible.

## Recommendation for this repo

**Do Option A.** The recipes app is single-user, single-environment. A 30-second manual smoke-check after any deploy that changes frontend output shape is strictly cheaper than even the one-test overhead of Option B — and the user will do the browser check anyway to see the redesign.

Concretely, amend the internal ship ritual to one extra step:

> After `systemctl restart recipe-server` on any change that touches `src/recipe_app/templates/` or `static/`:
> 1. Hard-refresh the external URL in a real browser (not localhost, not curl).
> 2. Click one nav link and confirm it stays inside the app.
> If either check fails, the topology changed semantics — stop and diagnose before considering the change shipped.

## Related docs

- `docs/solutions/integration-issues/tailscale-serve-path-prefix-strips-root-absolute-urls.md` — the specific Tailscale mechanism that was the trigger for this meta-lesson.
- `docs/solutions/runtime-errors/systemd-silent-crash-loop-port-already-in-use-eaddrinuse.md` — another "green signal, broken reality" pattern (systemd reported `activating` for three days while actually failing).
- `docs/solutions/test-failures/comprehensive-test-coverage-fastapi-recipe-app.md` — the existing test-coverage-expansion pattern (covers breadth; this doc covers a blind spot orthogonal to that breadth).

## The compounding rule

When green tests meet broken production, the test surface doesn't match the production surface. The cheap fix is almost never "add more tests" — it's one pre-ship check that exercises the layer you've been mocking away. Localhost is an easier, smaller world than production. Tests that live only in that smaller world miss the parts of production that weren't in it.
