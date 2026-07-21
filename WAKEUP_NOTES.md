# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-20p - LIVE-GATED DRAIN, operator present, 4 games - 6 rows closed, 9 new bugs

**Tier-1 RC-side. The one Tier-2 slice is parked on branch `ds/g2-12-ranged-reflect`
(`6fe6df12`), NOT on main.** LEDGER 987. Full detail: the dated drain block now at the
TOP of `docs/LIVE_GAME_GATED_SYNC.md` (that block is the real hand-off; this is the
summary).

Games: practice SR q3140 -> ARAM Mayhem q2400 -> Arena q1750 -> real SR draft q400.

## Closed (6): G1-00, G6-02, G2-18, G2-29, G2-34, G2-35

- **G1-00** - CHECK 1 across ALL FOUR champ-select shapes; CHECK 2 `champ_select`
  **BYTE-IDENTICAL** flag-ON vs OFF in the same lobby. Divergence was TWO keys
  (`config` AND `lcu_port`), not the one predicted. Adjudicated AGAINST the doc's
  premise - live `config.auto_accept` was `false`, so carry it, never synthesize.
- **G6-02** - first GATE 6 row ever closed. Ctrl+Shift+A with League foreground:
  PASSIVE -> ACTIVE + the 20s auto-revert, with listener receipts.
- **G2-18/29/34/35** - operator rulings + measurements; see the drain block.

## The 5 fixes sitting on main, UNCOMMITTED at time of writing -> now committed

ARAM balance resolver (dead in EVERY ARAM, fixed + live-verified in-game), auto-PGR
arm (= G4-26, root-caused to a 5s TTL vs a documented 8-11s capture lag), minimap
clear-on-exit, KP live value, champ-select mastery/meta placeholders.

## DO NOT REDO / carry-forward

- **G2-12 is decided, not open**: operator ruled the Thornmail reflect credit TOO HIGH
  (+8.963 pct measured, control byte-identical). The ranged-exposure fix is BUILT and
  DS-green on the branch. What is owed is the Tier-2 ritual: ENGINE bump, Share resync
  in the SAME commit, dual suite, `:8893` restart, LEDGER + doc update. **Open question
  the operator raised live: ARAM is a permanent teamfight, so the factor may need to be
  MODE-AWARE rather than a global 0.35.**
- **G2-18's residual is a code slice, not a game**: wire the live HP feed and delete the
  0.35 midpoint. RC already emits hp/hp_max (item 639).
- **G5-01 is THREE questions now** - augments WORK, anvils FAIL, rows are CORRUPT. Do not
  re-file it as one row. The anvil failure is most likely the 23-30s vision cadence, not
  a wiring gap.
- **Do NOT re-run the "is the ingest rail broken" investigation** - it is HEALTHY
  (2964 -> 2965, Arena game ingested). The 12-day gap was ARAM Mayhem + customs, operator
  confirmed. What remains is a rendering defect (`Unknown / 0-0-0`).
- `coaches/arena_coach.py` work from a CANCELLED agent is preserved as
  `CANCELLED_arena_coach.patch` in the session scratchpad - the tree was reverted, not
  shipped.

## Process lessons worth keeping

1. **Editing any `web/js/*` file hot-reloads every connected client mid-game** (ADR-008).
   This contaminated one of my own "clean reproduction" claims and probably caused an
   overlay-stranded-on-dashboard incident I first reported as spontaneous. Do not run
   web-touching agents while the operator is in a game they care about.
2. **pytest writes into `logs/hotkey_listener.log`** - a test monkeypatches the signal
   path to `Z:/nonexistent/...`. It produced two false readings during triage tonight.
3. **`zoom` re-captures the screen live** rather than cropping the previous screenshot -
   do not use it to inspect a frame that has already moved on.
