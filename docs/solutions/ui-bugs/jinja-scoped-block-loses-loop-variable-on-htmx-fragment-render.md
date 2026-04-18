---
title: Jinja `{% block scoped %}` silently loses loop variables when rendered as an HTMX fragment
category: ui-bugs
date: 2026-04-17
tags:
  - jinja2
  - jinja2-fragments
  - htmx
  - fragment-render
  - silent-bug
  - template-scope
component: grocery list, recipe fragments
problem_type: logic-error
discovered_in: feat/ui-redesign post-review (PR todo #008)
related:
  - docs/solutions/ui-bugs/fix-qa-display-bugs-scaling-escaping-jsonld-nutrition.md
  - docs/solutions/implementation-patterns/calendar-view-paprika-import-fastapi-htmx.md
---

# Jinja `{% block scoped %}` loses loop-variable context on partial render

## TL;DR

A `{% block name scoped %}` that pulls variables from an enclosing `{% for %}` loop works fine on full-page render, but when the *same block* is rendered as an isolated HTMX fragment via `block_name=` (jinja2-fragments / FastAPI), the loop has not executed — those variables are **undefined and silently render as empty strings**. Any `data-*` attribute that depended on the loop variable turns into `data-foo=""`, which then breaks any client-side code that groups or filters on that attribute.

**Fix:** always pass every variable the block reads *explicitly* into the fragment's context dict, even if the block is also rendered inline elsewhere as part of a loop.

## Symptom

On the grocery page the user could check an item → the row updates via HTMX fragment swap → on next "Hide checked" toggle, the parent aisle failed to collapse (the JS grouped items by `data-aisle=""` which matched no real aisle).

No error in console, no Jinja exception, no 500 — just silent data loss in the DOM.

## Template

```jinja
{# grocery.html — full-page render #}
{% for aisle, items in aisle_groups %}
  <details class="grocery-aisle">
    <summary>{{ aisle }}</summary>
    {% for item in items %}
      {% block grocery_item scoped %}
        <div class="grocery-item" id="item-{{ item.id }}" data-aisle="{{ aisle }}">
          {{ item.text }}
        </div>
      {% endblock %}
    {% endfor %}
  </details>
{% endfor %}
```

The `scoped` modifier is what makes `{{ aisle }}` resolve inside the block during normal rendering — it imports variables from the enclosing scope.

## Fragment-render site

```python
# main.py — /grocery/check/{item_id} returns the grocery_item block alone
return templates.TemplateResponse(
    request, "grocery.html",
    {"item": item, "glist": {}},        # ← `aisle` is NOT passed
    block_name="grocery_item",
)
```

jinja2-fragments runs **only the block body** — the outer `{% for aisle, items %}` loop never executes, so `aisle` has no value. Under Jinja's default undefined semantics, it renders as an empty string, producing `<div … data-aisle="">…</div>`.

## Root cause

`{% block scoped %}` imports loop variables **during a normal render pass that actually reaches the loop**. jinja2-fragments (`block_name=`) skips everything outside the block body. The `scoped` declaration does not establish a requirement that those variables be passed in — it's a permissive import, not a contract.

Result: any block that both (a) is reused as an HTMX fragment *and* (b) references a loop variable will silently render empty values when called as a fragment.

## Fix

Pass every block-referenced variable into the fragment context explicitly:

```python
return templates.TemplateResponse(
    request, "grocery.html",
    {"item": item, "aisle": item["aisle"], "glist": {}},   # ← add aisle
    block_name="grocery_item",
)
```

If the value isn't naturally on the item (e.g. derived from the loop iteration index), either store it on the item before passing, or lift it out of the block:

```jinja
{# Alternative: don't rely on loop scope from inside the block #}
<div class="grocery-item" data-aisle="{{ item.aisle }}">
  {{ item.text }}
</div>
```

The alternative is slightly better architecturally — the block stops depending on outer scope and becomes truly self-contained, which matches how it's invoked as a fragment.

## Detection

**Manual:** check every `{% block X scoped %}` in the codebase for references to `loop.*` or loop-target variables (`aisle`, `item`, `entry`, etc.). For each, identify if that block is *also* rendered as a fragment via `block_name="X"`. If yes, the call site needs the outer-scope values passed in.

```bash
# Find all scoped blocks
rg -n "{% block \w+ scoped" src/recipe_app/templates/

# Find all block_name= call sites
rg -n 'block_name=' src/
```

Cross-reference the two lists.

**Regression test:** render the fragment standalone and assert the `data-*` attribute is non-empty.

```python
async def test_grocery_item_fragment_preserves_aisle(client, create_recipe):
    """Per-item check re-renders grocery_item fragment with a real aisle."""
    # … set up a checked item …
    resp = await client.post(f"/grocery/check/{item_id}", data={"is_checked": "1"})
    assert 'data-aisle=""' not in resp.text
    assert 'data-aisle="Produce"' in resp.text  # or whatever aisle the item has
```

## Prevention

1. **Default pattern:** write fragment-used blocks to be *self-contained* — reference only variables passed explicitly in the context dict. Treat `scoped` as a full-render convenience, not a contract.
2. **Whenever adding a new `block_name=` call site**, read the block body and grep for every `{{ var }}` it emits. Confirm each `var` is either (a) in the context dict, or (b) defined inside the block.
3. **CI check (optional):** a small pytest that iterates the template AST, finds every `{% block X scoped %}` and every `block_name="X"` call, diffs required-vs-provided variables.

## Related regressions from the same redesign review

This finding was one of four silent-bug patterns that surfaced when `/ce:review` ran reviewer agents against the uncommitted UI redesign. All four share the theme "refactor renamed or repositioned things, tests passed, but interactive UI was silently broken":

- **CSS-JS class drift:** JS toggled `.strikethrough` / `.active-step` / `.completed-step` against the legacy CSS names; the redesigned CSS defined `.checked` / `.active` / `.completed`. Cooking mode's strike-through and step progression did nothing. Grep for `classList.add/.remove/.toggle` and cross-check every string literal against the current CSS.
- **HTMX `hx-boost` swaps `<body>`, not `<main>`:** `initAll()` re-init gated on `target.tagName === 'MAIN'`, which never matches on boosted navigation. Widgets that rely on re-init (calendar, scaling, grocery filter, tweaks panel) went dead after the first nav hop. Fix: add `target.tagName === 'BODY'` to the gate, or switch to `htmx:historyRestore` which fires on both.
- **`hx-target="#recipe-grid"` on a header input fires wasted round-trips** on every page that doesn't render the grid. HTMX sends the request; the response is discarded because the target is missing, but the server still did a full template render. Fix: an `htmx:configRequest` handler that calls `evt.preventDefault()` when the target doesn't exist. Do NOT rely on the Enter-key fallback alone — 300ms debounced `input changed` triggers have no keydown.

These three are noted here rather than split into four docs — the compounding lesson is **silent-bug review agents find what test suites miss on frontend refactors**, and this is the signature cluster to expect.

## References

- `src/recipe_app/main.py:473-478` — the fragment-render call site that was missing `aisle`
- `src/recipe_app/templates/grocery.html` — the `{% block grocery_item scoped %}` wrapper
- jinja2-fragments docs: https://github.com/sponsfreixes/jinja2-fragments
- Post-review todos: `todos/008-complete-p1-aisle-empty-state-broken.md` (primary), `007`, `010`, `011` (related regressions)
