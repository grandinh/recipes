---
title: systemd silent crash-loop when bound port is already in use (EADDRINUSE)
problem_type: runtime_error
component: recipe-server.service (FastAPI, /root/recipes)
date: 2026-04-17
tags:
  - systemd
  - port-collision
  - crash-loop
  - eaddrinuse
  - silent-failure
  - fastapi
  - operations
symptoms:
  - "`systemctl status <unit>` shows `activating (auto-restart)` indefinitely"
  - "Service is unreachable but no alert fires"
  - "Restart counter climbs into the hundreds (635 in our case) over hours/days"
  - "CPU is wasted on every restart attempt (~2.5s each)"
error_messages:
  - "[Errno 98] error while attempting to bind on address ('127.0.0.1', 8420): address already in use"
related_memory:
  - project_hermes_infisical_rotation_interaction.md (silent-systemd-failure hardening pattern)
  - feedback_hermes_mcp_requires_restart.md (related: daemon restart after config change)
---

# systemd silent crash-loop when bound port is already in use (EADDRINUSE)

## Problem

`recipe-server.service` had been silently failing for **3 days**. `systemctl status recipe-server` showed:

```
Active: activating (auto-restart) (Result: exit-code) since ...
```

— which looks like "starting" but is actually "perpetually failing." The web UI was unreachable. The journal revealed 635 repeated bind failures:

```
ERROR: [Errno 98] error while attempting to bind on address ('127.0.0.1', 8420): address already in use
```

Port 8420 was held by an unrelated, abandoned `vite preview` process (`node` pid 1231 running `/home/user/projects/daily-briefs/build`, an old SvelteKit project not touched since Mar 31). The squatter started Apr 14 22:41 and held the port until Apr 17.

> **Note on `/home/user/`** — that's a directory owned by root, not a separate UID. The system has no `user` account (`id user` → "no such user"). The path is just a workspace name; the process itself runs as root.

## Root cause

**systemd's `Restart=on-failure` (or `Restart=always`) hides bind failures.** When the unit's `ExecStart` exits non-zero, systemd schedules a restart and reports `activating (auto-restart)` in the status one-liner. Without an explicit `StartLimitBurst` (or with one that's never reached), the loop continues forever. The actual error string lives in `journalctl`, not in `systemctl status`. Without checking the journal, the failure is invisible.

The squatting process is the *trigger*; the absent fail-fast guard is the *root cause* of the silent-loop failure mode.

## Investigation

Two commands were enough to diagnose:

```bash
journalctl -u recipe-server -n 40 --no-pager   # find the bind error
ss -tlnp | grep ':8420'                         # find the squatter
```

Identifying the squatter before killing it (so you know what you're nuking):

```bash
ps -fp <PID>
ls -la /proc/<PID>/cwd
```

## Fix

```bash
kill <PID>                                     # remove the squatter
systemctl restart recipe-server                # service can now bind
```

Escalate to `kill -9 <PID>` if the process ignores SIGTERM.

## Verification

```bash
ss -tlnp | grep ':8420'                                # owner should be the service, not the squatter
systemctl is-active recipe-server                      # 'active', not 'activating'
curl -sI http://127.0.0.1:8420/ | head -1              # smoke test
```

## Prevention (ranked by leverage)

### 1. Fail-fast on the unit (highest leverage — single-line fix)

Add to `recipe-server.service` (or any equivalent service drop-in):

```ini
[Unit]
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
ExecStartPre=/usr/bin/bash -c '! ss -ltn "sport = :8420" | grep -q LISTEN'
Restart=on-failure
RestartSec=5s
OnFailure=hub-alert@%n.service
```

After 5 restarts in 60s the unit enters `failed` state — visible to *any* monitor. `ExecStartPre` makes the diagnostic explicit ("port already held") instead of generic EADDRINUSE buried in app logs.

### 2. Hub healthcheck integration

`hub-healthcheck.timer` (per `/srv/hub/`, polls every 5min, ntfy's on failure) should probe recipe-server's `/health` or do a raw TCP bind check on 8420. This catches the `active` state with a wedged app — systemd alone doesn't.

### 3. Generic OnFailure notifier

Create a `hub-alert@.service` template that pipes `journalctl -u %i -n 50` to ntfy. Wire every long-running unit's `OnFailure=` to it. One-time setup, covers all future services.

### 4. Operator pre-flight

Before starting any dev server: `ss -ltnp | grep <port>`. Pre-flight, not post-mortem. Adding to `~/recipes/CLAUDE.md` under "Service Health" makes it discoverable.

### 5. Codify in review

In `compound-engineering.local.md`, add a review checklist item:

> Any new systemd unit must have `StartLimitBurst` set AND either `OnFailure=` or Hub healthcheck registration. Bare `Restart=on-failure` without a limit is a silent-failure trap.

## Lessons

1. `systemctl status` alone is **insufficient** for confirming a service is healthy. The status one-liner conflates "starting" with "perpetually failing." Always confirm with the journal *or* an end-to-end probe.
2. Restart counters in `systemctl status` (e.g., "restart counter is at 635") are the canary. Three-digit restart counts are never normal.
3. Stray dev processes from abandoned projects are real. Audit `ss -tlnp` periodically — squatting is invisible until something else needs the port.

## See also

- `project_hermes_infisical_rotation_interaction.md` — closest prior art on hardening systemd units against silent failure (hermes-gateway absorbing rotation restart bursts).
- `/srv/hub/AUDIT.md` — Hub healthcheck timer setup.
- Recipe app deployment: `recipe-server.service` drop-in at `/etc/systemd/system/recipe-server.service.d/10-hub-bind-loopback.conf`.