4. I was WRONG four times and each correction changed the answer: the auto-PGR feed
   hypothesis (there IS a writer), "round counter stuck" (it RESETS), "re-trigger dead"
   (it fires), and an "independent reproduction" that was actually an overlay-shell
   client the router pins by design. Re-probe before asserting.

## NEXT SESSION (operator-chosen) - UI/UX

**Queue doc: `docs/qa/UI_UX_QUEUE_2026-07-21.md`** - written at the end of this session,
carries the operator's own framing plus ~20 concrete defects measured live tonight. Read
it first; this is the summary.

Build **dev display data for the out-of-game pages** + a **pseudo-screen for the in-game
overlay** so UI work stops depending on catching a live game in the right state.

Operator's three asks, in his framing:
1. **Colour is off for RC as a whole**, out-of-game AND in-game - some pairs mix well,
   others read optically wrong, and **some panels do not match the rest thematically**.
   He wants a **theme swap explored**, not per-cell patching.
2. **2-3 LAYOUT ALTERNATIVES per page** to choose between, not one proposal to approve.
3. **Daily-use data points are redundant or lacking** - a content audit, not styling.
4. His own note: the earlier per-page UI reviews were **never finished** (larger issues
   kept interrupting). Treat the E11 sweep as INCOMPLETE.

**DO NOT close (1) by citing the old palette pass.** Memory
`feedback_operator_ui_qa_method` says E11 out-of-game is done for palette - that was a
COMPLIANCE hunt (bare hex vs tokens) and comes back near-empty. The operator is asking
about OPTICAL RESULT and CROSS-PANEL COHERENCE, which that pass never asked. Explicitly
re-opened by him.

**Highest-leverage content fix, and it needs no API:** the `Unknown / 0-0-0` rows are
backfillable from the local `.rofl` archive. `RC-RoflArchive` runs every 15 min into
`C:\Users\Administrator\Documents\RC_ROFL_Archive` and was VERIFIED working tonight - it
captured the SR, the Arena AND the q2400 ARAM Mayhem game that Match-V5 will never
return. Layer-1 extraction gives 365-367 fields x 10 players, no client, no patch gate.
Traps: join on participant ORDER never puuid, and sidecars carry no queue_id.

Method: the operator's own per-page loop (MAP -> ADVOCATE ROUNDS with counter-arguments,
he wants pushback -> ACT behind a verifier gate + the 5-phase fixture audit). One
cross-page design-system pass FIRST, or every page re-litigates the same colours.

---

# 2026-07-20n - RM-03 E12 lever L3 BUILT (dark) - full in-process snapshot port

**Tier-1 -> full suite. No ENGINE bump, no Share touch.** Commit `875aa355` (ff-merge
to main, pushed). Full `tests/` suite 12324 passed / 53 skipped / 0 failed
(verifier-CONFIRMED, independent re-run). LEDGER pending append.

## Scope grew on contact: L3 needed a lobby extraction R148 never did

The WAKEUP framed L3 as "point `_state_builder:310` at an in-process reader using
`shape_champ_select`." Ground-truth probing showed the relay hop `lcu_summary()` carries
the WHOLE agent snapshot (phase + lobby + ready_check + champ_select + mastery), not just
champ_select - and `build_state` reads `lobby` (party_mains, preflip) + dumps the whole
thing to `state.lcu`. `shape_champ_select` only covers champ_select; the lobby/mastery
shaping lived ONLY in the standalone agent, un-extracted. Operator chose **full in-process
port** (framed Q). So L3 first needed a `shape_champ_select`-style extraction of the REST.

## What shipped (all DARK - flag DEFAULT-OFF, live path byte-identical today)

- `lcu/snapshot_shape.py` - `shape_snapshot(request, config, *, enrich=True)`, transport-injected,
  stdlib-only. Moved the lobby + mastery helpers verbatim from `tools/lcu_agent.py`
  (`_slim_lobby_member`, `_lookup_summoner_by_id`, `_derive_search_state`,
  `_resolve_local_summoner_id`, `_maybe_refresh_mastery` + their caches, `_LOBBY_QUEUE_NAMES`).
  Reuses `shape_champ_select`. Does NOT emit `config`/`lcu_port` (caller/transport-owned).
