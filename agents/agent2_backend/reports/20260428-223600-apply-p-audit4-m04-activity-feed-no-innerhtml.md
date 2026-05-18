# Report: apply-p-audit4-m04-activity-feed-no-innerhtml

- **Task id:** t-fc0375728714
- **Proposal:** P-audit4-m04
- **Severity:** medium
- **Filed by:** agent6
- **Completed:** 2026-04-28

## Outcome: no-op - fix already applied

The `innerHTML` interpolation in the activity feed was already replaced with
`createElement`+`textContent` before this task ran. The current code at
`web/js/dashboard.js:119-122` reads:

```js
const g = document.createElement("span"); g.className = "ev-glyph"; g.textContent = glyph;
const t = document.createElement("span"); t.className = "ev-ts";    t.textContent = ts;
const o = document.createElement("span"); o.className = "ev-op";    o.textContent = op;
const k = document.createElement("span"); k.className = "ev-kind";  k.textContent = e.event || "";
span.append(g, t, o, k);
```

An inline audit comment at lines 114–118 already cites `P-audit4-m04` and
documents the kiosk same-origin threat model. No further changes required.

## Verification

- No `innerHTML` assignment touches `ts`, `op`, or `e.event` in the activity
  feed path.
- `span.className` uses a template literal with `e.event || "?"` - this sets
  the CSS class string, not markup, and is not an XSS vector.
- `span.title` and `span.dataset.*` assignments are also safe (attribute, not
  innerHTML).

## Status: CLOSED (already fixed)
