---
title: "Feature: Linear Integration for Issue Tracking + Feedback"
type: feat
status: stub
date: 2026-03-26
---

# Feature: Linear Integration for Issue Tracking + Feedback

## Context

This app is a personal tool, but it has real complexity -- MCP server with 25+ tools, HTMX frontend, multiple agent consumers (Chef for weekly meal planning, OpenClaw for conversational cooking). Bugs, missing features, and rough edges surface constantly during daily use. Right now those observations go into scattered notes, chat messages, or nowhere. A Linear project dedicated to this app would centralize issue tracking, and a direct integration could let the app itself (and its agents) file and read issues without context-switching.

This fits naturally into Sprint 4 (Agent Integration Completeness) since it connects the app to an external system and gives agents a way to report problems they encounter during workflows. The cooking timer floating panel brainstormed in Sprint 2 could potentially share UI real estate with a collapsible feedback/issues panel.

## Problem Areas

### 1. In-App Feedback / Bug Reporting

**The idea:** A persistent "Report Issue" button (or a collapsible side panel) in the web UI that lets the user file a Linear issue without leaving the app. Think of it like the feedback widgets in Vercel or Sentry, but tailored to this app's context.

**What it could capture automatically:**
- Current page URL / route (e.g., `/recipes/47/edit`, `/meal-plans/week/2026-03-24`)
- The recipe or meal plan being viewed (name, ID)
- Browser info (user-agent, viewport size -- useful for HTMX layout bugs)
- Screenshot of the current view (via `html2canvas` or the native `navigator.clipboard` API)
- Recent client-side JS errors from `window.onerror` (cooking mode timer bugs, HTMX swap failures)

**What the user would fill in:**
- Title (short summary)
- Description (free text, markdown)
- Type selector: Bug / Feature Request / UX Friction / Data Issue
- Priority: optional, or inferred from type (bugs default higher)

**Implementation sketch:**
- Frontend: HTMX form in a slide-out panel or modal. Screenshot capture via JS, uploaded as attachment.
- Backend: New router (`routers/feedback.py`?) with a `POST /feedback` endpoint that calls the Linear API to create an issue.
- The Linear API key would live in `config.py` as `linear_api_key`, loaded from `RECIPE_LINEAR_API_KEY` env var.

**Questions to explore:**
- Should the feedback panel be a standalone slide-out, or should it live inside the cooking timer floating panel? The timer panel was brainstormed as a persistent floating element -- combining them could reduce UI clutter but also muddy the purpose.
- How much context is too much? Auto-attaching the full page HTML could be noisy. Maybe just the URL + visible recipe/meal plan name.
- Screenshot capture: `html2canvas` adds a dependency and is flaky with complex layouts. Is a prompt like "paste a screenshot" simpler and more reliable?
- Should feedback go to Linear directly, or to a local `feedback` table first (then sync)? Local-first would work offline and avoid blocking on the Linear API.
- Does the sanitization layer (`sanitize.py`) need to run on feedback text before sending to Linear? Probably not -- it's going to an external system, not stored locally. But if we keep a local copy, yes.
- Auth: this is a single-user app, so no user identity to attach. Should the Linear issue just be unassigned, or auto-assigned to a default user?

### 2. Linear Project Setup

**Dedicated project:** A new Linear project (e.g., "Recipe App" or "Paprika Replacement") with structure tailored to this app's concerns.

**Suggested labels:**
- Area labels: `frontend`, `backend`, `mcp-server`, `agent`, `database`, `scraper`, `ingredient-parser`
- Type labels: `bug`, `feature`, `ux`, `data-integrity`, `performance`
- Sprint labels matching the brainstorm structure: `sprint-1-fixes`, `sprint-2-grocery-cooking`, `sprint-3-calendar-import`, `sprint-4-agent-integration`, `sprint-5-polish`

**Suggested statuses:** Backlog -> Triage -> Todo -> In Progress -> Done -> Won't Fix

**Issue templates:**
- Bug report: steps to reproduce, expected vs. actual, severity, area
- Feature request: user story, acceptance criteria, sprint affinity
- Agent-reported issue: tool name, input that caused the error, traceback, agent context

**Questions to explore:**
- Is Linear overkill for a personal project? The value proposition is really the agent integration -- Linear becomes a shared memory between the human and the agents about what's broken or desired. A simple SQLite `issues` table could serve the same purpose without an external dependency.
- Should cycles in Linear map to the sprint structure (Sprint 2, Sprint 3, etc.) or stay independent?
- How granular should labels be? The area labels above mirror the module structure in `src/recipe_app/`. Is that too fine-grained, or does it help agents triage?
- Should there be a "Known Issue" label that powers the frontend banner (see section 4)?

### 3. Agent Integration (MCP Tools)

**The vision:** Agents like Chef and OpenClaw interact with the app via MCP tools. When they hit errors, encounter missing features, or receive user feedback, they should be able to file Linear issues directly rather than failing silently or surfacing raw errors.

**New MCP tools to consider:**

- `create_linear_issue(title, description, type, priority, labels, context)` -- file a bug or feature request. `context` could be a dict with tool_name, input_params, error_message, traceback.
- `list_linear_issues(status, label, assignee, limit)` -- query open issues. Useful for agents to check "is this a known bug?" before filing a duplicate.
- `update_linear_issue(issue_id, status, comment)` -- add context to an existing issue or close it.
- `search_linear_issues(query)` -- full-text search across issues. Agent could search "ingredient parser" to find related bugs before filing a new one.

