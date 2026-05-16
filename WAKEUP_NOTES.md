# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s224 wrap — 2026-05-16 (DS Phase 5.9.24: unmapped-key pass — Bel'Veth R + _UNIT_TO_FIELD variant family)

**Operator instruction:** same self-paced loop ("continue ds work in parallel for the next hour self continue — maximum effort"). This is **iteration 2** (s223 was iteration 1, same session-day).

## What happened — worked the space orthogonal to s223's saturation finding

s223 proved the *uncovered-champion* block_index space saturated. s224 worked the other axis: ability KEYS on already-covered champions not yet in the registry. Built `tools/ds_unmapped_key_prefilter.py` (runs the s223 ground-truth A/B over every unmapped key of all 125 covered champs, full-HP + 40%-HP passes) → tight **7-item shortlist**. 2 were documented skips (Corki R = s194 every-4th-missile; DrMundo Q = s203 conditional-higher-vs-full-HP), 3 were false flags on already-mapped siblings. Two real findings:

## Shipped (committing now)

1. **`Belveth: {R: 1}`** — block 1 "True Damage" (150-250 + 100% AP + 25% missing-HP) is the canonical Endless-Banquet recast nuke; engine defaulted to block 0 ("Bonus True Damage" 6-10), live A/B **8→450 raw (56×)**. This **corrects s223's over-conservative "Bel'Veth R = no entry, already parsed" call** — field-parsed ≠ engine-block-selected (engine always defaults to block 0; an explicit entry is needed to select block 1). The s223 test `test_kayle_belveth_R_remain_unmapped` was rewritten → `test_kayle_unmapped_belveth_R_added_s224` (s223→s224 evolution guard). Bel'Veth → `{E:2, R:1}`.
2. **`_UNIT_TO_FIELD` text-drift family (s223-sibling)** — the pre-filter exposed 8 missing Meraki health-unit variants: double-space `"%  of target's current health"`, `"the target's"` maximum/missing forms (single+double space), caster-max pronoun/name forms (`"% of his/her maximum health"`, `"% of Braum's/Zac's maximum health"`). Added; `tools/migrate_abilities_unit_variants_s224.py` (same audit-gated zero-re-fetch contract as s223, reuses its `_promote`/`_recompute_parse_status`, idempotent) promoted **exactly 32 mods across 13 champs** (Ambessa Q · Braum Q · Briar W · Fiddlesticks Q · Gnar E · Gwen Q·R · Maokai Q · Sejuani W · Skarner E · TahmKench R · Trundle R · Varus W · Zac Q) whose %HP component was dropped. **Trundle R + Fiddlesticks Q evaluated 0 entirely pre-s224** (live A/B Trundle R 0→500, Fiddle Q 0→72). Skipped non-clean: TahmKench Q / Pantheon W `% AP per 100 bonus health` (hybrid), AurelionSol Q malformed Stardust string.

ENGINE 0.95.0→0.96.0; 5 pin bumps + `test_block_index_overrides` Belveth shape-pin update + `test_unit_variants_s224.py` (18 tests). DS suite 2086→**2104**; wider RC **1107**; DS server restarted → `/health` 0.96.0.

## Don't-redo / blockers

- **Don't `--force` re-extract** to apply parser fixes — Meraki `latest` is mutable (patch-bump + churn risk). The two migration scripts (`migrate_abilities_nested_hp_s223.py`, `migrate_abilities_unit_variants_s224.py`) are **historical artifacts** like DB migrations — don't refactor old ones; write a new dated one per parser change. All idempotent + hard audit-gated.
- **Varus W is now a FUTURE block_index candidate** — s224 parsed its Blight-stack maxHP (blocks 1-4) but the engine defaults Varus W to block 0 (18-dmg passive on-hit). A `Varus: {W: <blight-block>}` entry would surface the detonation — but pick the right block (per-stack vs max-stack vs the Q/R-detonation interaction) carefully; this is iteration-3+ material.
- s224's `test_target_max_hp_textdrift_promoted` etc. pin the live snapshot — if the snapshot is ever cleanly re-extracted (new patch), these stay green because the fixed `_UNIT_TO_FIELD` produces the same typed fields.

## NEXT (self-continuing loop)

Unmapped-key space near-exhausted (only Bel'Veth R was a clean find across 125 champs). Iteration 3 options: (a) Varus W block_index entry (data now parsed); (b) audit the *form_index* / *combo_sequence* registries for similar gaps; (c) the conditional-target-state schema lift (architectural — flag for operator, don't ship autonomously). s220 aggregator G Post-Game-Review reframe remains the big pending UI item.

