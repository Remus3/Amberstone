# RM-141 - League Classic / JADE mode detection + coach surface (SPEC)

Author: SPEC agent, 2026-08-02. HEAD 0a9240b9. Patch 16.15.1.
Engine at authoring was ENGINE 1.270.0, superseded by 1.271.0 on 2026-08-04;
nothing in this spec depends on the engine revision - see A4.
Status: SPEC ONLY. No code written by the spec pass. TDD mandatory: failing
test first.

## 0. Constraints restated (binding on every slice)

- 7-bit ASCII only. No em dashes, no en dashes, no smart quotes, anywhere -
  in code, comments, tests, docs or commit messages.
- TDD is mandatory. Write the failing test FIRST, prove it RED, then implement.
- The framed question is ANSWERED and CLOSED: "League Classic" is Riot's JADE
  throwback mode. Do not re-ask it.
- Do NOT re-litigate the settled keystone or the phase-driven view-router
  (item 87). ARAM Mayhem reports queueId 2400 and the view-router is correct.
- Do NOT widen the queue-coverage filter to kAlternativeLeagueGameModes.
  RM-128 refuted that by measurement; eight already-mapped ids live there
  under three different mode_keys. Widening to kJade is a DIFFERENT and
  legitimate change - kJade is a group whose every member is genuinely that
  mode, which is exactly the discriminator COVERAGE_GROUPS documents.
- Do NOT re-open the closed 173/173 DS_SWEEP roster.
- Brawl is retired from champ-select (s214). Its backend is NOT deadcode
  (corrected 2026-08-06 - `core/game_snapshot.py:98-102` also routes URF /
  ARURF / ONEFORALL / GAMEMODEX / NEXUSBLITZ to `MODE_BRAWL`, and the coach is
  importlib-loaded for all of them; see `docs/DAEMON_SLAYER.md`). It is
  used in this spec ONLY as a shape reference for how a mode_key threads
  through MODE_TO_FILE and the coach registry. Do NOT revive it, and do not
  copy brawl_coach.py as a template.
- core/game_snapshot.py and app/_game_lifecycle.py are FROZEN files. Edits are
  allowed this run under the operator's headless-upgrade grant but must be
  MINIMAL and SURGICAL - the spec below caps each at 3 lines. The grant is for
  THIS run only and does not carry forward.

## 1. What the "jade" mode key must be, end to end

### 1.1 game_snapshot mode string

Ground truth: core/game_snapshot.py:64-95 is gameMode-STRING only and never
consults queueId. ALL_MODES is at :71. The catch-all default at :95 returns
MODE_SR for ANY unrecognised value.

Upstream naming, measured from data/meta_build/ddragon/16.15.1/summoner.json:
34 spell rows carry a `modes` list; the distinct tokens include JADE (16 rows)
and KIWI_JADE (8 rows) as SEPARATE tokens, alongside CLASSIC (9), ARAM (9),
KIWI (7), CHERRY (2). Riot models JADE and KIWI_JADE as two distinct
gameModes, and CLASSIC remains the SR token.

Required: add MODE_JADE = "JADE" beside the existing constants and append it
to ALL_MODES.

TWO ORDERING TRAPS, both currently live bugs:

  TRAP A. "KIWI_JADE" today returns MODE_SR. The ARAM branch at :86 tests
  gm in ("ARAM","ARAM_UNRANKED_5X5","KIWI","ODIN") or gm.startswith("ARAM").
  "KIWI_JADE" matches none of those. An ARAM-Mayhem-Jade game is therefore
  coached as Summoner's Rift today.

  TRAP B. A naive `if "JADE" in gm` inserted before the ARAM branch would
  capture KIWI_JADE into MODE_JADE, which is WRONG. history_notes records that
  the ARAM-Mayhem-Jade crossover on the Howling Abyss is the likely first
  contact, and 151 of the 162 throwback items claim maps["12"] (Howling
  Abyss). A KIWI_JADE game is played on the Abyss, so the ARAM coach surface
  is the correct one.

Therefore the ONLY correct edit is, in this order:
  1. add "KIWI_JADE" to the existing ARAM tuple (one token);
  2. add an exact-match JADE branch AFTER the ARAM branch and BEFORE the
     ARENA branch;
  3. append MODE_JADE to ALL_MODES.
