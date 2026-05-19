# Contextual DS-backed BUILD-ORDER — staged plan & overnight status

**Owner:** operator (SamplePlayer) · **Author:** overnight autonomous run, 2026-05-17
**Resume context:** WAKEUP_NOTES.md "2026-05-17 wrap — OVERNIGHT AUTONOMOUS DIRECTIVE"

---

## TL;DR (read this first)

The PRIMARY goal is **DONE at the engine/wiring layer and proven end-to-end
against the live DS server.** "Always the same items" is fixed and the hard
unique-passive no-double rule is enforced by the engine's own source-of-truth
dedup — with **zero engine change**. What remains is the dashboard UI rendering
of the ordered build, which is deliberately staged for an operator-reviewed
session (UI-audit ritual + a live game to verify) rather than shipped blind
overnight.

Commits this run (all green, ruff + py_compile clean, pushed=NO — local main):
- `1a20424` feat(build-order): core/build_order.py planner + 19 headless tests
- `18139a5` feat(build-order): opt-in wiring into coach dispatch + live-proof + 3 tests
- `240f709` feat(build-order): read-only /api/build-order endpoint + 7 route tests
- `da4f334` test(build-order): anti-drift / all-6-families no-double guard (5 tests)
- `81af51e` test(build-order): sync dispatch-validate path pin for /api/build-order

**Run totals:** 5 commits, ~37 new test methods (22 planner + 3 dispatch +
7 route + 5 guard) + 1 pin sync. **Full `tests/` suite: 1141 passed, 0
failed** (one self-introduced pin regression caught by the full-suite run
and fixed in-run — `81af51e`). 0 engine changes, ENGINE stays 1.3.0, 0 DS
restart, ruff + py_compile clean throughout.

**To go live on the dashboard:** `echo restart > restart_trigger.txt` on
Legion (deferred overnight — unattended supervisor restart risk vs marginal
gain; the route is headless-proven + the planner is live-proven vs :8893).
After restart, verify: `curl -k -X POST https://127.0.0.1:8888/api/build-order
-d '{"champion":"Ezreal","mode":"SR","level":13}'` → ordered build JSON.

Nothing is blocked on you for the backend. Two non-blocking items need a
live game (see §6).

---

## 1. Root cause (mapped this run)

`daemon_slayer_client.rank_for_primary_archetype` + the 6 underlying
`rank_items_by_*` scorers do **greedy single-item marginal scoring** vs a
fixed owned-item set and return a flat top-N. Coaches surface that flat list
(`coach_integration/archetype_dispatch.py:display_rows`). Consequences:

1. **"Always the same items"** — with a near-naked champion the #1 marginal
   item is deterministic per (champion, level); generic early enemy stats →
   same top item every game. No notion of a *sequence* / spike timing.
2. **Unique-passive double-pick** — dedup only filters a candidate that
   collides with an *already-owned* item's `unique_passive_key`. The ranked
   *list itself* can contain Trinity Force **and** Essence Reaver (both
   `spellblade`). Treating that list as a build = the forbidden double.

Unique-passive families are engine-tagged in `agents/daemon_slayer/effects.py`
— **6, not 3** (corrected from an earlier draft): `spellblade` (16 items —
Trinity Force / Lich Bane / Essence Reaver / Iceborn / Divine Sunderer /
Dusk-and-Dawn + Arena 22xxxx mirrors), `lifeline` (12 — Sterak's / Maw /
Shieldbow / Hexdrinker / Seraph's / Protoplasm + mirrors), `immolate` (7 —
Sunfire / Hollow Radiance + mirrors), and three single-item families
`fiendhunter_barrage`, `hellfire_char`, `innervating_fill`. Source of truth =
`collect_effects` + `rank.py current_unique_keys`. **This is exactly why the
planner must NOT carry its own family map** — it would have shipped knowing
only 3. Because the planner is family-agnostic (defers to engine iteration),
it covers all 6 — and any future family — for free. A machine-checked
anti-drift guard (`tests/test_build_order_no_double_guard.py`, 5 tests)
asserts: the planner source contains no family literal; every engine family
(derived at runtime) is un-doublable in a plan; a single-family pool yields
exactly 1; and the family set hasn't regressed below 6 (s232-style tripwire —
a 7th family is auto-covered, a dropped tag trips the test).

## 2. The fix shipped (pure orchestration, no engine change)

`core/build_order.py` · `plan_build_order(...)` → `BuildOrderResult`:

- **Order = iterative greedy forward selection.** One ranker call per slot;
  the chosen item is appended to `item_ids` before the next call. Each slot
  re-ranks against the *accumulated build + real enemy context*
  (`target_armor/mr/max_hp/bonus_hp`, already plumbed from `enemy_stats`).
  The sequence now adapts to the match — directly kills "always the same".
