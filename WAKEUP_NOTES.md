# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-20d - R138 HEXCORE offline explorer refresh

Merge `ee0e2f62` (slice `ab16e062`) + docs `001b3fc0`. LEDGER 976. gemini-loop
cycle 1 of the 2026-07-20 standing autonomous grant. Docs artifact only -
ENGINE-IMPACT NONE, no ENGINE_VERSION bump, no Share sync, no restart owed.

**The file count needed adjudication, not a raw git diff.** The directive said
"find net-new non-test .py files since d584e02e". The raw command returns 36;
10 of those are `Share/src/agents/daemon_slayer/*.py`, which are byte mirrors
emitted by `tools/ds_share_sync.py`, not distinct source units. Shipping 36
would have double-counted the DS mirror inside a visualization whose entire
point is file density. 26 unique units landed. **Do not "re-add the missing
10" in a later pass - the exclusion is deliberate.**

**The stale literal occurred three times, not two.** The `293` dust count lived
in the `// DUST:` comment, the sr-only accessibility paragraph, AND the no-JS
fallback prose near the file end. The third was found by the build agent, not
by the brief. All three now read 319 and a test pins comment-vs-prose
agreement, so the page can no longer silently lie about its own contents.

**The HUD engine pair was read live, not off docs.** `:8893/health` returned
`1.228.0 / 16.14.1`; CLAUDE.md's own header still says 1.226.0 and would have
shipped a wrong number into the artifact. Same for commits (3733) and HEAD
(`114977ee`), both re-derived from git rather than carried forward.

**Worth remembering about the test.** The build agent's first `CATS` parser
anchored to line start, matched only 6 of 15 keys, and produced a FALSE
integrity failure against pre-existing data. It fixed the parser rather than
relaxing the assertion, and added a `len(keys) >= 15` self-check so a silently
degraded parse fails loudly instead of green-washing. That is the right
instinct on a referential-integrity test and is the reason claim 8 (every dust
parentNodeId resolves in NODES) is trustworthy.

**Verified.** verifier subagent CONFIRM 13/13 (independently re-parsed DUST,
re-ran `node --check` on the extracted ~600KB script block, re-counted NODES,
confirmed the 2-file blast radius). Full RC suite **12290 passed / 0 failed /
23 skipped / 359 subtests** in 20m38s. ruff clean; file remains 0 non-ASCII
bytes and fully self-contained.

**No visual capture owed** - `docs/HEXCORE_offline.html` is a standalone offline
artifact, not a dashboard or overlay page, so the 3b overlay-capture ritual
does not apply. The `node --check` guard plus the referential-integrity tests
are the proof surface for this file.

---

# 2026-07-20c - RM-111 ARAM comp-conditioned item-interaction aggregator

Commit `d96ba4c5`. LEDGER 974. New `core/aram_item_interaction.py`, 24 tests.

**What it answers.** For the local ARAM corpus: "when did buying this item
actually pay off AGAINST THIS SHAPE of enemy comp, in my own games". That is a
different question from Daemon Slayer's, and the two must not be mixed - DS
answers what is optimal in simulation. The module is DESCRIPTIVE ONLY and is
firewalled from `agents/daemon_slayer` rank by a test that greps its own source
for an `agents` import.

**The predicted scope cut landed on granularity, not on the item.** Comp shape is
a COARSE 9-way bucket - enemy damage axis (ad_heavy / mixed / ap_heavy at >=4 of
5 leaning) x enemy frontline count (none / light / heavy) - never a 5-champion
tuple, and the champion axis is OFF by default.

**The MIN_BUCKET_N gate is load-bearing, and that is MEASURED.** Live probe over
the real corpus: 2049 ARAM matches, **776 cells surviving, 1281 dropped** at
n<15. 62 percent of cells are too thin to show. 8 of 9 shapes populate
(`ad_heavy/fl_none` is empty - an all-AD comp with zero frontline is rare).

