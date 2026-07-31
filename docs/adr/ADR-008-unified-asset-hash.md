# ADR-008: Unified asset-hash for cache-busting + auto-reload

**Date:** 2026-05-12
**Status:** Accepted (s171.8 - shipped 2026-05-12 in commits `1aba0da` + `876fd01`)

## Context

The dashboard at `:8888` has two cache-busting mechanisms that should
answer the same question - *"did any served asset change?"* - and act
together so a single asset edit reaches the operator's browser:

1. **`dashboard/_static.compute_asset_hash()`** drives the `?v=<hash>`
   query-string rewrite in `inject_asset_hash()`. When `web/index.html`
   is served, every `<link>`/`<script>` reference gets its `?v=...` tag
   replaced with the freshly computed hash so the browser sees a new
   URL and refetches.
2. **`dashboard/routes_state._serve_ui_version()`** powers the
   `/api/ui-version` poller. The page polls this endpoint every 4 s; if
   the returned `{"v": ...}` differs from the value at page load, the
   page reloads itself.

Each function independently maintained its own file allow-list:

- `compute_asset_hash` walked **6 root files**: `index.html`,
  `css/dashboard.css`, `js/dashboard.js`, `js/main.js`, `js/sim.js`,
  `js/ws_client.js`.
- `_serve_ui_version` walked a **different 4-file list** - `index.html`,
  `css/dashboard.css`, `js/dashboard.js`, and *one of* the older root
  scripts - and did **not** include `js/main.js` (the s133 ESM
  entrypoint) or anything under `web/{js,css}/panels/`.

The two lists agreed by coincidence in 2026-04 because everything still
lived at the root. They diverged silently in s133 (Phase 3.1 ESM split)
when `js/main.js` became the entrypoint that pulled in `js/panels/*.js`
and `css/panels/*.css`. Then s164 introduced `js/panels/champ_select.js`
and `css/panels/champ_select_view.css`, neither of which was in either
list. Subsequent panel work (s165, s166, s167, ..., s171.7) repeatedly
edited those panel files but the auto-reload poller never noticed.

The operator-visible failure mode: between s164 (2026-05-10) and s171.7
(2026-05-12), every `champ_select.js` edit was invisible. The
`?v=<hash>` rewrite caught the index-load case - so opening a fresh
page picked up new code - but the 4 s auto-reload poller never fired
because the hash it watched didn't include the panel files. Operators
who left the dashboard open through a session never got the panel
updates, and silently served pre-s171.7 `champ_select.js` (which still
gated the champ-select view on opt-in `?cs=1`). The menu route
`applyView` was a direct caller and bypassed the gate, masking the
symptom - operators could click into the new view from the menu, but
the actual `phase=ChampSelect` LCU push routed to the legacy
`cs-overlay` because the runtime code was stale.

## Decision

`/api/ui-version` defers to `compute_asset_hash`. The two paths now
share **one** parts list, computed once and cached for 2 s:

- **Root assets** (explicit names): `index.html`, `css/dashboard.css`,
  `js/dashboard.js`, `js/main.js`, `js/sim.js`, `js/ws_client.js`.
- **Walked subdirectories** (everything inside, sorted by filename):
  - `web/css/panels/*.css`
  - `web/js/panels/*.js`
  - `web/js/lib/*.js`

The hash is `sha1("|".join(f"{rel}:{int(mtime)}" for each part))` -
first 10 hex chars. Computed in `dashboard/_static.compute_asset_hash`;
both `inject_asset_hash` and `_serve_ui_version` call this single
function.

## Consequences

- Future panel additions auto-bust caches without any registry edit. A
  new file under `web/js/panels/` or `web/css/panels/` is picked up on
  the next 2 s cache window and surfaces in the next `/api/ui-version`
  poll within 4 s.
- Auto-reload poller and index-rewrite agree by construction. A change
  to `js/main.js` (or any panel) reaches the operator's browser within
  one poll cycle whether they reopen the page or leave it sitting.
- The s164 -> s171.7 stale-cache failure mode is structurally
  impossible: there is no longer a second list to drift from.
- Bonus: `js/lib/*.js` (state.js, helpers) are also covered now, which
  closes a smaller drift around shared utility edits.

## Trade-offs

- **More `os.stat` calls per compute.** The walked-subdir lists run
  `iterdir` + per-file `stat`. With ~30 panel files in the current tree
  the additional cost is on the order of single-digit milliseconds per
  cache-miss. Cached for 2 s already, so repeated index hits within a
  burst stat nothing.
- **Cache hash changes whenever any of the additional files change.**
  This is the entire point - the previous behaviour silently elided
  panel changes. The operator-facing effect is a 1-RTT reload, which
  is exactly the design intent.
- **`OSError` on a missing subdir is swallowed.** If `web/js/panels/`
  vanishes (it shouldn't, but defensive), the function returns a hash
  based on whatever else was readable rather than 500'ing the index
  request. Matches the prior behaviour for individual missing root
  files (recorded as `f"{rel}:0"`).

## Status

Accepted, shipped 2026-05-12.

- `1aba0da` - expanded `compute_asset_hash` to walk
  `web/{js,css}/panels/*` + `web/js/lib/*`.
- `876fd01` - `/api/ui-version` now delegates to
  `compute_asset_hash` so the two cache-busting paths share one
  source of truth.

The drift this ADR closes was live for ~10 days (s164 ship 2026-05-10
to s171.8 fix 2026-05-12). If a similar parallel-implementations
pattern shows up in a future routing/serving layer, treat it as a
direct ADR-008 violation rather than a fresh problem.
