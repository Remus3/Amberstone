# LEAP-03 - On-hit (ds.onhit) consumer-surface completion

Status: SPEC (pre-implementation). Author pass: 2026-07-16.
Target model: claude-opus-4-8, effort HIGH.
Estimated sessions: 1 (short).
Context: 7th archetype scorer `ds.onhit` shipped Slice B, ENGINE 1.216.0, LEDGER 911.

---

## GOAL

front-load the thinking into specs; execution sessions are typing, not deciding.

The 7th archetype scorer `ds.onhit` (on-hit AP combined-DPS: ability-DPS + on-hit
auto-DPS, so Nashor's Tooth surfaces for Gwen / Kayle / Kog'Maw) is BUILT and
LIVE-proven end to end: the scorer, kit-credit routing, the AP/AD axis-coherence
gate, the `/rank-onhit` route, the client `rank_onhit_for`, the dispatcher branch,
the live-calibrated roster, and `default_for_champion` routing all landed
(LEDGER 911; live E2E on `/api/build-plan` confirmed `scorer=onhit` + Nashor's for
all three, controls held).

What did NOT land is the last mile of the CONSUMER surface. Four residual gaps
keep onhit a second-class citizen versus the other six archetypes:

  (a) The `/rank-onhit` ROUTE and its client `rank_onhit_for` silently drop the
      `apply_mode_modifiers` + `phase` params that every sibling ranker honors -
      even though the engine function `rank_items_by_onhit` already accepts both.
      Result: an ARAM/phase-aware onhit ranking is mode-blind (SR-only) at the
      HTTP boundary. Gwen/Kayle/Kog'Maw are all ARAM-relevant, so this matters.
  (b) Two stale forward-reference comments outlived Task 9 (they say the roster
      "does not exist yet" / describe Task 9/10 tests as still-pending, when both
      shipped in the SAME session).
  (c) The champ-select archetype whitelist (`ARCHETYPES` / `IMPLEMENTED_SCORERS`)
      still enumerates SIX archetypes, so `default_for_champion` can already
      RETURN `"onhit"` (archetype_picks.py:483-484) yet the taxonomy that
      validates and advertises it does not know the word - and the read-only
      combat-style CHIP renders an onhit champ with the neutral fallback tint
      instead of the dedicated onhit tint that already exists in CSS.
  (d) `docs/DAEMON_SLAYER.md:169-172` still documents a SIX-archetype "6-button
      3x2 picker grid" - doubly stale: seven scorers now exist, and that picker
      grid was REMOVED (LEDGER 823) in favor of a read-only chip.

CRITICAL PREMISE CORRECTION (read EVIDENCE before writing code): the task framing
"champ-select archetype picker has no manual onhit option / add a 7th button to
the 3x2 grid" is based on the STALE DAEMON_SLAYER.md doc, not the live tree. The
operator-facing 6-button picker GRID was DELETED (LEDGER 823) because clicking a
scorer wrote a `user_cs` pick into the shared committed `data/cs_archetype_picks.json`
that the build-order precompute reads, polluting every operator's committed build
tables. There is NO grid to add a button to. The live UI is a read-only chip
(`web/js/panels/archetype_chip.js`). Follow-up (c) is therefore NOT "add a
7th picker button"; it is "make the taxonomy + the read-only chip onhit-aware."
Do NOT re-introduce a picker grid (GHOST LIST).

Everything here is plumbing + taxonomy + docs. No new scorer, no new math, no
dispatcher redesign.

---

## EVIDENCE (ground-truth, every claim cited file:line, verified 2026-07-16)

### (a) Route + client drop mode/phase; engine already accepts them

- `agents/daemon_slayer/onhit_dps.py:332` `def rank_items_by_onhit(...)` - its
  signature ALREADY declares `phase: Optional[str] = None` (:342) and
  `apply_mode_modifiers: bool = False` (:350), and forwards both internally to
  the composed compute (onhit_dps.py:431-432 and :465-466). The engine is ready.
