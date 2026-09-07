# RC 2.0 Phase-1 Research (stage 1.4): CHAMP-SELECT UX

Grounded, cited survey of champ-select (pick/ban phase) assistance in
aggregator A, Aggregator B, Overlay App E, Overlay App F, Aggregator C, Draft Tool L, and Aggregator D, with
a 6-point LIFT verdict for each pattern against RC's CURRENT champ-select
surface.

Scope = the ~30-45 second pick windows (LCU phase `ChampSelect`), all four
modes (SR draft / ARAM / Arena / TFT-not-applicable). The sibling LOBBY
phase is covered in `docs/research/RC2_RESEARCH_lobby.md` and not re-walked
here.

ASCII only. Cited from live repo greps + web sources (URLs at bottom).
Date: 2026-06-19. Author: research subagent.

---

## 0. What "glance-useful" means in a 30-45s pick window

Across every tool surveyed, the features that earn their screen space in
the short window fall into four buckets:

1. ONE-TAP STATE WRITES - rune page / item set / summoner spells pushed to
   the client with no typing (every overlay app does this; it is table
   stakes).
2. A SINGLE DECISION PROMPT - "pick X / ban Y / swap to Z" as one line, not
   a wall of stats (Overlay App E Counter Picker, Aggregator C 3-factor ban, Draft Tool L
   best-next-pick).