**Pressure metric decided:** own-minus-enemy `total_gold` delta over a 120s
window after the purchase. If the window is not fully covered by frames (game
ended first) the observation records `None`, never a truncated reading. A per-frame
HP swing is NOT possible - `timeline_frames` stores no champion HP.

**Two things worth remembering.**
- `core.item_wpa.load_legendary_ids` gained a `map_id` param **defaulting to 11**,
  so every SR caller is byte-identical. ARAM passes 12.
- Champion resolution joins on the numeric `key`, NOT `participants.champion_name`.
  The stored name is the DDragon id ("MonkeyKing"); the comp-fact extractor keys on
  the display name ("Wukong"). A string join silently drops champions.

**OWED:** the consumer surface is NOT wired. The coach `watch`/`next` channel and
the overlay item strip are untouched - this slice is the aggregator only.

**Docs:** ROADMAP.md 81889 -> 74976 bytes. RM-100 / RM-106 / RM-106a / RM-106b full
narratives relocated verbatim to `docs/ROADMAP_HISTORY.md`; the condensed pointers
left behind KEEP every still-open thread (the `0xC000013A` unknown, the
snapshot_panels asyncio-marker leak, the replay URL-rotation hypothesis, RM-106b's
unmeasured archive depth).

---

# 2026-07-20b - pro-match corpus CLOSED (no API needed) + ds_patch_diff shipped

Commits `533d70fb`, `999cb1b8`. CI green. LEDGER 972-973. RM-109 + RM-110.

**The planned session was wrong and the correction is the headline.** The plan was
a Match-V5 fan-out: resolve ~30 pro Riot IDs to puuids, page each pro's id list,
intersect with the operator's. Unnecessary. `participants.riot_id_game_name` +
`riot_id_tagline` are populated on 29418 of 30592 rows, so the recovery is a LOCAL
read-only SQL join at ZERO API calls. The rejected fan-out would have cost ~700+
calls / ~14 min at the real `DualBucket` ceiling (20/1s + 100/120s = 0.83 req/s)
for no new information.

**Final answer: 26 matches**, pro-attributed, 29 same-team appearances, 49 matches
containing any pro. All 26 already `has_stats=1 AND has_timeline=1` - Phase 2
(ingest) was already done. `core/pro_match_index.py` + 4 oracle tests reproduce it.

**Do NOT redo any of these - all operator-confirmed closed:**
- Roster expansion: 66 candidate teammates (>=5 games, minus the 30 known and the
  Chunjae duo alts) checked against aggregator G. **ZERO are pro.** Do not rebuild the
  list or re-scrape aggregator G.
- The post-2025-09 coverage hole is REAL play history, not missing data. Never run
  a catchup for it.
- Blank-name risk is dead: only **8** blank `riot_id_game_name` rows on the
  operator's side (the 1174 figure was corpus-wide, mostly enemy rows).
- Identity notes kept for premade work: xChunjae / vChunjae / zChunjae are ONE duo
  partner; candidate rows 12+15 are alts of row 6, row 22 = row 19.

**`tools/ds_patch_diff.py` shipped** (16 tests, Tier-1). Measured 16.13.1 ->
16.14.1: 8 changed items (Phantom Dancer AS 0.6 -> 0.65, Kraken Slayer 0.35 ->
0.4, Hextech Rocketbelt AP 70 -> 60, Protoplasm Harness 2500 -> 2600g), 0 champion
changes, 90 SR build-order changes. **Ability diffs read 0 across 16.10.1 ..
16.14.1 and that is CORRECT, not a bug** - the payload is byte-identical, Meraki
`latest` is pinned at content patch 25.15. Documented in the module docstring so
"0" is never misread as "no balance changes". `ability_staleness.json` (RM-81, 75
stale champions / 123 findings) is what answers that question.

**ARAM item-interaction coach scoped to BACKLOG** (RM-111) with its data gate
MEASURED GREEN: 2073 queue-450 matches, all 2073 carrying both `ITEM_PURCHASED`
and `timeline_frames`. Own session, do not bolt onto other work.