- `agents/daemon_slayer/server.py:1146-1204` `_route_rank_onhit` - parses
  champion/level/items/mode/target_*/budget/slots/top/sort/include_components/
  filter_shared_uniques/apply_passive_damage/ap_ad_coherence, then calls
  `rank_items_by_onhit(...)` (:1186-1199). It NEVER parses or forwards `phase`
  or `apply_mode_modifiers`. The route docstring (:1155-1158) enumerates the
  params it deliberately drops (target_current_hp_pct/max_priority/block_strategy/
  form_index/block_index/apply_ability_amps) but does NOT list phase/mode - they
  are simply omitted, not intentionally excluded.
- SIBLING PARITY PATTERN = `_route_rank` (the DPS ranker `/rank`),
  server.py:421-492: parses `phase = _opt_str(body, "phase")` (:431), validates
  `if phase not in ("early","mid","late"): raise _ApiError(400, ...)` (:433-434),
  parses `apply_mode_modifiers = _opt_bool(body, "apply_mode_modifiers", False)`
  (:448), and forwards BOTH into the ranker (`phase=phase` :475,
  `apply_mode_modifiers=apply_mode_modifiers` :482). `_route_rank_tank`
  (:606,:658), `_route_hybrid` (:715-717,:753-756), `_route_rank_bruiser`
  (:796-798,:816,:862,:870), and `_route_beam` (:1985-2012) follow the same
  shape. This is the exact code to mirror into `_route_rank_onhit`.
- TASK-FRAMING NOTE: the task suggested comparing against `/rank-mage` or
  `/ability-dps`. Ground truth: `_route_rank_mage` (server.py:1082-1143) does
  NOT forward `apply_mode_modifiers`/`phase` either - its `rank_items_by_ability_dps`
  call (:1121-1138) omits them, so `/rank-mage` is the WRONG parity template.
  The correct sibling is `/rank` (`_route_rank`). Use it.
- CLIENT SIDE: `core/daemon_slayer_client.py:952-1009` `rank_onhit_for` - its
  signature (:952-969) has no `phase`/`apply_mode_modifiers` param and its POST
  body (:986-1000) never sends them. So even after the route accepts the params,
  no Python consumer can reach them until the client passes them through. Full
  consumer-completion needs BOTH halves.

### (b) Two stale forward-reference comments (Task 9 obsoleted them)

- `core/daemon_slayer_client.py:1114-1116` (docstring of `_onhit_coherence_for`):
  "``core/ds_onhit_ap_roster.py`` does not exist yet as of Task 7 - the
  ``except ImportError`` branch below is the ACTIVE path today ... until Task 9
  ships the roster + loader." PROVABLY FALSE now: the roster shipped (Task 9),
  `core/ds_onhit_ap_roster.py` exists and is imported unconditionally at
  archetype_picks.py:53, and `tests/test_onhit_ap_routing.py:88` asserts
  `_onhit_coherence_for("Gwen") == 1.0` - i.e. the TRY branch is the active path,
  not the ImportError branch.
- `tests/test_onhit_ap_routing.py:6-7` (module docstring): "Task 9/10 append more
  tests to this same file ... once core/ds_onhit_ap_roster.py lands." Future
  tense for work already DONE below in the same file (Task 9 tests at :62-156,
  Task 10 tests at :159-178). This is the literal "stale test comment" of the
  task framing; #1 above is a stronger, provably-false instance in the client
  module. Fix both (same Task-7-era root; both are doc-only Tier-0 edits).

### (c) Whitelist + chip are onhit-blind; picker grid is GONE

- `core/archetype_picks.py:60-62` `ARCHETYPES = ("carry","bruiser","tank","mage",
  "assassin","enchanter")` (six) and `ARCHETYPE_SET = frozenset(ARCHETYPES)`
  (:63). `IMPLEMENTED_SCORERS` (:69-71) is the same six. Neither knows "onhit".