3. THREAT-AT-A-GLANCE - who on the enemy team is dangerous, encoded as
   colour/tag not prose (Overlay App F player tags; RC's personal-vs WR band).
4. TIMED SUB-DECISIONS unique to the mode - ARAM bench reroll, Arena augment
   tier (both are on their own clocks inside champ select).

Anything that needs more than ~2 seconds of reading (full match history,
deep matchup tables) is pre-game STUDY, not pick-window glance. RC should
weight lift by which bucket a feature lands in.

---

## 1. RC's CURRENT champ-select surface (ground truth)

RC already has the deepest LCU champ-select WRITE integration of any tool
surveyed (it issues bench-swap, augment-intent, ban-intent, pick-intent,
rune-write, spell-set, item-set-push, lane/pick-order/champ-trade), plus a
rich READ surface. The dashboard renders a full-page
`<section id="view-champ-select">` while `lcu.phase === "ChampSelect"`.

### 1a. Polling / reaction cadence (how fast RC sees the session)

- The Legion-local LCU agent (`tools/gamepc_lcu_agent.py`) pushes a full
  champ-select snapshot to the vision server on a 1.0s loop
  (`tools/gamepc_lcu_agent.py:110` `INTERVAL = 1.0`), drains the dashboard
  command queue every 0.5s (`:112` `CMD_INTERVAL = 0.5`), and polls
  ready-check / summoner-override every 0.5s (`:111` `AUTO_INTERVAL = 0.5`).
- The dashboard state envelope (SSE/poll) re-fires every ~2s; the sim
  FakeSocket tick re-fires every 3s. `renderChampSelectView` is gated by an
  idempotent signature (`web/js/panels/champ_select.js:699` `_csvComputeSig`)
  so it only rebuilds panels when the observable pick state changes
  (`:700`).
- NET: RC reacts to an enemy lock / your hover in roughly 1-3 seconds
  end-to-end (1s agent push + up to 2s envelope). This is the SAME
  event-on-LCU-session model every Overlay Platform M competitor uses; no competitor
  publishes a faster number. RC is competitive on timing.

### 1b. LCU champ-select WRITES RC already issues

All via `tools/gamepc_lcu_agent.py` (dashboard POSTs queued `/api/lcu-cmd`,
JS polls `/api/lcu-cmd-result`; helpers in `lcu/lcu_pregame.py`):

| Action | Mechanism | repo cite |
|---|---|---|
| Hover / lock champion | PATCH `/lol-champ-select/v1/session/actions/{id}` | `lcu/lcu_pregame.py:167` `pick_champion` |
| Lock-in button | `cmd: lock_pick` | `web/js/panels/champ_select.js:831` (LOCK IN button) |
| Set pick intent | `cmd: set_pick_intent` | `web/js/panels/champ_select.js:243` |
| Set ban intent | `cmd: set_ban_intent` | `web/js/panels/champ_select.js:241`, `:1043` |
| Bench swap (no 5s cooldown) | POST `/lol-champ-select/v1/session/bench/swap/{id}` | `lcu/lcu_pregame.py:190` `bench_swap_fast`; click `:1369` |
| Lane swap | `cmd: request_position_swap` | `web/js/panels/champ_select.js:217` |
| Champ trade | `cmd: trade_request` | `web/js/panels/champ_select.js:221` |
| Pick-order swap | `cmd: request_pick_order_swap` | `web/js/panels/champ_select.js:225` |
| Set summoner spells | PATCH `/lol-champ-select/v1/session/my-selection` | `lcu/lcu_pregame.py:205`; click `:972` |
| Auto-write rune page | resolves keystone+trees, writes perks | `lcu/lcu_rune_writer.py:149` `build_perk_ids`, `:216` `load_rune_rec` |
| Push 4 build variants to in-game shop | `apply_item_sets_batch` (by-uid) | `web/js/panels/champ_select.js:866` `_csvMaybePushBuildsToLCU` |
| Set augment intent (Arena) | `cmd: set_augment_intent` | `web/js/panels/champ_select.js:3293` |

### 1c. Dashboard champ-select READ / advice surface (all live)

`web/js/panels/champ_select.js` `renderChampSelectView` (`:668`) +
`_csvRenderCentralPane` (`:802`) render, mode-aware (SR / ARAM / Arena via
`_csvDetectMode` `:361`):

- My Pick card: portrait, LOCKED/HOVERING state, lock button
  (`:943`).
- Allies + Enemies team panels (`_csvRenderTeam` `:539`); SR enemy cells
  carry 2 champion tags (CC/burst class) + a leading personal lifetime
  win-rate-vs-this-enemy slot (`/api/personal-vs`, `:518`, band-coloured
  red/amber/green `:485`).
- Summoner-spell strip, click to push D/F (`:878`).
- Build chooser - up to 4 build variants per champ+mode+archetype
  (`_csvBuildVariantsFor`), with a per-category PUSH control (Runes /
  Spells / Build checkboxes) (`:889`).
- DS-backed ordered Build Order card, re-ranked vs the live enemy comp
  (`buildOrderCardHtml` `:930`; enemy ids resolved `:925`).
- Archetype picker (carry/tank/bruiser/... swaps the build) (`:847`).
- SR-only Suggestions panel (`_csvRenderSuggestions` `:997`): suggested
  bans grid (`/api/champ-select/pickban-recs` via `ban_suggest_toggle.js`,
  click to set ban-intent `:1043`); banned-list rows once picks start
  (`:1015`); pick-order advisory (`:1221` `_csvCompAwareTip`); DS top items.
- ARAM-only deterministic comp verdict banner: STAY / SWAP->champ /
  VARIANT->build, with confidence (`POST /api/aram-comp-verdict`,
  `:1656`; engine `dashboard/_champ_select_deterministic.py`, with
  engage/peel notes `:125` `_ally_notes` and enemy AD/AP itemization fact
  `:168` `_enemy_itemization`).
- ARAM bench strip, click-to-swap, highlights the verdict's swap target
  (`_csvBenchHtml` `:1324`).
- Arena: My Duo + Augments pane - 3 augment slots (silver/gold/prismatic)
  + current-round options, click to set intent (`_csvArenaPaneHtml`,
  augment wiring `:3284`). Duo synergy grid via `/api/duo-synergy`
  (101.qq bot+sup seed, `dashboard/routes_duo_synergy.py:324`).
- CC threat cards (blended-EHP threat, conditional pressure, cooldown
  watch, CC-pairing) - DS-engine analyses of the enemy comp
  (`:1771`-`:1913`).
- Live Haiku champ-select coach: advice + summoners + swap + watchout,
  debounced ~1 call / 6-10s of active drafting
  (`/api/champ-select-coach`, `handleChampSelect` `:162`).

### 1d. SR pickban-recs backend (what RC's "suggestions" actually compute)

`dashboard/routes_pickban.py` (`GET /api/champ-select/pickban-recs?role=`):
counters index from `rewind_history.db` (`:100`, `:170`), a "struggle ban"
from the operator's own recent loss matchups (`:683` `_query_struggle_ban`,
`:630` `_query_loss_matchups`), performance comfort/limit/new/synergy bands
(`:350`-`:452`), and a cleanse advisory vs hard-CC enemies (`:699`). This
is a PERSONALIZED engine (operator's own match DB), conceptually closest to
Aggregator C' 3-factor ban.

---

## 2. External patterns + 6-point LIFT checklist

LIFT verdict legend: HIGH = strong fit, low effort or high payoff, clear
integration point, legal re-implementation. MED = useful but real effort or
partial overlap. LOW = RC already has it, or poor fit, or legal/scope
blocker. (Legal: re-implement the PATTERN against RC's own data; never
copy a competitor's stats DB or scrape their gated overlay.)

---

### P1. Live per-pick DRAFT WIN-PROBABILITY (Draft Tool L)

- WHAT: As each champ locks, show a single team-vs-team win-% that updates
  live, plus a ranked "best next pick" list. Draft Tool L's model is additive:
  `allyRating + allyDuos + matchups - enemyRating - enemyDuos` through a
  logistic transform; best-next-pick = linearly sum each available
  champion's score against everything locked.
- HOW: Stats-only, client-side math over an aggregated champ-pair dataset
  (Riot API + Aggregator D, Emerald+). LCU live-sync auto-fills picks/roles/
  bans (Tauri desktop app, read-only). No runes/builds, SR-only.
- RC ALREADY HAVE: PARTIAL. RC has an ARAM deterministic comp verdict
  (`dashboard/_champ_select_deterministic.py`, STAY/SWAP/VARIANT) and a
  personalized SR pickban-recs engine (`dashboard/routes_pickban.py`), but
  NEITHER outputs a live SR team-vs-team win-% that re-computes per pick.
  RC's SR draft surface is counters + struggle-ban + comfort, not a draft
  advantage meter.
- WHERE IT INTEGRATES: a new `/api/draft-advantage` route fed by a champ-
  pair winrate table (RC can build one from `rewind_history.db`'s ~2846
  matches, or seed from a public aggregate it is allowed to use), rendered
  as a header band on `view-champ-select` for SR mode; re-fetched on the
  existing `_csvComputeSig` change (`web/js/panels/champ_select.js:699`).
- EFFORT+RISK: MED-HIGH. The win-% math is simple (a logistic over pairwise
  deltas) and legal to re-implement. The RISK is data: RC's own 2846-match
  DB is far too sparse for champ-pair matchup cells at SR scale (Draft Tool L
  needs millions; cells under ~50 games fall back to baseline). Without a
  large licensed/public aggregate the number would be noisy and mislead.
- LIFT VERDICT: MED. The single most differentiated competitor feature and
  a genuine RC gap for SR, but gated on a credible champ-pair dataset. Ship
  it ONLY if RC adopts a large enough data source; otherwise it is a
  confident-looking wrong number. (The deterministic engine RC already
  prefers - facts not predictions - argues for a "draft notes" framing over
  a single fragile %.)

---

### P2. Counter-pick recommendations vs the LIVE enemy team (Overlay App E Counter Picker, Aggregator C, Aggregator B, Aggregator D)

- WHAT: Given current bans + ally picks + enemy picks, surface the best
  champion(s) for your slot, winrate-based, updating as enemies lock.
  Aggregator C extends this to your remaining ALLIES too. Aggregator D/Aggregator B
  surface per-matchup deltas (and Aggregator B adds CS/kill/gold diff @15 so you
  can tell a farming counter from a kill counter).
- HOW: A counters index keyed by enemy champion, filtered by role, sorted
  by matchup WR delta. Overlay App E/Aggregator C read the LCU session live; Aggregator B/
  Aggregator D counters are per-champ pages (manual second-screen unless via
  their overlay).
- RC ALREADY HAVE: PARTIAL-to-YES. `dashboard/routes_pickban.py:170`
  `_counters_for_champion` builds a counters index from `rewind_history.db`
  and the pickban-recs route is role-filtered. RC also has the personal-vs
  enemy WR band per enemy cell (`web/js/panels/champ_select.js:518`). What
  RC does NOT do: present a "these are your best COUNTER picks given the
  enemy comp" suggestion list for YOUR open slot at pick time, nor advise
  allies.
- WHERE IT INTEGRATES: extend `_csvRenderSuggestions`
  (`web/js/panels/champ_select.js:997`) with a "counter picks" sub-block
  driven by an enhanced pickban-recs response that takes the live enemy ids
  (already resolved at `:925` for the build order) and returns top counters
  for the operator's role.
- EFFORT+RISK: LOW-MED. The counters index and the enemy-id resolution both
  already exist; this is mostly a new response field + a render block. Risk:
  RC's own DB counters are personalized/sparse - may need to blend with a
  global counters source for champs the operator has not faced.
- LIFT VERDICT: HIGH. RC has 80% of the plumbing (counters index + live
  enemy ids + a Suggestions panel + ban-intent click wiring). Turning it
  into a glance "pick X into this comp" list is the highest payoff-to-effort
  item in this doc, and it is the bucket-2 single-decision prompt that wins
  the short window.

---

### P3. One-click / auto rune + spell + item import (aggregator A, Overlay App E, Aggregator C, Aggregator B, Overlay App F)

- WHAT: On hover/lock, push a rune page, item set, and summoner spells to
  the client - either one-tap or fully automatic per game. Universal across
  every overlay app. Aggregator C/aggregator A offer an AUTO toggle (no button).
- HOW: LCU writes - rune-page POST, item-set POST, my-selection PATCH for
  spells. Apps gate spells (off by default / level-10) and manage a single
  owned rune page to avoid clobbering the user's pages.
- RC ALREADY HAVE: YES, fully. Rune auto-write
  (`lcu/lcu_rune_writer.py:149`), spell set (`lcu/lcu_pregame.py:205`, click
  `web/js/panels/champ_select.js:972`), 4-variant item-set batch push
  (`:866`), and a per-category PUSH control with Runes/Spells/Build
  checkboxes (`:889`). RC even pushes ALL 4 build variants into the in-game
  shop dropdown, which several competitors do not.
- WHERE IT INTEGRATES: already integrated. The only competitor delta is the
  AUTO-import toggle (push without a click each game), which RC's PUSH
  control is one boolean away from.
- EFFORT+RISK: LOW (for the auto toggle); already done otherwise. Risk:
  clobbering the operator's rune pages - RC should confirm it writes one
  managed page (RuneWriter does), and note the known live bug that RuneWriter
  fires only on the first champ-select per RC session
  (`reference_runewriter_dies_after_game1` memory).
- LIFT VERDICT: LOW (already have). Mentioned only for the small AUTO-toggle
  enhancement and as a reminder to fix the first-CS-only RuneWriter bug,
  which is a higher-value reliability fix than any new feature here.

---

### P4. Pre-game ENEMY/ALLY scouting table (Overlay App F signature; Overlay App E, Aggregator B, Aggregator C)

- WHAT: During champ select, a table of all 10 players with rank, win rate,
  main champions/mastery, and auto-generated TAGS - smurf, losing/winning
  streak, one-trick, off-role, aggressive/passive. Overlay App F's reason to
  exist; the fastest "who is dangerous" read in the genre.
- HOW: Each player's recent match history pulled from the tool's stats API
  (keyed by the summoner names the LCU session exposes), distilled to
  ranks + tags. Riot ToS allows reading public match history.
- RC ALREADY HAVE: PARTIAL. RC shows the operator's OWN lifetime WR vs each
  enemy CHAMPION (`/api/personal-vs`, band-coloured), and the lobby view
  enriches members - but RC does NOT show each enemy/ally PLAYER's rank,
  mains, or behaviour tags during champ select. RC's angle is "how do I do
  vs this champ", not "who is this player".
- WHERE IT INTEGRATES: a new scouting strip above or beside the team panels
  in `renderChampSelectView`, fed by a route that takes the session's
  summoner names and returns per-player rank + top champs. RC has a Riot
  API key permitted for champ-select full-team context (ADR-006,
  `reference_no_riot_api_key`), so Account-V1 + League-V4 + Match-V5 can
  build it legally.
- EFFORT+RISK: MED-HIGH. New backend (per-player Riot API fan-out, rate-
  limit + cache), new UI strip, and tag heuristics are non-trivial. Riot
  personal key rate limits make a 10-player fan-out in a 30s window tight;
  needs caching + graceful partial render.
- LIFT VERDICT: MED. Genuinely high user value (Overlay App F's whole moat)
  and legal via RC's key, but the heaviest new build in this doc and rate-
  limit-constrained. Strong candidate for a phased lift: ranks first, then
  mains, then behaviour tags.

---

### P5. ARAM bench / reroll tier overlay (aggregator A, Overlay App E, Aggregator C, Aggregator B, Aggregator D)

- WHAT: In ARAM champ select, rate the champions on your BENCH so you know
  which to reroll/swap to. aggregator A shows the OP-Tier of each bench champ
  inline; everyone ships an ARAM tier list. Mayhem variant adds an augment
  tier overlay.
- HOW: An ARAM-specific winrate/tier table joined against the live bench
  champion ids.
- RC ALREADY HAVE: YES (and arguably better). RC's ARAM comp-verdict engine
  recommends STAY / SWAP->bench-champ / VARIANT, deterministically, from the
  ally comp's engage/peel/damage balance (`dashboard/_champ_select_
  deterministic.py`; banner + bench-cell highlight `web/js/panels/
  champ_select.js:1329`, `:1349`). This is a DECISION ("swap to this one"),
  which is stronger than a static per-champ tier the user must interpret.
- WHERE IT INTEGRATES: already integrated. A small enhancement: annotate
  each bench cell with its standalone ARAM win-rate/tier so the operator can
  override the verdict with context (aggregator-A-style), reading from an ARAM
  tier table RC would need to source.
- EFFORT+RISK: LOW (for the per-cell tier annotation, if an ARAM WR table is
  available); the decision engine is done.
- LIFT VERDICT: LOW (already have the hard part). Optional bench-cell tier
  annotation is a nice-to-have, gated on an ARAM WR data source.

---

### P6. Arena AUGMENT tier ratings keyed to your champion (aggregator A, Overlay App E, Aggregator B, Aggregator D, Aggregator C)

- WHAT: In Arena, when the augment-pick prompt appears (silver/gold/
  prismatic rounds), rate the offered augments - ideally filtered to YOUR
  champion. aggregator A's overlay explicitly shows "the tier of augments that fit
  your current champion"; Aggregator B/Aggregator D expose per-champ Arena augment
  tiers (Common/Recommended/Not-Recommended, filterable by tier).
- HOW: An augment-by-champion winrate/tier table joined against the current
  round's offered augment ids.
- RC ALREADY HAVE: PARTIAL. RC RENDERS the 3 augment slots + the current-
  round options and can set augment intent
  (`web/js/panels/champ_select.js:3247`-`:3293`), but the options carry only
  name + a static blurb (`:3265`) - there is NO tier/winrate RATING on them,
  and nothing champion-specific.
- WHERE IT INTEGRATES: enhance `_csvArenaPaneHtml` /
  `_csvWireArenaAugments` to colour/grade each offered augment from an
  augment-tier table (champ-keyed if available), via a new `/api/arena-
  augment-tiers` route.
- EFFORT+RISK: MED. The UI slots + LCU intent wiring exist; the work is the
  augment-tier DATA. There is no augment API mid-game (the augment LCU/:2999
  API is a confirmed dead-end per CLAUDE.md settled item), but the OFFERED
  augment ids ARE in the champ-select session, so a static augment-tier
  table is enough - no OCR needed at pick time. Augment data must be sourced
  (DS engine does not model Arena augments today).
- LIFT VERDICT: MED. Clear gap, the augment pick is a real timed sub-
  decision (bucket 4), UI is half-built, and intent-write already works.
  Blocked only on an augment-tier dataset; once sourced this is a
  high-payoff Arena-specific win.

---

### P7. Ban-phase SUGGESTIONS (Overlay App E power-picks, Aggregator C 3-factor, aggregator A none, Aggregator B meta)

- WHAT: During the ban phase, suggest who to ban. Aggregator C' 3-factor is
  the gold standard: (a) most popular champ in YOUR lane, (b) what has been
  beating YOU in your last ~20 games, (c) a global meta terror in another
  lane.
- HOW: Stats query (role meta) + a personalized loss-history query + a meta
  tier query, minus champs already banned.
- RC ALREADY HAVE: YES, close to Aggregator C. RC's pickban-recs serves a
  suggested-bans grid filtered by role with a STRUGGLE-BAN from the
  operator's own recent loss matchups (`dashboard/routes_pickban.py:683`),
  rendered as a clickable grid that excludes already-banned ids and sets
  ban-intent on click (`web/js/panels/champ_select.js:1006`-`:1043`). RC has
  factor (b) natively and a global-bans fallback; it does not explicitly
  split out (a) lane-meta vs (c) global-terror as labelled reasons.
- WHERE IT INTEGRATES: already integrated; enhancement = label each
  suggested ban with its REASON (your-losses vs lane-meta vs global) the way
  Aggregator C does, which makes the grid self-explanatory in the glance.
- EFFORT+RISK: LOW. Reason labelling is a response-field + render tweak over
  existing infrastructure.
- LIFT VERDICT: LOW (already have core). Reason-labelling is a cheap polish
  that raises the glance value; worth folding into the P2 counter-picks
  slice.

---

### P8. Team COMP / damage-profile balance (Aggregator C, Draft Tool L synergy, Aggregator B/Aggregator D duos)

- WHAT: Surface the team's composition shape - AD/AP damage balance,
  engage/peel, and duo synergy - so the operator can pick to fill a gap.
  Draft Tool L models pairwise duo synergy; Aggregator B/Aggregator D expose duo tier
  lists; Aggregator C frames counters team-aware. NOTE: both Overlay App F and
  Aggregator C LACK an explicit AD/AP damage meter in champ select (a gap RC
  could beat).
- RC ALREADY HAVE: YES, partially ahead. RC's ARAM comp-verdict states the
  enemy damage profile as a FACT (`_enemy_itemization` `dashboard/_champ_
  select_deterministic.py:168`) and names the ally carry/engage
  (`_ally_notes:125`). RC also has a 101.qq-seeded bot+sup duo synergy grid
  (`/api/duo-synergy`, `dashboard/routes_duo_synergy.py:324`) and DS CC-comp
  threat cards (`web/js/panels/champ_select.js:1771`+). What RC lacks: an
  explicit AD/AP balance read of the operator's OWN team during SR draft to
  guide "we need more AP" picks.
- WHERE IT INTEGRATES: extend the deterministic engine to emit an ally
  damage-profile line for SR (not just ARAM), surfaced in the Suggestions
  panel; the champion-tags index (`champion_tags.js`, used at `:651`)
  already classes champs and could seed an AD/AP tally.
- EFFORT+RISK: LOW-MED. The champion classification data exists; this is a
  tally + a one-line render. Risk: low.
- LIFT VERDICT: MED. RC is already AHEAD of Overlay App F/Aggregator C on
  damage-profile facts; extending the ally AD/AP read to SR draft is a
  cheap, defensible (deterministic, not predictive) differentiator that
  fits RC's "facts over predictions" philosophy.

---

### P9. Tier / winrate OVERLAY on champion picks (aggregator A OP-Tier, Aggregator B, Aggregator D, Overlay App E)

- WHAT: Slap a meta tier (S/A/B...) or win-rate badge on the operator's
  pick and on enemy picks, so "is this good right now" is instant.
- HOW: A role-keyed tier table joined against the displayed champion ids.
- RC ALREADY HAVE: PARTIAL. Enemy cells carry CC/burst TAGS
  (`web/js/panels/champ_select.js:651`) and the operator's personal WR-vs
  band, but there is no GLOBAL meta tier/winrate badge on any pick.
- WHERE IT INTEGRATES: a tier badge on each team cell in `_csvRenderTeam`
  (`:539`), fed by a tier table.
- EFFORT+RISK: LOW (render) but gated on a tier DATA source RC does not
  currently maintain (DS engine is build/combat math, not a meta WR tier
  list).
- LIFT VERDICT: LOW. Low user-value-add over RC's existing personalized WR
  band, and needs a meta-tier data source RC lacks. Skip unless a tier feed
  arrives for another reason.

---

## 3. Cross-cutting findings

- DATA SOURCE PATTERN is identical to RC's: every overlay reads the LCU
  client API + process state for the live session, plus its OWN aggregated
  stats API for recommendations (NOT the Live Client `:2999` game API, which
  is in-game only). This matches RC's "Live Client name vs DDragon id" and
  "no positions in champ select" constraints
  (`reference_liveclient_no_positions`). RC's session-read plumbing is
  already as good or better.
- TIMING: nobody publishes a latency number; all are event-on-LCU-session.
  Overlay Platform M apps (aggregator A, Overlay App E, Overlay App F, Aggregator C, Aggregator B) share Overlay Platform M's
  KNOWN intermittent champ-select non-detection bug. RC's direct LCU agent
  (1s push) avoids that failure mode - a real reliability EDGE for RC.
- LEGAL: re-implement PATTERNS against RC's own data (rewind_history.db +
  RC's Riot key) or a public/licensed aggregate. Do NOT scrape a
  competitor's gated overlay or copy their stats DB. Draft Tool L is open-source
  (MIT-style, github.com/draft tool L) so its MATH is studyable as a
  reference, but its dataset is Riot+Aggregator D-derived - use the algorithm,
  source RC's own numbers.
- RC's DIFFERENTIATORS already in place that competitors lack: personalized
  WR-vs-each-enemy band, a deterministic ARAM swap DECISION engine (vs static
  tiers), enemy damage-profile-as-fact, DS CC-comp threat analysis, and a
  per-category build/rune/spell PUSH control. RC is not behind; it is
  differently-shaped (decision + facts + personal history vs global tiers).

---

## 4. Ranked LIFT summary

| # | Pattern | Verdict | One-line rationale |
|---|---|---|---|
| P2 | Live counter-picks vs enemy comp | HIGH | 80% plumbing exists (counters idx + live enemy ids + suggestions panel); bucket-2 decision prompt |
| P6 | Arena augment tier ratings | MED | UI slots + intent-write done; needs augment-tier data; real timed sub-decision |
| P4 | Enemy/ally player scouting table | MED | Overlay App F's moat, legal via RC key; heaviest build, rate-limit-bound; phase it |
| P8 | Ally AD/AP damage-profile (SR) | MED | RC ahead of rivals on facts; cheap deterministic extension to SR |
| P1 | Live per-pick draft win-% | MED | Most-differentiated competitor feat + real SR gap, but gated on a champ-pair dataset |
| P7 | Ban-suggestion reason labels | LOW | Core already shipped; reason labels are cheap polish (fold into P2) |
| P5 | ARAM bench tier annotation | LOW | Decision engine already beats static tiers; per-cell tier optional |
| P3 | Rune/spell/item auto-import | LOW | Fully shipped; only AUTO-toggle + fix RuneWriter first-CS bug |
| P9 | Meta tier badge on picks | LOW | Low add over personal WR band; needs a tier feed RC lacks |

TOP-3 actionable: P2 (counter-picks vs live enemy comp) is the clear first
build - highest payoff, most reuse, wins the glance. P6 (Arena augment
tiers) and P4 (player scouting) are the strongest NEW capabilities, both
data-gated. P8 (SR ally damage profile) is the cheapest defensible
differentiator.

---

## 5. Sources

Aggregator A / Overlay App E:
- https://overlay-platform-m.invalid/app/aggregator-a-electron-app
- https://aggregator-a.invalid/desktop/en/patch-notes
- https://aggregator-a.invalid/desktop/en/overlays
- https://aggregator-a.invalid/lol/modes/aram , https://aggregator-a.invalid/lol/modes/arena , https://aggregator-a.invalid/lol/modes/aram-mayhem
- https://aggregator-a.invalid/help/articles/31092042797849 (aggregator-a auto rune setup)
- https://review-site-z9.invalid/blog/game-analytics/overlay-app-e-gg-overlay-review
- https://1v9.gg/blog/league-of-legends-lol-best-overlay-apps
- https://overlay-app-e.invalid/lol (Pick/Ban power-picks/synergies/counters; 403 to fetch, snippet)
- https://support.overlay-app-e.invalid/hc/en-us/articles/360032708372 (auto-import items/runes/spells; level-10, spells off by default)
- https://overlay-app-e.invalid/lol/tierlist/aram-mayhem , https://overlay-app-e.invalid/lol/arena-augments

Overlay App F / Aggregator C:
- https://overlay-platform-m.invalid/app/overlay-app-f , https://overlay-platform-m.invalid/app/overlay-app-f-learn/
- https://review-site-z12.invalid/blog/article/all-you-need-to-know-about-overlay-app-f-a-complete-guide
- https://third-party-review-site.invalid/overlay-app-f/
- https://mfn.se/a/m-o-b-a-network/... (overlay-app-f standalone Electron, Dec 2025)
- https://aggregator-c.invalid/blog/how-to-use-the-aggregator-c-desktop-app-guide/ (3-factor ban; live counter-picks for you + allies)
- https://aggregator-c.invalid/blog/lol-how-to-use-aggregator-c-overlay-live-companion/ (auto-import; ARAM)
- https://aggregator-c.invalid/blog/lol-how-to-scout-allies/
- https://overlay-platform-m.invalid/forum/t/lol-launcher-champion-select-not-detected/1572 (overlay-platform-m CS non-detect)

Aggregator B / Draft Tool L / Aggregator D:
- an open-source draft-analysis tool (draft tool L) , a third-party code-wiki page for draft tool L's analysis engine
- a third-party comparison of two draft-analysis tools
- an open-source draft-analysis fork (draft tool L)
- https://overlay-platform-m.invalid/app/aggregator-b/ , https://review-site-z10.invalid/u-gg/ , https://aggregator-b.invalid/lol/champions/ahri/counter
- https://aggregator-b.invalid/lol/aram-tier-list , https://aggregator-b.invalid/lol/arena-duo-tier-list , https://aggregator-b.invalid/lol/champions/arena/sett-arena-build
- https://review-site-z9.invalid/blog/champion-guides/counter-picking-guide
- https://aggregator-d.invalid/lol/yasuo/counters/ , https://aggregator-d.invalid/lol/tierlist/ , https://aggregator-d.invalid/lol/tierlist/aram/ , https://aggregator-d.invalid/lol/tierlist/arena/
- https://aggregator-d.invalid/lol/swain/arena/build/
- https://review-site-z9.invalid/blog/game-analytics/aggregator-d-review

Sourcing caveat: aggregator A, overlay app E/support.overlay app E, overlay app F, the
Aggregator C blog, and aggregator B return 403 / JS-render to the automated fetcher;
several competitor feature claims are corroborated via Overlay Platform M store pages
+ independent reviews (Wombo Combo, 1v9, lolnow) rather than read directly
from vendor UI. Draft Tool L (open-source) and Aggregator D (server-rendered) are
the best-grounded. RC repo cites are first-hand from live greps.
