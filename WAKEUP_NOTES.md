# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + /live-gated-drain (2026-07-08, LEDGER 820) archived 2026-07-09. Only the last 3 sessions kept here.

---

# 2026-07-09 (remove the budget_saver subsystem entirely)

Operator directive (from item 824's NEXT). Executed `docs/BUDGET_SAVER_REMOVAL_PLAN.md` end-to-end.
Full detail: LEDGER 825. Removal only - no engine/schema/scorer change (Tier-0/1).

Two operator-decisions settled first: (1) DROP the vault program - `git rm` both `docs/specs/*VAULT*` specs
(RC_KNOWLEDGE + CANONICAL_LLM; they routed INGEST/QUERY through budget-saver); (2) rotate DeepSeek + NVIDIA
keys operator-side (the LITELLM master key is local-only, moot).

Verified ZERO external coupling before teardown (repo grep of LEAN_CLAUDE / budget-saver / BudgetSaver /
RC_BUDGET_SAVER: every hit is inside `ops/budget_saver/`, docs, or `.gitignore` - NO production launcher
shim; the "3 launchers" are the 4 .ps1 variants IN the dir; CLAUDE.md was already full canonical). Torn
down: unregistered RC-BudgetSaverProxy + RC-BudgetSaverWatchdog (watchdog FIRST - 15-min respawn poll);
`taskkill /F` LiteLLM `:4000` + all 3 Ollama `:11434` procs; `git rm -r -f ops/budget_saver/` (34 tracked,
discarded the held-back lean-settings.json); `git clean -fdx` the untracked `.venv`/state; SHRED
env.local.ps1 (431B x4, never committed); rm CLAUDE.md.full; `git rm` 5 docs (SPEC/PLAN + 2 vault specs +
the executed removal plan); `.gitignore:256-258` removed; ROADMAP bullet -> a do-not-re-pitch decommission
blockquote; cleared 4 OLLAMA_* Machine env vars. Memory `project_budget_saver_removal` marked DONE;
`project_llm_wiki_and_wallpaper_gen_plans` trimmed (vault dropped, independent SDXL lw-gen kept).

Verify: `Get-ScheduledTask RC-BudgetSaver*` empty; no `:4000`/`:11434` listeners; CLAUDE.md git-diff clean;
hygiene 15/15 + ruff green; zero tests reference budget_saver (nightly-full-suite collection-error surface
gone). RC (pid 2792) untouched - budget_saver had zero RC coupling, no restart needed.

NEXT (secondary, still open): BACKLOG "Daemon Slayer scorer calibration" - bruiser-scorer axis-awareness
(the Katarina AD gap), Kalista on-hit-vs-IE, beam boots_unique. Each engine fix = Tier-2 (full dual suite +
DS `:8893` restart + Share mirror). Also owed: operator confirms DeepSeek + NVIDIA keys rotated.

---

# 2026-07-09 (remove archetype-pick UI -> stop committed-precompute pollution)

Operator NEXT from item 823. The DS "Build Archetype" picker let operators write `user_cs` picks into the
shared committed `data/cs_archetype_picks.json` that BOTH build-order precompute tables read via
`get_archetype_for` -> a Katarina->bruiser pick built Katarina AD in everyone's committed tables. Full
detail: LEDGER 824.

Removed (2 surfaces):
- champ-select picker: `_csvArchetypePickerHtml` + `_csvWireArchetypePicker` (the save-user_cs + AUTO-clear
  POSTs) + `.csv-arch*` CSS + the `#csv-archetype-target` mount. KEPT the read-only GET default-resolution
  so the build preview uses the same server DDragon-tag+kit-axis default scorer the coach uses.
- in-game overlay: `active_match.js` `_cycleMeta`/`_BM_META` Row2 right-click cycle; Meta+Ultimate fetches
  now always send `archetype: ""` (server default). It was VIEW-ONLY (never persisted a pick), so no
  committed pollution - removed per operator directive.

Data backfill (Data Fixes rule - BOTH tables + Share):
- cleared `cs_archetype_picks.json` (13 picks) -> `{}`. Only 4 diverged from kit-default: Annie
  assassin->mage, Katarina bruiser->mage, Lulu carry->enchanter, Nilah carry->bruiser (other 9 already
  == default = no-op).
- splice-regen those 4 x sr/aram/arena in the comp-archetype table (`build_orders/`, `--static`) AND the
  flat table read by the deterministic+laning coaches (`daemon_slayer/<patch>/`, live `:8893`) + ran
  `ds_share_sync`. Drift-guarded via Caitlyn byte-identical (engine 1.184.0 == stamp) -> the diff is
  EXACTLY the 4 champs, no drift.
- removed the `58ce5397` `source != default` skip: `test_build_order_axis_parity` now runs unconditionally
  (Katarina mixed-cell AP) and is a pollution tripwire.

UI-audit (3b) caught + fixed a regression: with the picker gone the top-left "PICKS" card was EMPTY in
ARAM/Arena (`#csv-picks-target` is SR-draft-only) -> hid the card + spanned My Pick over the freed left
column (grid kept at 3 tracks so the 1920 + assessment-in-right-column pins hold). Re-audit PASS all 3 modes.

Tests: 631 data-consumer/archetype/build-order + 12 champ-select snapshot renders green; ruff/ASCII/
ds-share-sync `--check` clean. RC restarted.

NEXT from this session (remove the budget_saver subsystem) was EXECUTED 2026-07-09 - see the newest
session block above + LEDGER 825. Do NOT re-pitch a budget-saver / lean-profile / 8B-local fallback.
Secondary (still open): BACKLOG "Daemon Slayer scorer calibration" - bruiser-scorer axis-awareness, Kalista
on-hit-vs-IE, beam boots_unique. Each engine fix = Tier-2.

---

# 2026-07-09 (CI baseline repair -- nightly-full-suite red)

Follow-through on item 822's deferred NOTE: the schedule-only nightly-full-suite (14k, NOT in push/PR CI)
was red on main; RC-CIWatchdog never fixed it (ci-fix/29013242484 had 0 commits ahead). Fixed ~24
deterministic failures in 4 verified slices. Full detail: LEDGER 823. Commits 40afd582 58ce5397 ccbafd5e
adcf0cbe (all pushed; push-CI green). Confirmation nightly dispatched on the fixed HEAD.

Slices:
- S1 40afd582: regen build_order_variants_{sr,aram,arena} at ENGINE 1.184.0 (were 1.182.0 from the 809
  bump; MUST pass explicit --champions for full-roster 173 cells - bare --mode all yields the 10-champ
  seed). $py->$venvPy in BUDGET_SAVER_PLAN.md (bare-py regex). liveStrip->strip test literal.
- S2 58ce5397: made the kit-axis guards hermetic. test_archetype_axis_correction + build_order_axis_parity
  read the live data/cs_archetype_picks.json; the operator's Katarina->bruiser user_cs pick legitimately
  overrides the kit axis. Monkeypatch _load_picks to {} in the default tests; skip picked champs in parity.
- S3 ccbafd5e: u2500-sweep / rc2_p73-quarantine / pengu-skeleton referenced gitignored _archive/ + relocated
  pengu/ files absent on a fresh checkout -> converted missing-target fails to skips.
- S4 adcf0cbe (real logic): a force-cleared coach was re-populated with deterministic action by the
  deterministic layer AFTER apply_cleared_at emptied it -> gated the synthesis on a _was_cleared flag. RC
  restarted (pid 9016 -> 17632, reload_ok).

LEFT RED (DS-judgment, logged to BACKLOG "DS scorer calibration", NOT fixed blind):
- test_beam boots_unique=False: 19a76d8b's T3-boot exclusion + frozenset dedup make a multi-boot build
  unreachable from a boots-only pool. Retire the test or re-scope boots_unique (DS-batch call).
- test_aram_coach_shadow_wire Kalista IE: the generic on-hit AD template (finding B) drops crit IE - may be
  meta-correct for on-hit Kalista. DS-meta call. The Katarina AD build = real bruiser-scorer-not-axis-aware
  gap (finding A/B family).
Pre-existing full-suite-LOAD flakes (coach_poll_offload x2, ds_matchdb_mcp auth) all pass in isolation - untouched.

OPERATOR NEXT (2026-07-09, post-wrap interrupt) -- ROOT-CAUSE PREVENTION for the archetype-pick pollution:
- Remove the DS archetype OPTION BUTTONS from the champ-select menu (the `.csv-archetype-picker` in
  web/js/panels/champ_select.js:2567 + its two `/api/cs-archetype-pick` POSTs at :2611/:2650; route
  dashboard/routes_archetype.py, store data/cs_archetype_picks.json). Goal: operators can no longer write
  user_cs picks that pollute the shared committed precompute tables (Katarina->bruiser was the LEDGER 823
  root cause).
- Remove the RIGHT-CLICK archetype switching from the in-game build overlay panel (web/js/panels/ds_shaper.js
  contextmenu path + overlay_item_radial.js if it carries an archetype swap).
- Decide existing-pick handling: after removing the UI, either clear data/cs_archetype_picks.json (precompute
  reverts to kit-default) or keep the picks read-only. Frontend slices -> run the 3b UI-audit ritual before
  commit. This likely also greens test_build_order_axis_parity[Katarina] + the archetype_axis guards
  permanently (the scoped-skip from 58ce5397 becomes unnecessary).
