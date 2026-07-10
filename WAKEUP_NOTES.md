# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + /live-gated-drain (2026-07-08, LEDGER 820) archived 2026-07-09. Only the last 3 sessions kept here.

---

# 2026-07-09 (DS comp-aware boot utility scorer, DEFAULT-OFF; ENGINE 1.186.0)

BACKLOG "DS scorer calibration" enhancement #2 (boot utility-awareness). Full detail: LEDGER 827.
Tier-2, commit 0aa116af, DS :8893 restarted to 1.186.0 (health engine 1.186.0, patch 16.13.1).

- NEW `agents/daemon_slayer/boot_utility.py`: per-boot utility scorer (normalized axis vectors weighted by
  enemy AD/AP share + a v1 CC proxy; argmax with archetype-default hysteresis). Two cases: OFFENSIVE champs
  hold their kit boot unless the comp is lopsided; DEFENSIVE champs (tank/bruiser) pick Steelcaps-vs-AD /
  Mercury's-vs-AP by damage type. Behind DEFAULT-OFF `assume_boot_utility` in `core/build_order._select_boots`
  (OFF byte-identical - OFF-parity + ON-neutral==OFF invariant guarded); `plan_build_order` threads the flag.
  `ops/audit/boot_utility_preview_diff.py` = a NON-committing preview of what would flip if default-ON.
- The preview earned its keep: it caught a backwards first-pass calibration (tanks biased to armor vs AP);
  root-cause-reworked to the damage-type model above.
- ENGINE bump was UNDER-SCOPED at first (only __init__.py) - the read-only verifier FAILED the first
  commit-attempt on 120 unpropagated pins; completed the repo-wide sweep (105 DS test pins, docs banner,
  6 precompute stamps byte-level content-identical, Share/src 417 --check clean) before commit.
- Verify: full dual suite 19298 passed / 17 skipped; the only 2 reds are a PRE-EXISTING coach-poll asyncio
  isolation flake (`test_coach_poll_offload_hot03`, passes in isolation, unrelated); boot suite 14 RED-first;
  ruff clean.

NEXT: (a) the default-ON flip (live-game gated; 1-line RC-side caller default per project_ds_live_flip_seams);
(b) real per-champion enemy CC threaded into `_select_boots` (v1 uses the ap-share proxy, under-crediting
frontline CC); (c) the flagged SEPARATE finding - the committed full-roster build-order precompute tables
look STALE vs the generator (task chip "Investigate stale DS precompute build-order tables"; do NOT
`--mode all` regen, it clobbers to a 10-champ seed). Do NOT re-flag boot utility as unfixed - SHIPPED
DEFAULT-OFF (LEDGER 827). (WAKEUP prune to 2-3 blocks is due - weekly-hygiene relocate job.)

---

# 2026-07-09 (DS bruiser scorer axis-awareness + retire/relax 2 stale tests; ENGINE 1.185.0)

Closed the 3 DS scorer-calibration reds from LEDGER 823/824 (BACKLOG "DS scorer calibration"). Full
detail: LEDGER 826. Tier-2 (ENGINE 1.184.0 -> 1.185.0, DS :8893 restarted pid 2408 -> 18292, Share 415
files --check clean). Operator confirmed (a) fix-now; (b)/(c) resolved on recommendation after framing.

- (a) BRUISER AXIS [real fix]: `hybrid.py` rank_items_by_hybrid + compute_hybrid now score AP-axis champs
  (DDragon info.magic > info.attack) on ability DPS (compute_ability_dps) instead of auto-attack
  weighted_dps, so an AP champ routed to the bruiser scorer builds AP (Mordekaiser -> Blackfire/Riftmaker/
  Rabadon + Randuin/Warmog), AD champs byte-identical. Self-contained axis (no core import, Share-safe).
  LATENT: archetype_for returns "mage" for every AP champ so no committed comp-archetype cell reaches it as
  AP (all 6 AD-bruiser champs byte-identical after regen) - defense-in-depth for direct /rank-bruiser
  callers, not a live-output change. Gwen edge: DDragon attack 7 / magic 5 -> classifies AD (shared with
  all RC AD/AP consumers). RED-first test_bruiser_axis_awareness.py.
- (b) KALISTA IE [test relaxed]: no on-hit template exists (carry scorer is pure weighted_dps); on-hit
  Kalista is DPS-optimal + a real build; IE appears only for crit-passive kits. Test now asserts a coherent
  ADC core, not IE specifically. On-hit Kalista RATIFIED meta-correct.
- (c) BEAM boots_unique=False [test retired]: outcome unreachable with real items post-19a76d8b (T2 boots
  too low-DPS to stack); branch stays live (cli/server), default path still guarded.

Verify: DS-dir 8078 passed / 1 skipped / 1943 subtests; affected tests/ subset green (one pre-restart red
was the live :8893 lagging, green after restart); read-only verifier PASS 5/5.

NEW BACKLOG (operator-surfaced): situational/alternative builds (crit-vs-on-hit, matchup-keyed); boot
utility-awareness (MS/tenacity/haste/survival vs comp). OWED (operator-side, not code): rotate the DeepSeek
+ NVIDIA API keys at their provider dashboards.

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
on-hit-vs-IE, beam boots_unique. Each engine fix = Tier-2. (Those 3 reds CLOSED 2026-07-09 - see the newest
block at the top + LEDGER 826.)