- **No-double = engine-authoritative.** The planner forces
  `filter_shared_uniques=True` (a caller cannot weaken it via `rank_kwargs`).
  Once slot-1 = e.g. Trinity Force is in `item_ids`, every later slot's
  server-side `current_unique_keys` has `spellblade` locked → all other
  spellblade candidates are filtered by the engine. Iterating inherits that
  guarantee for the whole sequence **without duplicating the family map**
  here (avoids the s173 anti-drift trap). `unique_passive_safe` invariant
  is True by construction; a planner-side skip of any `shares_dead_unique`
  row is belt-and-suspenders for the off-default caller.
- Engine-down / blank-champion → `None` (mirrors `dispatch_for_coach`).
  Engine-up-but-empty → short order + explanatory note (not `None`).

**Live proof vs real DS :8893** (in commit `18139a5` body): a flat bruiser
ranking restricted to {Trinity Force, Lich Bane, Essence Reaver} returns all
3 together (the bug); the planner picks Trinity Force then the real engine's
dedup filters the other two for every later slot → order stops at exactly 1,
`unique_passive_safe=True`. Architecture validated end-to-end.

## 3. Wiring shipped (additive, opt-in)

`coach_integration/archetype_dispatch.py`:
- `CoachDispatchResult.build_order` (default `None`).
- `dispatch_for_coach(..., with_build_order=False, build_order_slots=6)`.
- **Opt-in by design:** an ordered plan is N sequential engine calls vs the
  single call the per-tick coach path needs. Test asserts default-off ⇒
  exactly 1 engine call. A build-order failure never sinks the (already
  successful) flat dispatch.

Existing `display_rows`/`picks_str` consumers + all prior dispatch tests
unaffected (purely additive). 62-test consumer slice green.

## 4. Gap found this run (route to operator)

**`only_item_ids` is silently ignored by the carry/dps branch.** The
`carry` fall-through in `rank_for_primary_archetype` calls `rank_for(...)`
which has no `only_item_ids` param (only tank/bruiser/mage/assassin/
enchanter thread it — see `core/daemon_slayer_client.py:111` vs `:189/:302/
:388/:526`). Whitelisting candidates for a carry/ADC silently no-ops. Not a
build-order regression (the planner works on the full pool fine), but it's a
latent surprise for any caller. **Fix (small, ~1 file):** add
`only_item_ids` to `rank_for` + thread `body["only"]` like the siblings;
needs a DS server restart to take effect (`:8893` is not supervisor-watched).
Staged, not shipped overnight (touches the engine client + needs restart).

## 5. Staged next steps (operator-reviewed)

### Phase 2 — read-only `/api/build-order` endpoint  *(DONE — `240f709`)*
`dashboard/routes_state._serve_build_order_post` ships. Body = ds-preview
body + `slots`; returns `BuildOrderResult.to_dict()` + `target_stats`.
Registered in `POST_ROUTES` + `BuildOrderRequest` soft-validation schema.
7 headless route tests (family-aware fake engine — no-double rule proven
through the HTTP layer). Goes live on the next RC restart (operator-driven).

### Phase 3 — dashboard UI render of the ORDER  *(operator-reviewed session)*
`web/js/panels/item_build.js` + champ-select build chooser currently render
the flat scorer rows (`#ds-pill`, `#ib-ds-block`, `_csvBuildVariantsFor`).
Add an "ordered build" presentation: slots 1→6 with per-slot delta + the
"why" (context line: vs Xarmor/Ymr) + an excluded-family chip when the
engine dropped a same-passive item. **Why staged, not overnight:** UI
changes want the per-page UI-audit ritual (memory
`feedback_phase3_fixture_ritual.md`) + a live game to verify
(`feedback_screenshot_after_ui_changes.md`); shipping a blind redesign
while asleep is exactly what that feedback says not to do. The
`/api/build-order` endpoint (Phase 2) lets the operator curl/preview the
ordered build immediately, decoupled from the UI work.

### Phase 4 — context enrichment  *(design discussion)*
Greedy forward selection is the right v1 (it's how human build guides
reason + it makes the order match-specific + it enforces the no-double
rule by construction). Optional later upgrades, each its own session:
(a) per-slot gold/spike-timing gate so slot-1 = the early power spike, not
just max marginal; (b) live enemy-build re-derivation feeding
`target_armor/mr/hp` from the actual enemy inventory mid-game so the order
re-plans as they itemize; (c) beam search over item *sets* if greedy's
local-optimum is ever observed to matter (it rarely does — flag, don't
pre-build, per the no-over-engineering rule); (d) expose each candidate's
own `unique_passive_key` on `RankedItem` across all 6 rankers + server so
the planner can label *which* family each pick locks (currently it only
surfaces engine-supplied exclusions, by design — no family-map dup). (d)
is a clean ~6-file additive change but needs the manual DS restart, so it
is operator-reviewed, not autonomous.