---

# s223 wrap — 2026-05-16 (DS Phase 5.9.23: nested %HP parser fix + provable block_index saturation)

**Operator instruction:** "continue ds work in parallel for the next hour self continue — opus 4.7 1m maximum effort". Self-paced loop; this is iteration 1.

## What happened — parallel batch ran, found the registry is saturated, pivoted to the real debt

Applied the **parallel-batch-agents** pattern: built `tools/ds_block_scanner.py` (filtered-index ground-truth A/B helper — verified against Aatrox's documented s197/s199 multipliers) then spawned **5 parallel research agents** over all **47 not-yet-covered champions** (alphabetical slices). Every agent independently returned **zero** block_index proposals. Cross-checked by an independent enumeration: only 20 multi-damage-block (key,form) pairs exist among the 47, every one a documented skip (single-block / block-0-already-single-target-max / nested-parser / malformed-Meraki / card-choice / turret-pet). **The s191→s217 single-int/list `block_index` registry is provably saturated** — future growth needs the conditional-target-state schema lift or upstream Meraki fixes, not more uncovered-champion scanning. This is a real, valuable negative result (closes a 12-session line of work).

**Pivot** (don't ship an empty batch): tackled the longest-deferred DS debt instead — the s199→s217 "nested missing-HP parser bucket". Root cause: Meraki encodes %-target-health scalings behind nested conditional `(+ ...)` parentheticals (Kindred E `"% (+ 0.5% per Mark) of target's missing health"`, K'Sante W doubly-nested per-resist, Kindred E block1 recursively-nested) that `_normalize_modifiers` dropped into `unparsed_modifiers` → the entire %HP damage component was silently uncounted since Phase 4a.

## Shipped (uncommitted at time of writing — committing now)

- **`tools/daemon_slayer_abilities_extract._canonicalize_unit()`** — strips `(+ ...)` groups innermost-first (regex loop, handles arbitrary nesting). Purely additive: no-op for units without `(+`, so recognized units are byte-identical (raw-match-wins guard). Wired as a fallback after the raw `_UNIT_TO_FIELD` lookup.
- **`tools/migrate_abilities_nested_hp_s223.py`** — deterministic **zero-re-fetch** in-place migration (re-parses only `unparsed_modifiers`, which preserve original `{values,units}`). Imports the extractor's own helpers so logic == a future clean re-extract. **Hard audit gate**: aborts without writing unless it touches exactly the 22 audited mods across the 10 expected champions (drift = Meraki changed). Promoted 22 mods / 10 champs (Amumu W · Cho'Gath E×2 · Elise Q×2 both forms · Evelynn E×2 · K'Sante W×4 · Kindred W+E×2 · Kled W · Sett Q×2 · Shen Q×4 · Zac W). Live A/B (vs 2000 HP): Cho'Gath E +250%, Zac W +200%, K'Sante W +152%, Amumu W +300%, Sett Q +40% raw.
- **`Kindred: {E: 1}`** registry entry — enhanced-execute (7.5% missing-HP vs block 0's 5%). Monotone ≥ block 0; exact no-op at full HP (engine default `target_current_hp_pct=1.0`); +21% at 40% HP. Registry 124→125 champs.
- **`tools/ds_block_scanner.py`** (kept — reusable for any future scan/audit).
- ENGINE_VERSION 0.94.0→0.95.0; 4 pin bumps. **`agents/daemon_slayer/tests/test_nested_hp_parser_s223.py`** (26 tests: canonicalizer / `_normalize_modifiers` integration / live-snapshot migration correctness / Kindred E A/B monotone+no-op / saturation guards). DS suite 2060→**2086**; wider RC **1107**; DS server restarted (pid was 16472) → `/health` 0.95.0.

## Don't-redo / blockers

- **Do NOT re-scan uncovered champions for block_index** — provably saturated (the registry `_meta.description` Phase 5.9.23 note + `test_nested_hp_parser_s223.SaturationAndBackwardCompatTests` pin this). Next block_index work is the **conditional-target-state schema lift** (`block_index: int | list[int] | dict[str,int]`) — needs operator schema sign-off, candidates: Lux Illumination, DrMundo E missing-HP, Renekton Q full Fury, Zed shadow-Q, TwistedFate card-choice.
- **Do NOT re-run the extractor (`--force`)** to apply the parser fix — it hits Meraki's mutable `latest` and would risk a patch bump + smear unrelated churn. The migration is the deterministic path; it's idempotent (re-running finds 0 to promote).
- Kayle E / Bel'Veth R are **NOT** parser-gap champions — their `target_missing_hp_pct` was already parsed pre-s223 (only second-order `% per 100 AP` amps stay unparsed). The s217 hand-off mischaracterized them. No entry warranted; Bel'Veth keeps only its prior `{E:2}`.
- DS server :8893 is HTTP not HTTPS and NOT supervisor-watched — restart via `taskkill /F /PID` (use the **PowerShell tool**, Git-Bash mangles `/F`) + `Start-Process pythonw tools\start_daemon_slayer.py`.

## NEXT (self-continuing loop)

Conditional-target-state schema lift is the next DS frontier but is an architectural change wanting operator sign-off — flag it rather than ship autonomously. Subsequent loop iterations: audit covered champions for *additional* uncovered KEYS (distinct from the saturated new-champion space), or DS calibration once rewind data refreshes. s220 aggregator G Post-Game-Review reframe remains the big pending UI item.

---

# s218 wrap — 2026-05-15 (Home page redesign + foundation overhaul)

**Operator instruction:** "doing ui work" — open-ended iterative pass on the Home view. Closed out with "this page is done now. commit and /done".

## Shipped — single commit (`4518ed9`)

**Foundation (applies to all views going forward):**
- Pin RC menu width at 230px (static across views; fits longest case "AUTO · PRE-GAME LOBBY"). `.title-current` switched from min-width to fixed width per operator hard rule.
- Bump typography +1px globally — 414 declarations across 14 panel CSS files via Python script; RC menu rules (4 skipped) preserved per directive.
- Flip body zoom default 1.33 → 1.0 in `base.css`. Fixed dev.js/main.js localStorage key mismatch (slider wrote `rc-zoom`, page-load read `rc-body-zoom` — body was always 1.33 regardless of slider position). Both now use `rc-zoom`.

**Dev/Sim Preview removal** (separate concern operator green-lit mid-session):
- Drop `#view-dev` section + menu item + `#sim-banner` block.
- Delete `web/js/sim.js`, `web/css/panels/dev.css`, `dashboard/routes_dev.py`.
- Archive `data/sim/*` + `data/sim_states.json` → `docs/_archive/2026-05-15-dev-sim-removal/`.
- Scrub orphan refs across `agents/supervisor.py`, `dashboard/_state_builder.py`, `dashboard/_handler.py`, `dashboard/_static.py`, `riot-commander.spec`, `tools/extract_panels.py`, `web_dashboard.py`, `view_router_state.py`.

**Home view content:**
- **7-tile quick actions** in operator's order: Find Match · Last Match · Session · History · Replay · Builds · Settings. Equal-width centered tiles. Find Match accented with lavender gradient + info-soft border + lavender icon (primary action signal).
- **Find Match opens a Home-unique queue picker modal** (centered fixed-position, backdrop dimmer, Escape/outside-click close). Mirrors lobby-view's `#lv-mode-menu` queue list with `data-hfm-*` attributes. Click → fires `change_queue_type` LCU command → routes to Pre-Game Lobby. Two false-start iterations resolved: synthetic `.click()` on `#lv-mode-trigger` after route was racing with the document outside-click handler → final landed approach is `e.stopPropagation()` on tile click + direct DOM mutation of menu's `hidden` class.
- **Tonight's Pick 3-section restructure**: Section 1 = champion intro (icon + name + meta); Section 2 = THE GOOD / THE BAD / THE UGLY placeholder rows tagged `data-dummy-data="tonights-pick-tips"`; Section 3 = STREAK / ADVISORIES sub-header rows wired live to `_HOME.streaks` (play_days + good_grades) and `#advisory-count`. Layout: `grid-template-columns: auto 1fr 1fr` so Section 1 sizes to content + Section 2 starts at a finite boundary after "best B" text. Section 3 uses 88px label col + 16px gap (matches Section 2) for symmetric label-value spacing. "Open Advisories" → "Advisories" rename to fit column. 14px row-gap between Streak + Advisories rows.
- **Recent 5 row updates**: spell out "X Minutes" (was "Xm"), append CS + CS/min chip, 6-slot placeholder item strip tagged `data-dummy-data="items-pending-ingest"`. Card click → History view with `sessionStorage.rc-history-focus-ts` → auto-select date-matching session + scroll target row + pulse-highlight class for 3.5s.
- **This Week row updates**: KDA breakdown "1.8 22/10/18" (avg + raw totals), AVG CS per game + CS/min (operator clarified avg not total), grade-tint demoted from card-bg-tint to 3px left-border accent (transparent bg + bottom-only divider — operator wanted list, not cards). Bumped `.home-week-bar-kda-raw` 13 → 14px to separate hierarchy from 15px ratio pill.
- **Backend (`dashboard/builders.py`)**: `/api/home/summary` recent[] gains `cs`, `cs_per_min`, `items[]`, `mode_subtype`; this_week[] gains `kills`, `deaths`, `assists`, `cs_total`, `cs_per_min`. RC hard-restarted (pid 18628 → 15752) via `taskkill /F /PID + restart.bat` after `restart_trigger.txt` mechanism didn't consume two attempts.
- **Hero headline**: drop absolute-threshold `up/down` classifier (was rendering 1.27 KDA as `.down` salmon-red despite no comparison baseline). Always `.flat` text-dim until real yesterday-comparison baseline ships.
- **Tonight's Pick "Jinx" name → History filtered by champion**: clickable (cursor:pointer + green-tinted underline on hover) → `sessionStorage.rc-history-focus-champion` → `_historyFetchAndRender` finds most recent session containing that champion + highlights all matching match rows + scrolls to first.

**Footer + tooltip polish:**
- Footer height 44 → 36px, color `--text-faint` → `--text-dim`, line-height 1, all children `inline-flex; align-items: center`. ui-version pill opacity 0.6 → 0.85.
- `wrapSixWords` (tooltip system) was splitting on ALL whitespace (including `\n`) so multi-section tooltips collapsed into one long line. Now preserves explicit `\n` boundaries, wrapping each source line independently at 6 words → RC pip / health-dot multi-section tooltip renders per-row.

**Cleanup:**
- Drop orphan `.home-pick-btn*` CSS (advisory + digest pip-buttons that Section 3 redesign replaced).
- Drop orphan `wireAlertRow` calls in `_homeWireStartup`.
- Drop orphan `view-dev` CSS selectors in header.css.
- All edits verified: py_compile clean on touched Python files; 27/27 view-router tests; live dashboard auto-reloaded via asset-hash; cache-bust hash flipped to `b5f4bf09c6`.

## Visual audit
Mid-session ran a `general-purpose` Agent for independent UI review. Surfaced 3 must-fix + 4 should-consider + 5 leave-alone findings. Operator picked 6 of 7 to apply (skipped #1 as false positive after re-verification). All 6 applied + verified live.

## Tests / verification
- `tests/test_view_router_state.py`: 27 pass + 16 subtests.
- `tests/test_routes_ds_preview_scorer.py` + `tests/test_state_builder_archetype_pick.py` + `tests/snapshot_panels/`: 59 pass + 16 subtests in 18.65s combined.
- Manual: Recent 5 click → History deep-link pulse-highlight verified by operator. Find Match picker modal → operator clicked queue → routed to Pre-Game Lobby successfully.

## What's next
- **Operator signaled next session = next view.** Page order likely: Pre-Game Lobby → Champ Select → Active Match → Last Match → Session → History → Replay → User Builds → Settings.
- **Tagged-for-removal placeholders** stay until backend work catches up: `data-dummy-data="tonights-pick-tips"` (needs post-match Good/Bad/Ugly analyzer), `data-dummy-data="items-pending-ingest"` (needs `items[]` column in match_history.db ingest), `builders.py` `items: []` + `mode_subtype: null` placeholders (same).

## Blockers / don't redo
- **Heartbeat ♥ — in header top-right** flagged by operator: WS heartbeat envelope (`{type:"heartbeat", t:epoch}`) doesn't re-arm immediately after RC restart. The dashboard at `web/js/main.js:5026` populates `#heartbeat` only on WS envelope arrival; supervisor's broadcast loop needs investigation. Don't re-investigate the WS connection itself — `ws://192.168.8.230:8891/push` is confirmed connected (footer shows it).
- **`restart_trigger.txt` watcher wedge** confirmed pre-existing — the supervisor's poll loop at `ops/rc_supervisor.py:1240` didn't consume trigger files on 2 attempts this session. Workaround: hard `taskkill /F /PID + restart.bat` documented as standard. Don't re-debug; existing memory entry `project_rc_supervisor_restart.md` already covers.
- **Hero headline up/down classifier removed**: do not re-add until a proper yesterday-comparison baseline is wired into `/api/home/summary`. Operator explicitly prefers flat over wrong-direction-tinted.