- `tools/lcu_agent.capture_state()` now delegates (`state.update(shape_snapshot(lcu_request, CONFIG))`);
  helper names re-exported so existing patches still bind. -405 lines. Agent byte-identical
  (parity tests + `test_champ_select_shape_rc2::TestAgentParity` green unchanged).
- `dashboard/_lcu_inprocess.py` - dashboard-OWNED `LcuClient` (no frozen main.py accessor edit),
  `_request`->`(payload,None)` adapter, `lcu_summary_inprocess() -> dict|None` (None when
  unconnected / on any exception -> relay fallback).
- `dashboard/_state_builder._read_lcu_snapshot()` at the call site: in-process ONLY when
  `RC_LCU_INPROCESS==1` AND in-process non-None, else relay `lcu_summary()`. Flag OFF default.

## NEXT / owed (G1-00, needs a live champ-select - no game)

Folded into `docs/LIVE_GAME_GATED_SYNC.md` G1-00 CHECK 2: with champ-select up, set
`RC_LCU_INPROCESS=1`, restart RC, byte-compare `/api/state` `lcu.champ_select` flag-ON vs
flag-OFF - must be identical. **Adjudicate live:** in-process path omits `state.lcu.config`
so the `main.js:5663` auto-accept pill loses its source - decide whether the reader
synthesizes `config` (main `_lcu` auto-accept is always ON) or the pill re-sources. Flag
stays OFF until this passes. Do NOT re-extract - the extraction is DONE + verifier-proven.

---

# 2026-07-20m - R148 E12 residual: lever L3 unblocked (not built) + an R146 regression

**Tier-1. No ENGINE bump, no Share touch.** Commits `6eb3837a` + merge `b3698bda`
(code), `06c52f0f` (docs + regression fix), `f460c9f3` (live-gated row). CI green.
Gemini-loop cycle 3 of the 2026-07-20 standing autonomous grant. LEDGER 985.

## The directive's premise was half stale, and the surviving half was mis-specced

"Build RM-03 E12 responsiveness levers residual." E12 reads OPEN in `ROADMAP.md:18`
but DONE in `docs/RC2_PLAN.md:95`. `docs/RC2_QA_CONSOLIDATED.md:167` breaks the tie:
the residual is QA items 59 + 62. **Item 59 was already shipped** (`_cached_lobby_mode`)
and had already been caught stale once - `ORCHESTRATION_FINDINGS_ARCHIVE.md` OQ10.
So the real residual was item 62 / lever L3 alone. ROADMAP now says exactly that
instead of restating "residual" for a third cycle.

**Lever L3 is not buildable as written.** The research note
(`docs/research/RC2_RESEARCH_io_timing_map.md:174-178`) says to point `build_state` at
the in-process `LcuClient` instead of the `/latest-lcu` relay hop. But the relayed
payload is AGENT-SHAPED by `capture_state()` - ~155 lines of enrichment - while
`LcuClient.get_champ_select()` is a bare session. A direct swap silently guts
`_cs_retention`, `_party_mains`, the preflip, `_active_champion` and `/api/state`'s
`lcu` key. The relay-self-heal alternative hits the same blocker AND keeps the
round-trip, so it cannot deliver the ~1.0s win either.

## What shipped: the prerequisite both variants need, and nothing more

`lcu/champ_select_shape.py` - `shape_champ_select(request, phase)`, the shaping lifted
out as a pure connection-agnostic function. `tools/lcu_agent.py` drops 283 lines to a
4-line call. **The L3 rewire itself is deliberately NOT built** - now unblocked and
re-sized against a named seam.