Three lines. Nothing else in the frozen file may move.

Do NOT use a substring test. Use exact equality on "JADE". This mirrors the
rule in agents/daemon_slayer/mode_variants.py:33-36 - the KEY is canonical,
never the name - one layer up: a substring test on a mode string is the same
class of error as a name-prefix test on a champion row.

### 1.2 core/mode_capabilities.py

MODE_CAPABILITIES (:41) is fail-CLOSED by contract. Add:

  MODE_JADE: {"has_wards": False, "district_config": None}

has_wards False and district_config None are DELIBERATE, not placeholders.
config/minimap_grids/ holds sr / aram / arena / brawl / tft and has no map-453
grid; the map-453 geometry has never been observed. Fail-CLOSED is the
documented safe-default for this table. Both values become LIVE-GATED rows
(section 5).

Do NOT add "JADE" to _RAW_SR_STRINGS (:39). That frozenset exists precisely to
stop the catch-all SR default from leaking capabilities, and JADE now has its
own canonical key so it never reaches that branch.

### 1.3 core/queue_modes.py - the queue ids

QUEUE_ID_TO_MODE_KEY starts at :40. The kJade group is unmapped today and the
reason is written at :31, tied to the absence of a jade key in
dashboard/_state_builder.py MODE_TO_FILE. Deciding that key IS this row.

Measured from data/queue_catalog_snapshot.json (fetched 2026-08-02T03:16:56Z):
group_counts carries "kJade": 17. The snapshot records only fingerprint /
group census / mapped ids / coverage_candidates, so the per-id kJade rows are
NOT on disk - the id list below comes from the ROADMAP RM-141 row's recorded
probe and MUST be re-verified by the refresh command in 1.3.2 before being
committed.

  1.3.1 Mapping rule
    - 4300..4310 (kPvP)      -> "jade"
    - 4320, 4321 (kVersusAI) -> "jade"
    - 3260, 3261, 3262 (kCustom) -> DELIBERATELY UNMAPPED.
      Precedent is exact and already in the file: 3280 is left unmapped
      because its gameSelectCategory is kCustom, and mode_key_from_queue_id
      returns None for queue_id 0 (custom / Practice Tool) by contract. Custom
      lobbies are no-coach in RC. Write the same comment for the three kJade
      kCustom ids so a later reader does not "fix" them.

  1.3.2 The snapshot is a hard dependency
    tests/test_queue_map_grounding_rm128.py asserts every mapped id still
    exists upstream, reading data/queue_catalog_snapshot.json. Adding ids
    without refreshing turns the suite RED on purpose. The slice MUST run:
      python tools/upstream_drift_check.py --refresh-queue-snapshot
    This is a CDragon HTTP fetch, NOT a live game, so it is in scope for a
    headless session. If the network is unreachable, the slice STOPS - do not
    hand-edit the snapshot.

  1.3.3 Census widening
    tools/upstream_drift_check.py:308 COVERAGE_GROUPS = ("kARAM",
    "kSummonersRift"). Append "kJade". COVERAGE_EXCLUDED_CATEGORIES already
    holds ("kCustom",), so the three 32xx ids self-exclude and the census
    stays honest without a second rule. Re-read the comment at :295-307
    before editing: it explains why kAlternativeLeagueGameModes stays out,
    and that reasoning is NOT a reason to keep kJade out.

### 1.4 dashboard/_state_builder.py MODE_TO_FILE + the data file

MODE_TO_FILE is at :56-65. Add exactly one entry:

  "jade": "coaching_data.json",

That is the SAME file sr / client / game already share. Consequences, all
verified:
  - MODE_FILES (:72) is tuple(dict.fromkeys(MODE_TO_FILE.values())) so the
    deduped artifact list is BYTE-UNCHANGED. agents/supervisor.py consumes
    MODE_FILES and needs no edit.
  - _state_builder.py:348 already reads
    MODE_TO_FILE.get(mode_key, "coaching_data.json"), so the resolution was
    already correct by fallback. The explicit entry exists because
    tests/preflip_mode/test_queue_modes.py and
    tests/test_queue_map_grounding_rm128.py assert that every mapped mode_key
    is a KEY of MODE_TO_FILE. Without it, S3 goes red.