- `core/archetype_picks.py:483-484` `default_for_champion` ALREADY returns
  `("onhit", ...)` for the on-hit-AP roster (Gwen/Kayle/Kog'Maw). So the taxonomy
  is internally inconsistent: the resolver emits "onhit", but `save_archetype_pick`
  would REJECT it - `if primary not in ARCHETYPE_SET: raise ValueError` (:564-567)
  - and the `/api/cs-archetype-pick` GET enum (`list(ARCHETYPES)` +
  `sorted(IMPLEMENTED_SCORERS)`, routes_archetype.py:57-58,:64-66) never
  advertises it.
- PICKER REMOVED: `web/js/panels/champ_select.js:2204-2210` - "The operator-facing
  archetype PICKER was removed (LEDGER 823): clicking a scorer wrote a user_cs
  pick into data/cs_archetype_picks.json, a shared committed file the build-order
  precompute reads ... What remains is the read-only path below." And
  `web/js/panels/archetype_chip.js:7-9` - "Since the operator archetype picker
  was removed (LEDGER 823) nothing renders it ... This chip surfaces it read-only."
- CHIP is onhit-blind: `web/js/panels/archetype_chip.js:21-31` `_ARCH_TINT` maps
  carry/marksman/adc/bruiser/tank/mage/assassin/enchanter/support to existing
  build-badge tints but has NO "onhit" key, so an onhit champ falls through to
  `csv-build-badge-default` (:33-36) - it renders the label "ONHIT" (fail-soft,
  by design :18-20) but with the neutral tint.
- THE ONHIT TINT ALREADY EXISTS: `web/css/panels/champ_select_view.css:1949`
  `.csv-build-badge-onhit { color: #67e8f9; background: #082f3a; border-color:
  #1e6b80; }` (used by the build-badge system, champ_select.js:1272). Wiring
  `onhit: "csv-build-badge-onhit"` into `_ARCH_TINT` is a zero-new-CSS change.
- READ/DISPLAY side is already onhit-aware end to end: the dispatcher branch
  `rank_for_primary_archetype` handles `arch == "onhit"` (daemon_slayer_client.py:
  1458-1478), and `coach_integration/archetype_dispatch.py` already maps onhit in
  `_UNIT_SUFFIX` (:60) and `_DISPLAY_LABEL` (:73). No dispatch work needed.

### (d) Stale doc

- `docs/DAEMON_SLAYER.md:169` - "Six canonical archetypes ... all six implemented
  and wired through rank_for_primary_archetype() (carry -> ds.dps ... enchanter
  -> ds.hps)". Now seven (onhit -> ds.onhit).
- `docs/DAEMON_SLAYER.md:172` - "UI: 6-button 3x2 picker grid in the My Pick card
  ... Clicks save to localStorage.rc-cs-archetype-<champion> + POST. Unimplemented
  scorers grayed but still clickable." Doubly stale: the picker was removed
  (LEDGER 823); the live surface is the read-only archetype chip.
- `core/archetype_picks.py:4-12` (module docstring) - "The Daemon Slayer engine
  ships six scorer archetypes ...". Now seven.

### Test that pins the count (RED-first anchor)

- `tests/test_archetype_picks.py:235` `self.assertEqual(len(ARCHETYPES), 6)` and
  `:252-254` `assertEqual(IMPLEMENTED_SCORERS, {carry,bruiser,tank,mage,assassin,
  enchanter})` will go RED the moment onhit is added. These are the natural
  RED-first anchors for slice (c).

### UNVERIFIED-SKIP (1)

- The internal signature of `rank_items_by_ability_dps` (does IT accept
  phase/apply_mode_modifiers?) was NOT probed to conclusion - the grep found no
  `def` line in ability_dps.py within the 2-probe budget. It is NOT load-bearing:
  `/rank` (`_route_rank`) is the verified parity template, and `/rank-mage`'s
  ROUTE was directly read and confirmed to omit the forward. Skip stands.

---

## SCOPE

1. `/rank-onhit` route mode/phase parity: add `phase` (parse + early|mid|late
   validation) and `apply_mode_modifiers` (parse) to `_route_rank_onhit` and
   forward both into `rank_items_by_onhit`, mirroring `_route_rank`:431-434,448,
   475,482.
2. Client passthrough: add `phase: Optional[str] = None` +
   `apply_mode_modifiers: bool = False` to `rank_onhit_for`, emitting the body
   keys ONLY when non-default (byte-identical for flagless callers).
3. Whitelist onhit: append `"onhit"` to `ARCHETYPES` and add it to
   `IMPLEMENTED_SCORERS` in `core/archetype_picks.py`.
4. Chip tint: add `onhit: "csv-build-badge-onhit"` to `_ARCH_TINT` in
   `web/js/panels/archetype_chip.js`.
5. Stale comments: fix `core/daemon_slayer_client.py:1114-1116` +
   `tests/test_onhit_ap_routing.py:6-7`.
6. Docs: `docs/DAEMON_SLAYER.md:169` (six -> seven) + `:172` (picker grid ->
   read-only chip) + `core/archetype_picks.py:4-12` docstring (six -> seven).

## NON-SCOPE (and why)

- Re-adding the removed 6-button picker grid. It was deleted deliberately
  (LEDGER 823 - committed-file build-table pollution). GHOST.
- Wiring `apply_mode_modifiers` into the LIVE coach dispatch
  (`dispatch_for_coach`, archetype_dispatch.py). That helper does not pass
  `apply_mode_modifiers` for ANY archetype today (kwargs :253-271); adding it for
  onhit alone (or all) is a cross-scorer live behavior change that needs its own
  eyeball/gate. This spec only restores API PARITY at the route+client boundary
  so consumers that DO pass the flag (ds-preview, tests, a future ARAM-aware
  path) get correct results.
- `_ARCHETYPE_AXIS` (archetype_picks.py:134-137) entry for onhit. That map is the
  INPUT set to `axis_correct_archetype`, only ever called with the six tag
  archetypes (:470); onhit is an OUTPUT of `default_for_champion`, never an input
  to axis correction. `.get()` is used (:307), so no KeyError. Leave it out.
- Dispatcher / scorer redesign. Settled: the 6-scorer plan is fully wired with no
  fallbacks; onhit already dispatches. This adds a picker/taxonomy option, not a
  scorer.
- DS coverage-% / match-row prose recompute (nested-registry hazard; DS-batch job
  only).
- ENGINE_VERSION bump (see R5 TIER).

---

## DESIGN DECISIONS

- D1 - Grid-for-7 layout is MOOT (task asked to pick 4x2-with-spacer vs
  3x3-minus-2). There is no grid: the picker was removed (LEDGER 823). Decision:
  do NOT introduce any grid. The read-only chip renders a single resolved
  archetype, so button-layout does not apply. (If a picker were ever revived -
  explicitly out of scope - the cleaner layout would be 4x2 with the 8th cell a
  spacer, since 3x3-minus-2 leaves a ragged bottom row. Recorded only to close
  the question; it is a NON-GOAL here.)
- D2 - mode/phase forward semantics IDENTICAL to sibling routes. Defaults
  `apply_mode_modifiers=False`, `phase=None`. Validate `phase in
  ("early","mid","late")` else `_ApiError(400, ...)`, byte-for-byte mirroring
  `_route_rank`:433-434. On the client, emit `body["phase"]` only when not None
  and `body["apply_mode_modifiers"]` only when True (mirrors the `if augments:`
  / seam-flag pattern documented at archetype_dispatch.py:275-293), so a flagless
  call produces a byte-identical body. `rank_items_by_onhit` already accepts both
  - this is pure plumbing, zero engine math change.
- D3 - Append `"onhit"` at the END of the `ARCHETYPES` tuple (not mid-tuple). The
  file comment (archetype_picks.py:57-59) is explicit that UI order + persisted
  localStorage/JSON keys key off this order and it must stay stable; appending is
  the only safe edit. Add to `IMPLEMENTED_SCORERS` (order-independent frozenset).
- D4 - Chip tint reuses the pre-existing `.csv-build-badge-onhit` CSS class
  (champ_select_view.css:1949). No new CSS rule, no new UI-audit CSS surface -
  the chip module's own comment (archetype_chip.js:11-13) requires reuse of the
  existing tint family.
- D5 - No ENGINE bump. Justification in R5 TIER.
- D6 - Optional polish (recommended): add an explicit `"onhit": "mage"` entry to
  `_fallback_secondary` (archetype_picks.py:493-500). Today an onhit primary with
  no `tags[1]` falls through `.get(primary, "bruiser")` to "bruiser"; "mage" is
  the truer AP alt-view. Low-stakes (operator-overridable), but keeps the alt-view
  coherent for the on-hit-AP champs. Include if cheap; drop if it complicates the
  slice.

---

## TESTABLE ACCEPTANCE CRITERIA (RED-first; write the test, watch it fail, then fix)

Route + client parity (slice 1-2):

- AC1 (route forwards, RED-first) - in `tests/test_onhit_ap_routing.py`, patch
  `agents.daemon_slayer.server.rank_items_by_onhit`, call
  `server._route_rank_onhit({"champion":"Gwen","level":13,
  "apply_mode_modifiers":True,"phase":"early", ...})`, and assert the mock was
  called with `apply_mode_modifiers=True` and `phase="early"`. RED today (the
  route passes neither, so the mock sees the defaults False/None). Mirrors the
  existing mock-based idiom in that file (:16-22).
- AC2 (phase validation parity, RED-first) - `_route_rank_onhit` with
  `phase="bogus"` raises `_ApiError(400, ...)`, exactly as `_route_rank` does.
  RED today (param silently ignored -> no 400).
- AC3 (client passthrough, RED-first) - assert `rank_onhit_for(..., phase="mid",
  apply_mode_modifiers=True)` puts `phase="mid"` and `apply_mode_modifiers=True`
  into the POST body, and that a flagless call omits both keys (byte-identical).
  Patch `_post_json` and inspect the body dict.

Whitelist (slice 3):

- AC4 (RED-first) - update `tests/test_archetype_picks.py:235` to
  `assertEqual(len(ARCHETYPES), 7)` and add `assertIn("onhit", ARCHETYPES)`; RED
  until the tuple grows.
- AC5 (RED-first) - update `:252-254` so `IMPLEMENTED_SCORERS` equals the
  seven-member set incl `"onhit"`; RED until the frozenset grows. The
  `issubset` guard (:245) stays green.
- AC6 - `save_archetype_pick(champion="Gwen", primary="onhit")` no longer raises
  `ValueError` and round-trips (was rejected pre-change by :564-567). New test.

Chip (slice 4):

- AC7 (RED-first) - in `web/js/panels/archetype_chip.test.mjs`, add
  `assert.match(archetypeChipHtml("onhit"), /csv-build-badge-onhit/)` to the
  known-archetypes test (currently :18-25). RED today (onhit -> default tint).
  The existing unknown-tint case (:46-50, "specialist") stays as the fallback
  example. Run `node --test`.

Docs + comments (slice 5-6): verified by re-read (Tier-0, no automated test).
Confirm no banned glyphs (ASCII only) and that DAEMON_SLAYER.md:169/172 name
seven archetypes and the read-only chip.

Whole-slice gate: full DS dual suite (agents/daemon_slayer/tests + tests/) green
apart from the 3 known pre-existing fails (coach_poll x2 + doc_size_budget);
`/api/cs-archetype-pick` (no champion) returns `"onhit"` in both `archetypes`
and `implemented`; `/api/cs-archetype-pick?champion=Gwen` still resolves
primary=onhit; live `/api/build-plan` for Gwen still shows `scorer=onhit` +
Nashor's (unchanged - onhit default output must not move).

---

## R5 TIER (classify each change; run only that tier's verification)

- Slice 1 (`server.py` `_route_rank_onhit`) = TIER-2 (engine-surface: a DS route
  whose new params reach the scorer). Run the full DS dual suite; re-sync the
  Daemon Slayer SHARE MIRROR for server.py; restart DS `:8893`
  (schtasks /End then /Run RC-DaemonSlayer - confirm the port is free first, the
  detached-child gotcha). BUT NO ENGINE_VERSION BUMP: `apply_mode_modifiers`
  defaults False and `phase` defaults None, so every existing (flagless) caller's
  output is BYTE-IDENTICAL; no scorer formula, no anchor, no coverage change. The
  136 onhit anchor pins and the DS suite must pass UNCHANGED - that is the proof
  the default path did not move. ENGINE_VERSION stamps scoring math / Share
  distributable identity; exposing an already-supported, default-off param at the
  HTTP boundary is plumbing, not a scoring change. This matches the standing
  "forward-marker: no bump, still Share + restart" pattern
  (memory feedback_ds_forward_marker_no_bump). Keep the literal `1.216.0`.
- Slice 2 (`core/daemon_slayer_client.py` `rank_onhit_for`) = TIER-1 RC-side (one
  module; not in the Share mirror). `py_compile` + `tests/test_onhit_ap_routing.py`.
- Slice 3 (`core/archetype_picks.py` whitelist) = TIER-1 (one module + its tests
  `tests/test_archetype_picks.py`). No engine, no Share, no `:8893`, no DS scoring
  impact.
- Slice 4 (`web/js/panels/archetype_chip.js`) = ASSET-ONLY. Per ADR-008 the
  `web/{js,css}` asset-hash auto-reloads; NO RC restart. BUT it is a UI page
  change, so the UI FIXTURE RITUAL applies: run the 5-phase fixture audit
  (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) on the champ-select
  My Pick chip BEFORE the commit, resolve every MUST-FIX in the same slice.
  Verify the onhit chip renders with the cyan onhit tint (not the neutral
  default). Node test via `node --test archetype_chip.test.mjs`.
- Slices 5-6 (stale comments + `DAEMON_SLAYER.md` + module docstring) = TIER-0
  cosmetic (doc/comment). Edit + (for .py) `py_compile`. No suite, no restart.
  Watch the em/en-dash + smart-quote ban; `tools/precommit_gate.py` is the
  backstop.

---

## FILES TOUCHED

Production / engine:
- `agents/daemon_slayer/server.py` - `_route_rank_onhit` (1146-1204): add phase
  parse+validate + apply_mode_modifiers parse + forward both into the
  `rank_items_by_onhit(...)` call. [Tier-2, Share + `:8893` restart, NO bump]
- `core/daemon_slayer_client.py` - `rank_onhit_for` (952-1009): add
  phase/apply_mode_modifiers params + conditional body keys; AND fix the stale
  docstring (1114-1116). [Tier-1 + Tier-0]
- `core/archetype_picks.py` - `ARCHETYPES` (60-62) + `IMPLEMENTED_SCORERS`
  (69-71) add "onhit"; module docstring (4-12) six -> seven; optional
  `_fallback_secondary` (493-500) onhit->mage (D6). [Tier-1 + Tier-0]

UI (asset-only, 5-phase audit):
- `web/js/panels/archetype_chip.js` - `_ARCH_TINT` (21-31) add
  `onhit: "csv-build-badge-onhit"`. [asset-only]

Tests:
- `tests/test_onhit_ap_routing.py` - add route + client parity tests (AC1-AC3);
  fix stale docstring (6-7).
- `tests/test_archetype_picks.py` - update count/set asserts (235, 252-254) +
  add onhit membership + save round-trip (AC4-AC6).
- `web/js/panels/archetype_chip.test.mjs` - add onhit tint assertion (AC7).

Docs:
- `docs/DAEMON_SLAYER.md` - lines 169 (six -> seven, + onhit -> ds.onhit) and 172
  (picker grid -> read-only chip; note LEDGER 823 removal).

Optional (5-phase-audit surface, include only if the render case adds value):
- `tests/snapshot_panels/conftest.py:61` fixture `archetypes` list + a new onhit
  render case in `tests/snapshot_panels/test_champ_select_archetype_chip.py`.

Frozen files: NONE touched (server.py, daemon_slayer_client.py, archetype_picks.py,
archetype_chip.js are all non-frozen; verified against the CLAUDE.md frozen list).

---

## EST SESSIONS + MODEL

1 short session. Target model claude-opus-4-8, effort HIGH. The slices are small
and independent; the only real cost is the Tier-2 DS suite + Share mirror +
`:8893` restart for the one-route server.py edit, and the 5-phase chip audit.
TDD RED-first per slice (the pinning tests already exist to invert).

---

## DONE RITUAL

1. TDD each slice RED-first (AC1-AC7); watch each fail before fixing.
2. `py_compile` every edited .py before any restart (silent-crash guard).
3. Run `tests/test_archetype_picks.py` + `tests/test_onhit_ap_routing.py` +
   `node --test web/js/panels/archetype_chip.test.mjs`.
4. Tier-2 for server.py: full DS dual suite (agents/daemon_slayer/tests + tests/);
   confirm the 136 onhit anchors + suite pass UNCHANGED (byte-identical default
   proof); re-sync the Daemon Slayer Share mirror for server.py; restart DS
   `:8893` (schtasks /End then /Run RC-DaemonSlayer, port-free first).
5. 5-phase fixture audit on the champ-select archetype chip BEFORE commit; resolve
   every MUST-FIX in-slice; confirm the onhit chip renders the cyan onhit tint.
6. Live verify: `/api/cs-archetype-pick` advertises "onhit" in archetypes +
   implemented; `/api/build-plan` for Gwen still `scorer=onhit` + Nashor's
   (unchanged); ENGINE_VERSION still 1.216.0.
7. Commit + push (banned-glyph gate must pass - ASCII only). Append the per-item
   entry to `docs/LEDGER.md` (NEVER CLAUDE.md). Update WAKEUP_NOTES. Confirm CI
   green before declaring done.

---

## GHOST LIST (do NOT do these)

- Do NOT re-design or re-pitch the archetype dispatcher. Settled: the 6-scorer
  plan is fully wired with no fallbacks, and onhit already dispatches
  (daemon_slayer_client.py:1458-1478). This spec ADDS a taxonomy/picker option,
  not a scorer.
- Do NOT re-introduce the 6-button 3x2 picker grid or any write-surface picker.
  It was removed for cause (LEDGER 823 - committed-file build-table pollution).
  The read-only chip is the intended surface.
- Do NOT touch `web/js/dashboard.js` - it is dead code (no `<script>` ref). The
  live picker/chip path is `web/js/panels/*` loaded via `/js/main.js`.
- Do NOT recompute DS coverage %/match-row prose (nested-registry mis-parse
  hazard; DS-batch job only).
- Do NOT bump ENGINE_VERSION (default output is byte-identical; see R5 TIER).
- Do NOT add "onhit" to `_ARCHETYPE_AXIS` (it is an axis-correction INPUT set;
  onhit is only ever an OUTPUT of default_for_champion).
- No em-dashes / en-dashes / smart quotes anywhere - 7-bit ASCII only.
- Frozen files stay untouched.
