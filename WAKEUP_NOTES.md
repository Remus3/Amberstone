# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-20a - .rofl sidecar backfill of rewind_history.db, executed live

Commits `5174058f`, `533e7e47`, `1e3a186c`, `d7901101`. CI green. LEDGER 971.

SHIPPED. 12 archived stats sidecars mapped to the 147-col `participants` schema;
3 net-new matches INSERTED into production (2961 -> 2964 matches, 30562 -> 30592
participants, 0 orphans). Backup `data/rewind_history.db.bak-20260720` (gitignored).
The DB now has its FIRST event-mode row (queue 2400 / KIWI) - was zero.

TWO FINDINGS THAT INVERTED THE DESIGN - do NOT re-derive:
- Sidecar PUUID is the RAW game uuid; DB puuid is API-key-ENCRYPTED. Zero overlap,
  a puuid join matches 0 of 18 rows. Join on sidecar player ORDER (index+1 ==
  participant_id), champion-name cross-checked. Pinned by test. Memory:
  `reference_rofl_sidecar_join_key`.
- Replay Tool Z16 does NOT read map/mode from the file - `GameDetailsInferrer.cs`
  INFERS map from player stats (no jungle creeps => Howling Abyss). Yields MAP not
  QUEUE and cannot separate ARAM 450 from Mayhem 2400. So queue_id/game_mode stay
  NULL unless a caller asserts them via `queue_overrides`. Header game VERSION is
  real (offset 14, plaintext) and oracle-verified.

118 columns mapped, each proven against the 6 overlap matches. summoner_id and
time_played were probed, DISAGREED, and are deliberately excluded.

DO NOT REDO: L1 (RM-100 asyncio dedup, `b54e315d`) and L3 (RM-108 token detector,
`a60d32e6`) were ALREADY SHIPPED - the lane list was half stale. RM-108 is now
marked SHIPPED in ROADMAP with its spec relocated to ROADMAP_HISTORY.

NEXT - operator-prioritised (Vanguard is OFF, so replay work is possible now):
replay-based coaching training. GROUND TRUTH PROBED THIS SESSION:
- Only 7 .rofl exist locally, all 16.12-16.14. The historical pro matches are NOT
  available as replays and never will be (.rofl is patch-locked to the running
  client, and Riot does not retain old files).
- BUT Match-V5 STILL SERVES those old matches: NA1_5221491343 / NA1_5217712024 /
  NA1_5216883079 all return 200, queue 420, patch 15.2, WITH full timelines
  (31 frames @ 60s, 1024 events - item purchases w/ timestamps, skill order,
  wards, kills w/ positions). That is the coaching substrate, no replay needed.
- The pro xlsx (Desktop\Challenger) has 93 strings: pro names + NA Riot IDs +
  role/team. No match ids recorded - but the ids are RECOVERABLE by resolving
  each pro's Riot ID to a puuid and intersecting their match list with the
  operator's. That is fully autonomous work.

ALSO OPEN: patch-change datasets. 5 per-patch snapshots exist
(data/daemon_slayer/16.10.1 .. 16.14.1) but there is NO cross-patch diff tooling -
that lane is genuinely unbuilt, not done.

STILL NEEDS THE OPERATOR: the /replays 5-per-account rotation question. All
observations so far ran with no games in between, so rotated=False proves nothing.
Play games, then `python tools/rofl_archiver.py --pull --no-lcu-pull`.
