# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-24 - R166 share-presentation-overhaul + baseline drift fix (near-CLEAN)

Gemini-loop DIRECTOR REFILL unit (b). Two commits (`5bd0854e`, `69d06ef7`),
LEDGER 1019, Tier-0 docs-only, ENGINE-IMPACT NONE, ZERO API / ZERO LLM.

- **R166 = near-CLEAN.** Four parallel audit agents read the ENTIRE `Share/`
  authored doc set (README, docs/01-05, CHANGELOG, LICENSE, lolmath_ingest/*)
  end to end as external presentation. Docs were already pristine from R163;
  ONE real defect: README Release-history header said "five most recent" over
  a SIX-entry list -> "six". Everything else verified CLEAN + internally
  consistent (1.239.0/16.14.1, 173/171, 706, 7 scorers, 35 paths, 306/355,
  7270+2330/9203) and all upstream credits (Riot Data Dragon / CommunityDragon
  / Meraki / wiki / lolmath / Overlay App E host-only) intact. 7-bit ASCII clean.
- **Baseline red fixed (`5bd0854e`).** The full-suite gate surfaced a
  pre-existing red on main: `test_docs_daemon_slayer_drift.py` - the
  `docs/DAEMON_SLAYER.md` banner still read ENGINE_VERSION 1.238.0 after the
  engine bumped to 1.239.0 at R164. Bumped banner 1.238.0 -> 1.239.0, count
  9190 -> 9203. Not caused by R166; fixed per "fix red baseline first".
- **Suites green:** DS 9203 passed / 1 skip / 3865 subtests; RC 12742 passed
  / 23 skip (the 1 drift red now green); `-k share` 203 passed; `ds_share_sync
  --check` in sync (460 files, 1.239.0). CI `paths-ignore '**/*.md'` so the
  all-markdown push triggers no per-push run; nightly runs the full suite and
  the drift guard is now green.
- **Don't-redo:** Share/ authored presentation is current + credit-complete as
  of R163+R166 - do NOT re-pitch a Share doc overhaul; future drift is a
  mechanical anchor restamp or a real engine-bump content change.

---

# 2026-07-23k - live-frame acceptance ADJUDICATED (owed 4 sessions, now closed out)

One commit, LEDGER 1014, Tier-1, ENGINE-IMPACT NONE. The operator queued SR and
the four acceptance lines were adjudicated against a real 22m30s game (Kai'Sa,
~300 CDP samples). **2 PASS, 1 FAIL-upstream, 1 OPEN.** RM-113 + RM-114 opened.

- **PASS - OQ16 cadence, both edges seen live.** `""` -> `soon` on drake at eta
  `1:32` -> `1:29`; `soon` -> `imminent` on baron at `0:11` -> `0:09`; then
  `state=up` at spawn. Matches `alertSoonS: 90` / `alertImminentS: 10`
  (`objective_gauges.js:66-67`) within the 3s sampling.
- **PASS - no reflow.** `#am-next-buy` = 108px across 235 in-game samples; the
  only `h=0` rows land after `game_time_s` goes null, so it tears down cleanly.
- **FAIL, but NOT the widget - RM-114.** `item_advisor.resolve_build` covers
  **6 of 172 champions** (Caitlyn, Jinx, Miss Fortune, Nilah, Tristana, Vayne).
  Kai'Sa returns `[]`, so no `sr_items` row carries `next:true` and the GOLD row
  correctly renders `-`. Invariant across three `owned` states (not the
  empty-build artifact) and across `Kai'Sa`/`Kaisa`/`KaiSa` plus plain `Ashe`
  (not name normalization). **Do NOT fix this blind** - sourcing `next` from DS
  changes what "next item" means; it is an operator product call.
- **OPEN - TRINKET, one field short.** Never activated in 260 samples, but
  `stageFor` returns `mid` on the clock arm alone at `c >= 600`
  (`next_buy_model.js:68-72`), so stage was provably `mid`/`late` for the last
  12.5 min and the gate cannot explain it. Hinges entirely on whether
  `owned_items` still held `stealth ward`. The probe now records that.
- **Probe fixed twice:** now emits `owned_items` / `completed_count` / `stage` /
  `holds_upgradable_trinket` / `next_item` / `sr_items_len`, and flushes per
  sample. **The flush matters** - block-buffered redirect served a 7-min-stale
  baron ETA that got reported as current, contradicting the operator mid-game.
  They were right; the file was wrong. Re-probe live before contradicting.
- **NEXT SESSION:** one SR game closes the TRINKET line with no new analysis -
  just run the probe and read `holds_upgradable_trinket` + `stage` against the
  TRINKET row. Then RM-114 needs an operator decision, not code.

---

# 2026-07-23j - live-frame probe gold/clock paths root-caused (caveat retired)

One commit (`10e92cf5`), Tier-1, ENGINE-IMPACT NONE. The live-frame acceptance
is STILL OWED - fourth session now - and still needs the operator in an SR game.
No headless work remains on it; the pre-flight is fully discharged.

- **Probe pre-flight PASSES.** rc-shell still alive with the CDP flags (root
  pid 2232) - no relaunch needed, the `2026-07-23i` blocker stays cleared.
  Probe attaches, reads the DOM, reports `#am-next-buy` present + hidden +
  rect 0x0 at `mode_key=client`.
- **The `2026-07-23i` caveat is RETIRED - it was a real bug, now fixed.**
  `/api/state.liveclient` is the FLATTENED block from
  `dashboard/_liveclient.py:114 liveclient_summary()` (attached at
  `dashboard/_state_builder.py:687`), NOT the raw Live Client `:2999` payload.
  Gold is `liveclient.gold` (`_liveclient.py:148`); the clock is
  `liveclient.game_time_s` (`_liveclient.py:144`). The probe read
  `activePlayer.currentGold` / `current_gold` / `gameData.gameTime` - none of
  those keys exist in that shape, so BOTH fields would have read null in-game
  regardless of widget behavior. A null GOLD in the next run is now a real
  widget signal, not probe noise.
- **Do NOT redo:** everything the `2026-07-23i` do-not-redo list names, plus
  this path fix. Do NOT re-derive the CDP session - use the committed probe.