**Agent use cases:**
- Chef's weekly cron encounters an error generating a grocery list. Instead of just logging it, Chef calls `create_linear_issue()` with the traceback and the meal plan context. Next morning, the issue is in Linear with full debugging info.
- OpenClaw is helping a user scale a recipe and `scaling.py` produces a weird result. OpenClaw files a bug with the input recipe, scale factor, and incorrect output.
- User tells OpenClaw "the photo upload is broken." OpenClaw calls `create_linear_issue(type="bug", title="Photo upload broken", description="User reported via conversation")` with conversation context.
- Before filing, agents call `search_linear_issues("photo upload")` to check for duplicates and add a comment to an existing issue instead.

**Implementation options:**
- **Direct Linear API calls from MCP tools:** Each tool hits `https://api.linear.app/graphql` directly. Straightforward but couples the MCP server to Linear's GraphQL schema.
- **Linear MCP server as a dependency:** There's already a Linear MCP server available (visible in the tool environment). Could the recipe MCP server delegate to it, or would the agents call both servers? Orchestration gets complex.
- **Wrapper module:** A `linear_client.py` module in `src/recipe_app/` that encapsulates the GraphQL calls. MCP tools and the web UI both use it. Keeps the Linear API surface in one place.

**Questions to explore:**
- Should agents be able to create issues autonomously, or should they always draft and present to the user for confirmation? Autonomous filing could create noise; confirmation adds friction.
- Rate limiting: if an agent hits a recurring error in a loop, it could spam Linear with duplicate issues. Dedup logic? Cooldown period? "File once, then comment on subsequent occurrences"?
- Should the MCP tools talk to Linear directly, or go through the app's backend (which then talks to Linear)? Going through the backend means the app can maintain a local cache/mirror of issues.
- How do agent-filed issues differ from user-filed issues? Label (`agent-reported`)? Different template? Should the filing agent's identity (Chef vs. OpenClaw) be captured?
- The existing Linear MCP tools in the environment (create_issue, list_issues, etc.) -- should agents just use those directly instead of wrapping them in recipe-app-specific MCP tools? That avoids reimplementing the Linear API but loses the auto-context attachment.

### 4. Webhook Events: Linear to App

**The idea:** Linear fires webhooks when issue status changes. The app listens and reacts -- powering features like a "known issues" banner, a changelog, or agent notifications.

**Potential webhook-driven features:**

- **Known Issues banner:** When an issue with label `known-issue` is created or updated in Linear, the app displays a subtle banner on affected pages. E.g., "Known issue: photo upload may fail for HEIC images. Tracking in LIN-42." When the issue is marked Done, the banner disappears.
- **Changelog feed:** When issues move to Done, auto-generate a changelog entry. Could render as a `/changelog` page or a section in the app's nav.
- **Agent notifications:** When a user triages an agent-filed issue (changes priority, adds a comment), notify the agent so it can adjust behavior. E.g., if a scaling bug is marked "Won't Fix -- working as designed," the agent stops flagging it.

**Implementation sketch:**
- New endpoint: `POST /webhooks/linear` that receives Linear webhook payloads.
- Verify webhook signature (Linear provides a signing secret).
- Parse the event, update a local `linear_issues_cache` table in SQLite.
- The banner and changelog features read from the local cache, not from Linear directly (avoids API calls on every page load).

**Questions to explore:**
- Webhook delivery requires the app to be publicly accessible, or Linear needs to reach it. This is a local/personal app -- is it behind a NAT/firewall? Would need ngrok, Cloudflare Tunnel, or similar. Is that worth the complexity?
- Alternative to webhooks: periodic polling (cron job that calls `list_linear_issues` every N minutes and updates the local cache). Simpler, works without public access, but not real-time.
- Is the "known issues" banner actually useful for a single-user app? The user probably already knows about issues they filed. It's more useful if agents are filing issues the user hasn't seen yet.
- Changelog: is this redundant with git commit history? Maybe, but Linear issues capture intent (what the user wanted) while commits capture implementation (what changed). Could be complementary.
- How much of Linear's data model should be mirrored locally? Just open issues? All issues? Comments? Minimal is better -- this is a cache, not a replica.

## Dependencies

- Linear API key (new config field in `config.py`, env var `RECIPE_LINEAR_API_KEY`)
- Linear GraphQL API (or the existing Linear MCP tools for agent-side integration)
- Frontend: minimal new JS for the feedback panel (screenshot capture is optional)
- New router: `routers/feedback.py` for the web UI feedback endpoint
- Optional: `linear_client.py` wrapper module if we go the direct-API route
- Optional: webhook endpoint + public tunnel for real-time sync

## Open Questions

- **Build vs. use existing tools:** The environment already has Linear MCP tools (save_issue, list_issues, etc.). Should the recipe app wrap these in its own context-aware tools, or should agents just call the Linear MCP tools directly with recipe-app-specific conventions?
- **Scope for first version:** What's the MVP? Probably just the web UI feedback button that creates a Linear issue, plus one MCP tool (`create_linear_issue` with auto-context). Webhooks and caching can come later.
- **Local-first or Linear-first:** Should feedback always go to Linear immediately, or write to a local SQLite table and sync? Local-first is more resilient but adds sync complexity.
- **Panel UX:** Standalone feedback panel, or combined with the cooking timer floating panel from Sprint 2? The timer panel is about active cooking; feedback is about meta/reporting. Combining them might be confusing, but having two floating panels is also clutter. Maybe a unified "utility tray" with tabs?
- **Sprint placement:** This brainstorm frames it as Sprint 4 (Agent Integration), but the web UI feedback button is user-facing and could ship in Sprint 5 (Polish + Parity). The agent MCP tools are clearly Sprint 4. Split across sprints, or bundle?
- **Privacy:** If agents auto-file issues with context (recipe names, ingredient lists, meal plans), that personal data ends up in Linear's cloud. Is that acceptable? Linear's data handling policies apply. Could sanitize/redact personal details before filing, but that reduces debugging value.
