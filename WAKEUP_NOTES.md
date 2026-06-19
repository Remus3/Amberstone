# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-18 (PM6) - 16.12.1 Arena ability-haste drift fix (3 mirror ids; ENGINE 1.143.0)

Operator "continue open items from last run". PM3's `TIER2_REPORT.md` cross-eval
bounded queue is fully DRAINED headless (Aphelios C=1.128.0, B1=1.141.0/PM4,
F2=1.142.0/PM5; A ARAM-override stays default-OFF). Picked a fresh self-directed
DS data-correctness unit. Commit `8c63b79b`, CI run 27799329481.

- **PREFLIGHT:** PM5 (F2, 1.142.0) verified landed clean - HEAD==origin/main,
  DS :8893 live 1.142.0 (it is HTTP not HTTPS - earlier "DS probe failed" was a
  curl scheme mistake), Share in sync 367. Same external anomalies persist
  (RC-GeminiAudit result=3 gemini loop DOWN / RC-WeeklyHygiene result=1; not
  locally fixable).
- **AH drift fix (item 498, ENGINE 1.142.0 -> 1.143.0; DS :8893 restarted pid-relaunch; Share 367).**
  `_item_ability_haste.py` was pinned at 16.10.1 (no committed regen tool, exactly
  as [[reference_item_ah_registry_drift]] warned). NEW `ops/audit/item_ah_drift_check.py`
  (regen-from-DDragon + diff) found 3 stale `22`-prefixed Arena mirror ids that
  Riot normalized DOWN in 16.12.1 - Imperial Mandate `224005` 35->15, Iceborn
  `226662` 10->15, Serylda's `226694` 10->15 (ground-truthed vs 16.11.1-vs-16.12.1
  DDragon stats blocks). SR/ARAM canonicals already 15. Feeds `compute_ability_dps`
  Arena cooldowns -> Tier-2. **OVER-FIX GUARD:** a naive alias==canonical sweep
  flagged 25, but 22/25 are legit Arena-boosted variants (verified vs DDragon) -
  only the 3 true drifts touched ([[reference_items_index_alias_ids]]). TDD RED->GREEN;
  the stale `224005==35` test (correct at 16.11.1) updated to 15 + a new normalization
  test. 88 ENGINE pins / 80 files (quoted-only). DS-dir 7361 / 1 skip / 1942 subtests
  + RC tests/ all green (7 anchor/live-engine fails were expected pre-sync, GREEN
  after ds_share_sync + DS restart). Correct-by-construction -> NO LIVE_GATED entry
  (already live at 1.143.0, not a default-OFF flip).
- `ops/loop/{config.json,director_prompt.md}` STILL uncommitted (operator pre-run
  loop tuning, untouched PM2-PM6; gemini loop DOWN).

---

# 2026-06-18 (PM5) - F2 cost-aware-top gate (DS Tier-2 nom F2, DEFAULT-OFF; ENGINE 1.142.0)

Operator "continue open items from last run". Shipped the second bounded DS Tier-2
ship-or-close nomination from PM3's `TIER2_REPORT.md`. Commit `60c3d6f7`, CI GREEN.

- **PREFLIGHT:** DS :8893 was DOWN (no proc) -> relaunched detached, healthy ENGINE 1.141.0 ->
  (post-bump) 1.142.0. RC-DaemonSlayer result=1 / RC-GeminiAudit result=3 / RC-WeeklyHygiene
  result=1 = same external/stale anomalies as PM3/PM4 (gemini loop DOWN, not locally fixable).
- **F2 cost-aware-top (item 497, ENGINE 1.141.0 -> 1.142.0; DS :8893 restarted; Share 367).**
  `rank.py` `sort_by="delta"` scales with cost -> 6000g ARAM/Arena Void Immolation `223069` ranks #1
  on hybrid/bruiser + ehp/tank across ~66 champs (artifact, NO WIN gate). NEW DEFAULT-OFF
  `cost_ceiling` param on the shared `_filter_candidates` (drop `gold.total` STRICTLY > ceiling)
  threaded through `rank_items`/`rank_items_by_ehp`/`rank_items_by_hybrid`; other 4 callers unchanged
  -> byte-identical OFF. +12 TDD (difference-of-differences). Reproduced live (Garen bruiser ARAM
  rank-1 = 223069). PM4 id/mode subtlety RESOLVED: 223069 is a genuine base id (maps 12+30 ARAM+Arena),
  NOT the `22`-alias quirk; report "ARAM-exclusive" imprecise. DS-dir 7360 / RC tests/ 8439 green;
  87 ENGINE pins / 79 files; Share --check in sync.
- **B2 found largely ALREADY SHIPPED** (DSP11 `prefer_kit_axis_by_win` + DSP2 `exempt_offclass_by_win`)
  - only per-champion live re-rank validation remains. A ARAM-override stays default-OFF. B1+F2
  bounded Tier-2 nominations now DONE; lane tail is live-validation-gated -> `LIVE_GAME_GATED_SYNC.md`.
- **Doc-budget:** pre-existing `test_roadmap_md_under_budget` RED (82556 > 80KB; CI runs no pytest so
  PM4 missed it) cleared by relocating the shipped item-320 `prefer_cdragon_ratios` block verbatim to
  `ROADMAP_HISTORY.md` (now 81269 < 81920).
- `ops/loop/{config.json,director_prompt.md}` STILL uncommitted (operator pre-run loop tuning,
  untouched PM2-PM5; gemini loop DOWN).