Byte-identity was PROVEN, not asserted: the verifier diffed pre/post `capture_state()`
across 5 fixtures - zero mismatches, identical key order. The real risk was the live
ONLOGON agent: the new import needs a repo-root `sys.path` insert, and RC-LCUAgent runs
with an **EMPTY WorkingDirectory** (defaults to `System32`). The shim anchors to
`__file__`, so cwd is irrelevant - verified under the literal task `pythonw.exe`, then
confirmed live by restarting the agent post-merge (came up clean, PID 24428).

## Caught in passing: R146 broke two tests and the Tier-0 exemption hid it

`test_hexcore_offline_dust.py` HUD count guards failed on `main` BEFORE this slice.
R146 added `title=` tooltips to those rows; the guards matched a bare `<div>` tag, so
they stopped matching entirely - the counts (141/322) were right all along. R146 was
correctly Tier-0 and correctly skipped the suite, and it still shipped a red. Fixed at
root (attribute-tolerant regex, sibling-swept, mutation-checked so it still fails on a
perturbed count).

## Carry-forward

- **G1-00 (new, GATE 1):** the new shaping path has never executed live - the agent
  restart happened with the client Offline, so only the early-return ran. Closes on one
  champ-select, no game needed.
- `tests/test_zoi_influence_dmz.py::test_rosters_fail_soft_on_garbage_roster` ERRORs
  under the full-suite random seed, passes 3/3 standalone. Same flake LEDGER 983 saw.
  Recorded, not silently re-rolled.
- The `my_pick` non-dict `AttributeError` is pinned by a test as pre-existing behavior.
  Hardening it belongs in its own slice, not a byte-identity one.

**VERIFIED FRESH:** RC 12338 passed / 23 skipped / 386 subtests; DS 9054 passed / 1
skipped / 3582 subtests; ruff clean; ASCII trio 13 passed.

---

# 2026-07-20j - R144 item-registry mode-mirror sweep: 1 real gap, 4 CLEAN

**ENGINE 1.230.0 -> 1.231.0 (patch 16.14.1). Tier-2** - Share mirror resynced in the
SAME commit `52258f17`, DS `:8893` bounced onto 1.231.0, dual suite green.
Gemini-loop cycle 2 of the 2026-07-20 standing autonomous grant. LEDGER 982.

## What the directive asked vs what was true

Extend R143's `_hsp_amp.py` mirror finding to the remaining 14 id-keyed registries
under `agents/daemon_slayer/_item_*.py`. **The premise was partly REFUTED and that is
the headline:** the predicted silent-zero defect exists in **exactly ONE** registry,
not across the set. Four of five slices came back CLEAN. They are recorded as
negatives, not dressed up as a sweep.

## The one real defect (slice A, `_item_ally_grant.py`)

Four SR mirrors priced 0.00 vs bare-id controls: `323107` Redemption, `323190`
Locket, `323222` Mikael's, `326620` Helia. Live-probed -
`name_to_id("Echoes of Helia", mode="sr")` returns `326620`.

**The failure mode was subtler than R143's and this is the durable lesson: it was NOT
a missing key.** R143 had already added these mirror rows to `enchanter_items.json`
with the per-proc fields left at 0.0 ("not measured this pass"), so the lookup
SUCCEEDED and returned a silent zero. A key-presence check cannot see this class.

Fixed with an id-to-id remap (`_ALLY_GRANT_MIRROR_SOURCE`), one functional line.
**No new magnitude constant was authored** - the 873.36 / 1018.32 / 205.84 / 61.12
values are computed OUTPUTS of the pre-existing bare-id formula, so they cannot drift
from it. Verifier reproduced each and confirmed mirror == bare at levels 1/6/11/13/18.

The four Arena `22xxxx` mirrors are **HELD at 0.0 on purpose**: grant stated in prose,
magnitude stated nowhere, and Riot retuned every absolute (Locket 400 vs 200 HP). A
base-nominal carry would invent a number.