WHAT WRITES THAT FILE: nothing new. coaching_data.json is the SR coach's
artifact. core/coach_registry.py MODE_COACH_MAP maps the four NON-SR modes to
their own writers; SR is deliberately absent because it is the default path
driven by core/sr_aram_worker.py. JADE joins the SR default path (section 2),
so RM-141 adds ZERO writers, ZERO files and ZERO entries to MODE_COACH_MAP /
MODE_POLICY_MAP.

### 1.5 What must NOT get a jade entry

  - dashboard/_state_builder.py:467 - minimap_rect gated to
    ("sr","aram","brawl"). LEAVE IT. Map 453 has no grid.
  - dashboard/_state_builder.py:504 - ZOI gated to ("sr","aram"). LEAVE IT.
  - core/theme.py:69 TAB_COLORS - no jade entry until a live game proves the
    tab is reachable.
  - core/coach_registry.py - see 1.4.
S1's test must PIN these absences so a later slice cannot quietly add them.

## 2. Does JADE reuse the SR coach path? YES. Reasons, with cites.

### 2.1 The dispatch, as it actually exists

  - core/coach_registry.py MODE_COACH_MAP keys on _tft_mode / _arena_mode /
    _brawl_mode / _aram_mode. SR is NOT in it.
  - app/__init__.py:155-158 sets those four booleans from the envelope mode.
    A MODE_JADE envelope leaves all four False, which is exactly the SR shape.
  - core/sr_aram_worker.py:167 is where the SR coach actually fires:
        is_sr_mode = gm_upper in ("CLASSIC", "RANKED", "PRACTICETOOL")
        if self._coach is not None and is_sr_mode:
            self._submit_coaching(state)
    A JADE tick fails that membership test, so NO coach fires today.
  - app/_game_lifecycle.py:374-390 selects the payload shape:
        elif env_mode in (MODE_SR, MODE_ARENA, MODE_BRAWL) and app.reader:
            payload = app.reader.to_rift_snapshot(state)
    and the emergency fallback at :387 repeats the same tuple. A MODE_JADE
    envelope falls to payload = None on both, so NO snapshot is produced.

CURRENT-STATE behaviour of a JADE game, stated honestly: envelope mode SR (via
the :95 catch-all), no coach fired, no rift payload built, coaching_data.json
goes stale, dashboard silently shows the LAST SR game's advice. That is worse
than a missing surface - it is a WRONG one.

### 2.2 Why reuse and not a new coach

JADE is 5v5 lane-and-objective League. The catalog names it "5v5 Jade" /
"Classic Rift" with descriptions "5v5 Classic", "Classic Co-op vs. AI". Every
macro primitive the SR coach emits - lane state, wave, objective timers, lead
projection, recall windows - is defined the same way. Building a jade_coach.py
would fork nearly all of the SR coach to change nothing that matters. The
smallest correct answer is a two-token widening.

### 2.3 The honest caveat that makes JADE not-quite-SR

Measured from data/meta_build/ddragon/16.15.1/item.json:
  - map 453 legal pool: 416 items = 265 canonical + 151 throwback-band.
  - map 11 legal pool: 316 items, of which exactly ONE is in the band.
  - map 11 AND map 453: 266. map 11 only: 50. map 453 only: 150.
An SR item recommender aimed at a JADE game can suggest any of 50 items the
JADE shop does not sell, and can never suggest any of the 150 it does. That is
not a rounding error.

This is why "jade" must be a DISTINCT mode_key even though it shares SR's
coaching file: the key is the hook a later slice uses to suppress or re-target
the item/build half. RM-141 does NOT build that suppression, because the JADE
shop contents are LIVE-GATED (section 5) and RC has no ingested throwback item
data to re-target to (section 3). Section 6 files it as a follow-on.

## 3. DS side: ingested or merely documented? -> MERELY DOCUMENTED. TIER-1.

