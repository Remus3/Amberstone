# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + /live-gated-drain (2026-07-08, LEDGER 820) archived 2026-07-09. Only the last 3 sessions kept here.

---

# 2026-07-10 (regen STALE HZ-B build-order tables to 1.186.0 + content-freshness guard; NO ENGINE bump)

Executes deferred `task_27071e90` (flagged in LEDGER 827). Full detail: LEDGER 828. Commit `5c149fe0`.
Data-catchup: NO ENGINE bump (engine already 1.186.0; a table regen is the post-bump FOLLOW-UP the
stamp-sync guard's own docstring prescribes, not a version change - the directive said BUMP, auto-picked
no-bump as the safest + correct option per the no-questions grant, logged for director override).

- Stale scope (static regen diff, all 3 modes): precompute `build_orders_*` = {Belveth}; variants
  `build_order_variants_*` = {Annie, Belveth, Katarina, Lulu, Nilah}. Item 827's "e.g. Annie mage" was the
  VARIANTS table (Annie precompute is byte-identical). ROOT CAUSE: 827 re-stamped the tables byte-exact
  (stamp only) but item-826 bruiser damage-axis awareness genuinely changed some orders full-roster; the
  OQ19 stamp-sync guard checks `engine_version==stamp`, never CONTENT.
- Prevention (2 parallel worktree slices, disjoint files, read-only verifier CONFIRM 7 claims): NEW
  `--champions all` full-roster flag on `core/build_order_precompute.py` + `core/build_order_variants.py`
  (canonical 173 from `data/daemon_slayer/<patch>/champions.json`; heeds the R78 `--static` seed footgun) +
  fixed the misleading "`--mode all` expands roster" docstrings; NEW `tests/test_build_order_content_freshness.py`
  (fast per-commit roster/stamp/structure guard + env-gated `RC_BUILD_ORDER_FULL_REGEN=1` slow regen-compare)
  + fixed the dangerous SEED-clobber `--mode all` regen command in the stamp-sync docstring.
- Fresh output validated BEFORE commit (wrong precompute > stale): 667112=Flesheater is a real item; the
  Belveth AD->AP shift is the shipped item-826 bruiser-axis reclassification -> FUTURE scorer-calibration
  flag, NOT a table bug blocking the sync. All 6 tables stay 173 champs / 1.186.0.
- SHARE: the HZ-B `build_orders/<patch>/` tables are NOT in the `Share/src` mirror (only the older
  display-keyed `<patch>/` family is), so no Share content changed; `ds_share_sync --check` green (417 files).
  No DS `:8893` restart (no engine code changed; :8893 already serves 1.186.0).
- GATES (verifier-CONFIRMED, fresh): freshness proof 19 passed; build-order blast radius 460 passed; RC full
  11238 passed / 2 failed (both the PRE-EXISTING coach-poll asyncio-pollution flake, LEDGER 823/824/827,
  proven passing in isolation) / 22 skipped; DS 8085 passed / 1 skipped / 1943 subtests. done_sentinel
  --tests 11238 --regressions 0. Don't-redo: HZ-B tables FRESH + content-freshness-guarded (do NOT re-flag
  task_27071e90); Belveth AD->AP is a shipped-826 reclassification pending scorer-calibration (FUTURE).

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
