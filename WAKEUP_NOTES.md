# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-19 (run 2026-06-19-01) - headless-upgrade: personal-build-wr + laning flip-gate diagnosis (4b)

Operator launched `/headless-upgrade`. HEAD `bfc44e0a` -> `a4db6aab` (2 commits), CI green
(both runs success), NO ENGINE bump, NO frozen edits, NO worktrees, NO DS restart. Prior
manifest 2026-06-18-03 fully committed, so fresh run-id 2026-06-19-01.

Pre-flight established the headless-safe HIGH-value queue is genuinely thin: PRIMARY Tier-1/2
coach flips are do-not-flip-blind (data-gated); the DS cross-eval clusters A(excluded)/B1/B2/C
are all shipped-or-gated; DS registries saturated; cost levers CLEAN. So picked the two clean,
PRIMARY-aligned, headless-VALIDATABLE slices that remained.

- **S1 `43acb128` (4b / research-lift):** `core/personal_build_wr.py` + `GET /api/personal-build`.
  Personal per-champion build win-rate from rewind_history.db - confidence-weighted item lift vs
  own baseline (smoothed_rates blend toward the personal prior), legendary+boots gold floor so
  end-of-game component noise drops out. Closes COMPETITOR_LIFT_2026-06-16 "personal-WR build
  override (local-data half)". +18 tests, live-verified (Vayne SR 54g -> Terminus/Guinsoo/PD).
  Deterministic, zero LLM. UI consumer DEFERRED (needs OWED Game-PC capture) -> BACKLOG.
- **S2 `a4db6aab` (4b PRIMARY finding):** `tools/hz_shadow_report.py` now emits the precompute
  x native confusion matrix + precompute verdict vocabulary. Run over the accrued 1490-row real-
  game shadow log it reclassifies the laning bottleneck: NOT game volume (693 comparable ticks),
  but AGREEMENT QUALITY = 39% (160/406). Precompute has only back_off/trade/even, NO hold band;
  Haiku says hold 28% of ticks. Caveat (verified): the precompute `even` verdict (A="Even trade
  on your cd window", B="Hold position") classifies coarse as "trade", so 39% understates true
  agreement. Corrected HZ_HAIKU_CALL_INVENTORY "bottleneck=games" claim. +1 test (27 total).
- **NEXT (operator-gated, in BACKLOG):** (a) personal-build UI consumer (capture-owed); (b) the
  laning hold-band recalibration + LFS table regen (the 39% fix) - a product-calibration call,
  explicitly NOT a blind overnight edit; the report's new confusion matrix is its per-iter gate.
- ops/loop/{config.json,director_prompt.md} STILL uncommitted (operator pre-run loop tuning, left).

---

# 2026-06-18 (run 2026-06-18-03) - headless-upgrade: champ-select pick-advisor shadow (4b) + 2 cost/bug slices

Operator launched `/headless-upgrade`. Prior manifest 2026-06-18-02 fully resolved (superseded by
17 commits), so fresh run. HEAD `7e803410` -> `98816b05` (4 commits), CI green, NO ENGINE bump,
NO frozen edits, NO worktrees. Item 500 in LEDGER.

- **S1 `a31ef769` (PRIMARY 4b):** champ-select PICK-ADVISOR is the last champ-select Haiku call
  (BRIEF flipped 2026-06-06; pick-advisor had NO det substrate + NO shadow). Built
  `core/champ_select_advisor_deterministic.advise_pick` (reuses aram_comp_verdict + archetype tags)
  + `core/champ_select_shadow` (mirrors hz_choice_shadow) wired fail-soft at `dashboard/routes_coach.py`.
  NO flip (do-not-flip-blind) - FLIP waits on shadow data from REAL games (data-blocked headless). +19 tests.
- **S2 `8c3a6ad6` (cost):** the cost-sweep's augment-select cache_control NOW-FIX was REFUTED (item 286:
  static ~62/80 tok, sub the 2048 Haiku floor = inert). Shipped a guard EXTENSION (arena site pinned) instead.