Default output BYTE-IDENTICAL - `ehp.py score_by="team_blended"` is DEFAULT-OFF. This
is a pre-flip fix, not an incident.

## Findings the directive did not ask for

- **ANTI-NORMALIZATION, stronger than R133/R143.** Zephyr ships ONLY as mirrors
  `223172`/`663172`. The bare `3172` a prefix-strip would synthesize is **GUNMETAL
  GREAVES** - an unrelated boot with zero tenacity. A strip does not mis-price; it
  resolves to a DIFFERENT ITEM. (Shadowflame is the magnitude version: `4645` 20% vs
  Arena `224645` 15%.)
- **FEED CONFLICT.** Meraki's single Crown row keyed `444644` (50%/3s) matches
  DDragon's SR `664644` (40%/3s), not DDragon's own `444644` (90%/1.25s). The feeds
  disagree about which item the key NAMES. No constant invented; the guard re-derives
  the conflict each run and fails if a patch makes them agree.

## CARRY-FORWARD - live-gated, do NOT settle offline

Arena Awe mirrors `223119` Winter's Approach / `223121` Fimbulwinter read "Health
equal to Total Mana" / "based on Mana" where SR reads "bonus mana", and their stat
blocks are genuinely retuned (600 mana / 400 HP vs 500 / 550, gold 2500 vs 2400).
DDragon strips the numeral from every Arena row; Meraki keys base ids ONLY (all five
mirrors absent from its 320 entries). Verifier independently confirmed **the catalog
CANNOT settle it**. Base nominal carried, not guessed. Needs a live Arena probe.

## Process findings worth keeping

1. **Suite totals are ORDER-SENSITIVE under `pytest-randomly`** - the same worktree
   gave 8976/2664 and 8965/3208 on two runs, both green; some tests re-shape into
   subtests by collection order. Pin `-p no:randomly` before comparing counts. An
   arithmetic reconciliation of two slices' counts mid-run was spurious and was
   retracted.
2. **The gist hook corrupted the INDEX in 3 of 5 worktrees** post-commit (~4654
   phantom staged deletions; `ls-tree` 4657 vs index 4; files intact on disk). Commit
   trees were clean, so the round merged by **CHERRY-PICK, never `git merge`** - a
   merge from a corrupt index would have shipped the deletions. Final commit verified
   `--diff-filter=D` EMPTY.
3. **There are TWO changelogs and a bump needs BOTH.**
   `agents/daemon_slayer/CHANGELOG.md` (format `1.231.0 (`) is what
   `test_changelog_tracks_engine_version` reads; `Share/CHANGELOG.md` (format
   `## ENGINE_VERSION x -> y`) is the package one. Updating only Share fails the
   suite - the guard caught it.
4. A bump is a **128-file / 149-literal** mechanical edit (quoted literal pinned
   across the DS test suite).

## Verified fresh (ordering pinned)

DS **9026 passed / 1 skipped / 3554 subtests**; RC **12288 passed / 23 skipped / 359
subtests**; ruff repo-wide clean; ASCII hygiene 13 passed; `ds_share_sync --check` in
sync 1.231.0 / 499 files; DS `:8893` live at 1.231.0 / 16.14.1 / 173 champs / 706
items. The 2 post-bump reds were stamp-propagation (doc anchor + a live probe against
the still-stale server), both green after the fix and bounce - not logic regressions.

Five worktree slices, five verifier gates, Claude sole merger.

## Don't-redo

- The 14 `_item_*.py` registries are SWEPT for mirror coverage - do not re-scan.
- `_ALLY_GRANT_MIRROR_SOURCE` is an id-to-id map ON PURPOSE. Do NOT "simplify" it to a
  prefix-strip or normalization helper - Zephyr proves a strip resolves to a different
  ITEM.
- The Arena `22xxxx` ally-grant mirrors are held at 0.0 DELIBERATELY. Do not seed them
  with base nominals.
- Crown `444644` stays excluded until the two feeds agree.
