# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-20e - R139 Share/ external-presentation pass

**Head `a700b414`. ENGINE-IMPACT NONE** - docs and presentation only, no DS path, no ENGINE_VERSION bump
(stays 1.228.0 / patch 16.14.1), no `:8893` restart owed. `tools/ds_share_sync.py --check` green throughout.

Gemini-loop cycle, directive R139: read the entire `Share/` package end-to-end and raise it to external-presentation
quality, credit upstream data sources explicitly, keep the sync guard green. Two worktree slices, Claude sole merger,
verifier gate CONFIRM/CONFIRM before merge (6 of 6 factual spot-checks independently re-derived).

**The directive's premise was already on disk.** It claimed the Riot credits were missing from `Share/README.md`;
they have been there as a four-row "Sources of truth (credited upfront)" table at `Share/README.md:19-32`. Following
the brief literally would have shipped a duplicate credit block. The real defect was one section below it.

**The guard was green over a five-versions-stale public doc, by design.** The README "Changelog (recent)" list topped
out at `1.222.0 -> 1.223.0` against a live 1.228.0 engine. `_doc_anchor_rules` in `tools/ds_share_sync.py` deliberately
EXCLUDES changelog history from the anchor auto-rewrite - so the `**Engine version:**` header stays fresh forever while
the release list beneath it rots silently. Worth remembering the shape: an anchor guard that covers the header but not
the body makes staleness invisible rather than loud. Five hand-written bullets now cover 1.224.0 through 1.228.0, each
grounded in the matching `Share/CHANGELOG.md` entry; the CHANGELOG preamble gained the upstream credit it never had.

**Docs half was the heavy half:** 100-plus stale `file:line` citations across `Share/docs/01..05` plus
`Share/lolmath_ingest/*` (104 table citations and 27 route refs in `02_FUNCTION_REFERENCE.md` alone), and every drifted
count re-derived against live ground truth - 172/705 -> 173/706 champs/items, 13 -> 20 snapshot JSONs, 328 -> 339 test
files, RUNE_PROCS 19 -> 20, NON_DAMAGE_BLOCKS 7 -> 9, `_effects_data.py` 5335 -> 5843 lines, explicit AA cast times
61 -> 49. One correction was substantive rather than numeric: `04_GAPS_AND_ROADMAP.md` justified the replay-parsing
ceiling with a reason this repo retired on 2026-06-03 (that a parsed `.rofl` is a strict subset of Match-V5 - it is not;
367 engine-named stat fields x 10 players, no patch gate). A wrong reason for a right conclusion forecloses the option
for the next reader, so it now states the honest bound: per-patch Layer-2 re-RE cost.

**Prunes: zero, and that is correct.** Every candidate resolved to load-bearing against the sync tool itself
(`_DOC_FILES` :71-78, `_INGEST_DOC_FILES` :90-95, `_INGEST_BUNDLE_REL` :96, MANIFEST machine-stamped). Only disposable
artifact was an untracked gitignored `__pycache__`.

Suites fresh this run: **DS 8866 passed / 1 skipped / 2518 subtests; RC 12290 passed / 23 skipped / 359 subtests.**
Share `.md` non-ASCII bytes: 0. Worktrees + slice branches cleaned (local and remote).

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