## 6. Not blocked on the backend — but these need a live game (operator)

- **Champ-select KNOWN BUG (ARAM / ARAM-Mayhem / Arena "all wrong").**
  Unspecified — needs a champ-select pop in *each* of the 3 modes to see
  what's broken (layout vs data vs render). Champ-select capture is
  Vanguard-SAFE (only *in-game* capture crashes). Not investigated this
  run (no live champ-select; not the primary goal).
- **Augment / LCU-WebSocket discovery** (now un-tabled per the directive).
  The only trustworthy test is, AT the moment the augment picker is on
  screen in a live Mayhem/Arena game: subscribe LCU WS `OnJsonApiEvent` +
  log changing resource URIs, hit `:2999 activeplayer/playerlist`, and
  enumerate the LCU resource tree properly (not substring-grep). Pure
  HTTP, Vanguard-safe. Needs a live augment window — can't be done
  headless overnight.

## 6b. Phase-3 UI design menu (cascade-6 research — decide in the reviewed session)

Researched competitor presentation + dense-dashboard UX so the operator's
Phase-3 session starts from a decision, not a blank page. **Do not
implement blind — this is a menu, the operator picks.**

**What the best tools do** (Aggregator C / Aggregator B, 2026): build = a
*sequential numbered order* (1st → 6th), an explicit **core vs
situational** split, rationale tied to *champion synergy + matchup +
enemy comp*. Aggregator B's edge is "granular data, clean UI". RC's edge over
them: the order is *live-contextual* (re-ranked vs the actual enemy
stats) and carries the unique-passive-exclusion signal they don't show.

**Dense-dashboard UX (directly relevant to the operator's font-floor /
viewing-distance / no-overload constraints):** lead with a high-level
summary, reveal detail on demand (hover/expand), prioritise the
decision-critical fields, no clutter. RC already lives this idiom
(`#ds-pill` glance + `data-tt-html` rich tooltip from s213) — the order
should reuse it, not invent a new one.

| Option | What | Pros | Cons |
|---|---|---|---|
| **A** inline "📋 Order" row in the existing champ-select build chooser (`_csvBuildVariantsFor`) | slots 1→6 L→R, gold+delta, per-item `data-tt-html` = the "why" | smallest new surface, reuses tested tooltip | 6 slots + deltas horizontally fights viewing-distance/density; competes with the 3+Experimental rows |
| **B** dedicated vertical "Build Order" card (champ-select + Post-Game) | numbered 1→6, icon + name + 1-line rationale + delta badge; excluded-family muted chip on the slot; collapsed to top-3 with a "full build" expander; hover = deeper math | matches the competitor-proven vertical-numbered mental model; most readable across the room; room for the "why" + exclusion signal; progressive-disclosure = the overload guard the operator cares about | new card → layout negotiation; needs the per-page UI-audit ritual + a Game-PC screenshot before "done" |
| **C** glance-only `#ds-pill` upgrade | pill shows next-2-in-order `▸ Trinity → Boots`, full order in its tooltip | tiniest change, in-game-safe, zero new layout | under-delivers per-slot rationale + the exclusion signal |

**Recommendation:** **B** for champ-select + Post-Game (where a build is
actually planned), **C** as the in-game glance companion (reuses the
existing pill, no in-game layout risk). **Reject A** — horizontal
cramming of 6 slots+deltas directly contradicts
`feedback_font_size_viewing_distance.md` (trim content, don't shrink).

**Rationale text is data-driven, not LLM** (matches the operator's
prefer-deterministic-DS stance + zero token cost): `/api/build-order`
already returns per-slot `delta`+`unit`, `context`, `excluded_family`,
`excluded_example`. Render e.g. `"+142 dps vs 90 armor"` and a muted
`"locks Spellblade · Essence Reaver dropped"` — short, plain, no verbose
prose.

**Seams:** data = the shipped `/api/build-order`; render = a new
`web/js/panels/build_order.js` consumed by `item_build.js` (B's card) +
a 2-line `#ds-pill` extension (C). Gate behind the existing
asset-hash/auto-reload (ADR-008) — no RC restart needed for the JS once
the route is live. Build the UI fully before any further DB wiring
(`feedback_ui_before_db_wiring.md`).

## 7. Discipline notes for the next session

- Screen agents stay DISABLED (Vanguard `vgk.sys` BSOD = screen capture,
  CONFIRMED — do not re-litigate; memory `feedback_gamepc_screen_capture_bsod.md`).
- DS engine untouched this run → ENGINE_VERSION unchanged (1.3.0), no DS
  restart needed. `core/build_order.py` is pure orchestration.
- `core/build_order.py` is NOT a frozen file; `archetype_dispatch.py` change
  is additive. `gen_archmap.py` must run when adding modules (pre-commit
  hook enforces it — ran this session).
- Commit-msg hook warns subjects >100 chars (warning, not block).