### 3.1 The probe (re-run any of these to re-verify)

  data/daemon_slayer/16.15.1/champions.json     173 rows, 0 with key >= 60000
  data/daemon_slayer/16.15.1/items.json         706 rows, 0 in [770000,780000)
  data/meta/ddragon_champions.json              173 rows, 0 jade
  data/meta/ddragon_items.json                  706 rows, 0 band
  data/meta/ddragon_summoner_spells.json         18 rows, 0 with a JADE mode
  data/meta_build/ddragon/16.15.1/champion.json 233 rows, 60 jade
  data/meta_build/ddragon/16.15.1/item.json     868 rows, 162 band
  data/meta_build/ddragon/16.15.1/summoner.json  34 rows, 16 JADE, 8 KIWI_JADE
  :8860 /health -> patch 16.15.1, champions 173, items 706 (engine read
                   1.270.0 at authoring, since superseded - not load-bearing)

The filtering happens at TWO independent places and BOTH already ship:
  - scripts/data_pipeline.py:95-131 filters at MIRROR time. data/meta/* is
    RC's LIVE-ROSTER cache read by ~15 modules that key by display NAME, which
    the throwback rows duplicate. The faithful copy is kept at
    data/meta_build/ddragon/<patch>/ so nothing is lost.
  - agents/daemon_slayer/data_loader.py:167-174 filters again at LOAD time via
    canonical_champions / canonical_items.

### 3.2 Verdict

The Jade_ rows and the [770000,780000) keyspace are FAITHFULLY MIRRORED and
THOROUGHLY DOCUMENTED, and are INGESTED BY NOTHING. No DS registry, no
scenario table, no build order, no scorer sees them.

RM-141 therefore requires ZERO changes under agents/daemon_slayer/ and ZERO
changes to any data/daemon_slayer/ artifact. No engine formula, parameter,
scorer or registry moves. DS /health output is unchanged.

  => TIER-1. NO ENGINE_VERSION bump. NO four-anchor doc update. NO Share
     mirror sync. NO dual suite in one commit. NO :8860 bounce.

This is the RM-140 lesson applied: the row's own tier guess is not evidence.
RM-140 assumed Tier-2 and shipped Tier-1 because nothing upstream had moved.
Same shape here - the upstream content moved in 16.15.1 and was ALREADY
handled, by partition, in commit 9df58480. RM-141 consumes that decision; it
does not revisit it.

### 3.3 Why the ingest is not a deferred slice but a BLOCKED one

core/build_order_precompute.py:576-582 states, and mode_variants.py:22-24
repeats: Meraki 404s all 60 Jade_ champions, so they have no ability formulas,
no wiki sidecar, no archetype pick and no build order. A DS ingest would add
60 champion rows that no downstream stage can cover, plus 162 items that would
corrupt the map-12 ARAM pool. Do NOT file "ingest the throwback registry" as
buildable work. File it as BLOCKED-UPSTREAM with that cite.

## 4. The KIWI_JADE crossover - what history_notes constrains

NOTE ON LINE DRIFT: line numbers in the ROADMAP row and in earlier hand-offs
are STALE. Cite the TEXT, not the number, and re-grep before quoting. A third
surviving "alias" mention lives at docs/history_notes.md:919.

### 4.1 The ALIAS read was WRONG

The prior session's read that the Jade_<Champion> rows are ALIASES was WRONG
in a way that mattered: they carry their own older-patch stat line, and the
same drop added 162 items in [770000, 780000) plus 16 modes:["JADE"] spells.
The dedupe guard that landed defused champion inflation but could not have
caught the item half.

Re-measured against data/meta_build/ddragon/16.15.1/champion.json:
  Jade_Ahri  key 60103  name "Ahri"  hp 460
  Ahri       key 103    name "Ahri"  hp 590
Same display name, different key, different stat line. A name-keyed dedupe
absorbs one into the other and silently serves an older patch's Ahri.

CONSTRAINS: (a) never dedupe or classify by the "Jade_" name prefix - the key
test (>= VARIANT_CHAMPION_KEY_FLOOR) is canonical, per mode_variants.py:33-36,
which also warns a name test would miss the next variant Riot ships under a
different word; (b) any prose still calling these "aliases" is REFUTED and
must be corrected, not repeated.

### 4.2 Revisit the partition, do not extend it

history_notes: "When a JADE mode appears in mode detection, revisit the
partition rather than extend it. The live Flash row already advertises a
KIWI_JADE mode, so an ARAM-Mayhem-Jade variant on the Howling Abyss is the
likely first contact - that is exactly why 151 of the 162 throwback items
claim maps["12"]."

Re-measured: band item map flags are 453:151, 12:151, 11:1, 21:1. The
prediction holds exactly.

CONSTRAINS, three ways:
  (a) RM-141 is the moment that note anticipated. Revisit = re-read
      mode_variants.py and confirm the partition still describes reality
      (it does). Do NOT drop the filter as mode_variants.py:30-31 invites
      ("When a real throwback mode is wired into mode detection, drop the
      filter rather than re-extracting history") - that invitation is
      CONDITIONAL on downstream being able to cover the rows, and 3.3 shows
      it cannot.
  (b) KIWI_JADE routes to ARAM, not JADE. That is section 1.1 TRAP B and it
      is the single most important test in the whole row.
  (c) The Abyss-first expectation means the JADE-proper surface may never be
      exercised before the KIWI_JADE one. Both must be correct on day one.

### 4.3 The refuted wording still in the tree - must be corrected

  - BACKLOG.md:50 - "the 60 extras are Jade_<Champion> alias rows (name =
    base champion)". REFUTED by 4.1. The surrounding CLOSED-STALE verdict on
    the 16.15.1 refresh is CORRECT and must be preserved. Rewrite only the
    "alias" clause: they are throwback-mode VARIANT rows at base_key + 60000
    carrying their own older-patch stat line, partitioned out at mirror time
    and again at load time. Keep the "do not treat them as new champions"
    conclusion - that half was right for the wrong reason.
  - docs/history_notes.md:919 - same "alias" wording. history_notes is an
    append-only archive of immutable session records; correct it with an
    inline bracketed correction note rather than a rewrite, or leave it and
    scope the guard test to exclude docs/history_notes.md. The slice decides
    and states which, in its commit body.
  - tools/daemon_slayer_build_orders_generate.py:167 - same wording in a
    docstring. Not mirrored into Share/src/tools, so this is a free
    correction.
  - tests/test_build_order_producer_fail_loud.py:267 - same wording in a test
    docstring.
  - ROADMAP.md RM-141 row - add the SHIPPED verdict and the tier finding.

## 5. LIVE-GATED (rows for docs/LIVE_GAME_GATED_SYNC.md, NOT slices)

No live JADE game is available. Every item below is an EYEBALL against a real
game, not a build. None blocks S1-S5; each can only CONFIRM or CORRECT what
S1-S5 assume.

  L1. gameMode string. Assumed "JADE" from 16 spell rows carrying
      modes:["JADE"]. CONFIRM the liveclient allgamedata gameMode field reads
      exactly "JADE". If it reads "CLASSIC" instead, section 1.1's exact-match
      branch is dead code and the row re-scopes to queueId detection - which
      core/game_snapshot.py deliberately does not do. HIGHEST-VALUE row here.
  L2. KIWI_JADE string. Same check inside an ARAM Mayhem Jade game. Confirms
      TRAP B's routing is exercised and not theoretical.
  L3. championName. Does liveclient report "Ahri" or "Jade_Ahri"? If the
      latter, every champion lookup in the SR coach misses and the row grows a
      normalisation layer. Section 2 ASSUMES the former.
  L4. queueId observed in a real JADE lobby, checked against the ids S3 maps.
  L5. Map 453 geometry: minimap rect, ward legality, whether the SR district
      grid is even approximately right. Unblocks mode_capabilities has_wards
      and district_config, and the _state_builder :467 / :504 gates.
  L6. Shop contents: does the JADE shop actually offer the 151 band items?
      Unblocks the item-advisor question in 2.3.

## 6. Follow-on rows this spec deliberately does NOT build

  F1. JADE item-advice correctness. Blocked on L6 and on 3.3. File as BACKLOG
      with the 416 / 266 / 50 / 150 measurement so the next reader does not
      re-derive it.
  F2. DS ingest of the throwback registry. BLOCKED-UPSTREAM (Meraki 404s all
      60). Cite core/build_order_precompute.py:576-582. Not buildable.
  F3. Map-453 minimap grid. Blocked on L5.

## 7. Slices

Every file appears in exactly ONE slice. Verified disjoint.

--- S1: dashboard mode-file resolution -------------------------------------
GOAL: "jade" resolves to the SR coaching file, and is pinned OUT of the two
      map-geometry gates.
FILES:
  dashboard/_state_builder.py
  tests/test_state_builder_jade_mode_file.py            (new)
TEST FIRST (must be RED before the edit):
  - assert MODE_TO_FILE["jade"] == "coaching_data.json"   (RED: KeyError)
  - assert MODE_FILES is unchanged in length and content vs the pre-edit
    tuple (guards the dict.fromkeys dedupe)
  - assert "jade" not in the minimap_rect gate tuple at :467 and not in the
    ZOI gate tuple at :504 - a source-text assertion is acceptable here and
    is the cheaper pin
CMD: python -m pytest tests/test_state_builder_jade_mode_file.py -q
MERGE: 1st.

--- S2: mode string + capabilities -----------------------------------------
GOAL: "JADE" becomes a first-class mode string; "KIWI_JADE" is pinned to ARAM.
FILES:
  core/game_snapshot.py                                 (FROZEN - 3 lines max)
  core/mode_capabilities.py
  tests/preflip_mode/test_jade_mode_string.py           (new)
TEST FIRST (must be RED before the edit):
  - mode_from_game_mode_string("JADE") == "JADE"          (RED: returns "SR")
  - mode_from_game_mode_string("KIWI_JADE") == "ARAM"     (RED: returns "SR")
  - mode_from_game_mode_string("jade") == "JADE"          (case)
  - "JADE" in ALL_MODES
  - GameEnvelope accepts mode "JADE" without raising
  - mode_from_game_mode_string("CLASSIC") == "SR" still   (no regression)
  - mode_from_game_mode_string("KIWI") == "ARAM" still    (no regression)
  - has_capability("JADE","has_wards") is False
  - district_config("JADE") is None
  - has_capability("KIWI_JADE","has_wards") is False      (routes via ARAM)
CMD: python -m pytest tests/preflip_mode/test_jade_mode_string.py -q
FROZEN-FILE NOTE: the game_snapshot.py diff must be 3 lines - one token added
  to the ARAM tuple, one new JADE branch, one constant appended to ALL_MODES
  plus its definition. Any larger diff is a spec violation and the verifier
  must reject it.
MERGE: 2nd.

--- S3: queue map + coverage census ----------------------------------------
GOAL: kJade PvP / VersusAI ids pre-flip the dashboard to jade; the census
      learns to watch the group.
FILES:
  core/queue_modes.py
  tools/upstream_drift_check.py
  data/queue_catalog_snapshot.json                 (regenerated, not hand-edited)
  tests/preflip_mode/test_queue_modes.py
  tests/test_queue_map_grounding_rm128.py
TEST FIRST (must be RED before the edit):
  - mode_key_from_queue_id(4300) == "jade"               (RED: None)
  - the same for every kPvP / kVersusAI id the refreshed snapshot confirms
  - mode_key_from_queue_id(3260) is None, and 3261, 3262 - with a comment
    naming the kCustom precedent (3280)
  - "kJade" in tools.upstream_drift_check.COVERAGE_GROUPS
  - "kAlternativeLeagueGameModes" NOT in COVERAGE_GROUPS (RM-128 regression pin)
  - the existing assertion that 4300 is None must be REWRITTEN, not deleted -
    it is a deliberate pin whose comment reads "deliberately unmapped pending
    RM-141"; the replacement comment must say RM-141 mapped it and name the
    kCustom exception
  - 2300 (Brawl) stays None
PRECONDITION: run
    python tools/upstream_drift_check.py --refresh-queue-snapshot
  BEFORE committing, and confirm group_counts still reports kJade and that
  every newly mapped id appears in mapped_queues with present=true. If the
  fetch fails, ABORT the slice; do not hand-edit the snapshot.
CMD: python -m pytest tests/preflip_mode/test_queue_modes.py
       tests/test_queue_map_grounding_rm128.py -q
MERGE: 3rd.

--- S4: coach path reuse ---------------------------------------------------
GOAL: a JADE tick actually fires the SR coach and builds a RiftSnapshot.
FILES:
  core/sr_aram_worker.py
  app/_game_lifecycle.py                                (FROZEN - 2 lines max)
  tests/test_jade_coach_path.py                         (new)
TEST FIRST (must be RED before the edit):
  - with a stub state {"game_mode": "JADE"}, SrAramWorker._submit_coaching IS
    called                                               (RED: is_sr_mode False)
  - with {"game_mode": "KIWI_JADE"}, _submit_coaching is NOT called (that is
    the ARAM coach's tick, not the SR coach's) - pins TRAP B end to end
  - env_mode MODE_JADE selects the rift payload branch and the emergency rift
    fallback in app/_game_lifecycle.py, i.e. payload is not None
  - CLASSIC / RANKED / PRACTICETOOL still fire (no regression)
EDIT SHAPE:
  - core/sr_aram_worker.py:167 - extend the tuple to
    ("CLASSIC","RANKED","PRACTICETOOL","JADE") and extend the comment above it
    to say JADE is the throwback Rift and shares the SR coach.
  - app/_game_lifecycle.py:375 and :387 - add MODE_JADE to both tuples. Two
    lines. Nothing else in the frozen file may move.
CMD: python -m pytest tests/test_jade_coach_path.py -q
MERGE: 4th.

--- S5: doc correction + gated filing --------------------------------------
GOAL: kill the refuted "alias" wording tree-wide; file the six LIVE-GATED
      rows; land this spec.
FILES:
  BACKLOG.md
  ROADMAP.md
  docs/LIVE_GAME_GATED_SYNC.md
  tools/daemon_slayer_build_orders_generate.py          (docstring only)
  tests/test_build_order_producer_fail_loud.py          (docstring only)
  tests/test_jade_alias_wording_guard.py                (new)
TEST FIRST (must be RED before the edit):
  - a tree scan asserts no tracked .md or .py describes Jade_ rows as
    "alias" / "aliases" (scope the scan to files mentioning "Jade_" so it
    stays fast and cannot false-positive on unrelated uses of the word;
    state explicitly whether docs/history_notes.md is in or out of scope and
    why)                                                 (RED: 3+ hits today)
  - a positive pin that survives the rewrite: load
    data/meta_build/ddragon/16.15.1/champion.json and assert
    Jade_Ahri.key == "60103" and Ahri.key == "103" and their hp differ. This
    is the MEASUREMENT that refutes the alias read; keeping it in the suite
    means the refutation can never silently rot back.
  - assert docs/LIVE_GAME_GATED_SYNC.md contains rows L1..L6 by id
  - ASCII guard: every file this slice touches is 7-bit clean
CMD: python -m pytest tests/test_jade_alias_wording_guard.py -q
MERGE: 5th, last. Prose only; no import depends on it.

## 8. Merge order and why

  S1 -> S2 -> S3 -> S4 -> S5

  S1 before S3: the preflip and grounding tests assert every mapped mode_key
    is a key of MODE_TO_FILE. S3 is red without S1.
  S2 before S4: S4 imports MODE_JADE.
  S1 and S2 are independent of each other; either may be BUILT first in
    parallel worktrees, but S1 MERGES first so the queue slice never sees a
    half-state.
  S3 and S4 are independent of each other.
  S5 last: it asserts on the finished state of the tree.

After the final merge, run the repo-root suite once in full. Per the repo-root
suite rule, per-slice runs prove the slice; only the root run proves the merge.

## 9. Acceptance

  A1. A synthetic tick with game_mode "JADE" produces envelope mode "JADE",
      mode_key "jade", coach file coaching_data.json, a RiftSnapshot payload,
      and a fired SR coach.
  A2. A synthetic tick with game_mode "KIWI_JADE" produces envelope mode
      "ARAM" and takes the ARAM coach path. Unchanged from what an ARAM tick
      does today.
  A3. mode_key_from_queue_id returns "jade" for the kJade PvP/VersusAI ids and
      None for the three kCustom ids.
  A4. Nothing under agents/daemon_slayer/ or data/daemon_slayer/ changed.
      ENGINE_VERSION is UNCHANGED BY THIS ROW - compare it against the value
      at the start of the implementing session, never against a literal
      pinned here, which goes stale on the next unrelated engine bump.
      :8860 /health still reports 173 champions / 706 items. Share mirror
      untouched.
  A5. No tracked file calls the Jade_ rows aliases (subject to the
      history_notes scope decision in 4.3).
  A6. docs/LIVE_GAME_GATED_SYNC.md carries L1..L6.
  A7. Whole tree is 7-bit ASCII clean.
  A8. Repo-root suite green.