- **S3 `fb0dd83b` (open bug):** runewriter game-1-only silence ([[reference_runewriter_dies_after_game1]]) -
  NOT reproducible headless (get_champ_select stale after game1). Added re-arm regression test (+4) +
  INFO enter/exit diagnostics so the NEXT live session pinpoints the failing branch. Logging-only, no flip.
- **GATED -> BACKLOG:** HZ-B build-order tables 21 ENGINE bumps stale (operator-gated regen, ENGINE-bump tax);
  same-state coach Haiku-skip debounce (fidelity-gated; cost_health_watchdog exit 1 = by-design breach, not a crash).
- **NEXT:** champ-select pick-advisor flip after shadow data accrues; both BACKLOG items operator-gated.

---

# 2026-06-18 (PM7) - Arena boots 22xxxx map30 mirror (P6-G4 deferred tail; ENGINE 1.144.0)

Operator "continue open items from last run". TIER2_REPORT + RF round-2 queues DRAINED
headless, so picked the next self-directed DS data-correctness unit: the G4-deferred Arena
boots mirror (`docs/LIVE_GAME_GATED_SYNC.md` section D). Commit `c258c4ab`, item 499.

- **PREFLIGHT:** HEAD==origin/main `b644709f` (PM6 landed clean), DS :8893 live 1.143.0
  (HTTP not HTTPS), Share in sync 367. Same external anomalies (RC-GeminiAudit result=3
  gemini loop DOWN / RC-WeeklyHygiene result=1; not locally fixable).
- **Arena boots fix (item 499, ENGINE 1.143.0 -> 1.144.0; DS :8893 restarted -> 1.144.0; Share 367).**
  The Arena build tables carried BARE 3xxx tier-2 boots (`3111` x423 / `3006` x87 in the flat
  table) - all `maps.30=False` (illegal on Arena). G4 (item 423) upgraded SR to tier-3 and left
  "ARAM/Arena keep tier-2", but ARAM's 3xxx are map12-legal while Arena's are NOT. FIX:
  `core/build_order.py` NEW `_BOOTS_ARENA_MIRROR` (6 ids -> `22`-prefix, each verified map30=True)
  + `_ARENA_MODES={ARENA,CHERRY}`; `_select_boots` remaps on Arena (mirrors the SR-upgrade branch).
  Ground-truthed vs `items.json` maps.30. 3 Arena tables regenerated boots-only (flat 510 surgical /
  HZ-B1 684 / HZ-B2 342; SR/ARAM byte-identical) via NEW `ops/audit/p7_arena_boots_regen.py`. The
  flat-table full regen would have BUNDLED 176 cells of unrelated 1.123->1.144 ranking drift accrued
  since G4 -> did a SURGICAL boots-only remap to keep the commit scoped (drift = separate patch-refresh
  concern). ENGINE bump = pure table-regen provenance EXACTLY as G4 (zero engine-code; ranker never
  imports core/build_order); 88 quoted pins / 80 files. 36/36 boots tests; DS-dir 7361 / RC tests/
  8440 (6 Share-anchor RED mid-suite = expected pre-sync race, re-ran fresh = 17 GREEN). Correct-by-
  construction -> NOT live-gated (only an Arena augment-phase visual OWED).
- **DIVERGENCE (not actioned):** `tools/champion_loadout_validate_meta.py` `ARENA_HAS_BOOTS` strips
  Arena boots ("Cherry has no shop") - a SEPARATE curated-loadout subsystem; the DS build_orders
  Arena-carries-boots stance is G4/LIVE_GATED-sanctioned, so the mirror is correct for THIS artifact.
- **LIVE (operator played an ARAM Yasuo mid-run):** RF1 survivability seam VALIDATED SANER for a
  tabled bruiser (the LGS2-open gap) - hybrid ON floats Wit's End + Jak'Sho, drops Runaan's +
  Stormrazor. RF1 marked FLIP-READY in LIVE_GATED section B; actual default-ON flip stays operator-
  gated (not flipped mid-game). The served live #1 (Void Immolation, F2 6000g artifact) is the
  known default-OFF/gated F2 case, not actionable mid-game.
- `ops/loop/{config.json,director_prompt.md}` STILL uncommitted (operator pre-run loop tuning,
  untouched PM2-PM7; gemini loop DOWN).
