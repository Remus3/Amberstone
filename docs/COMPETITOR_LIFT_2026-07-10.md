# Competitor Lift - Aggregator C Live Matchup + Combat-Style Tags (R89, 2026-07-10)

## Observation provenance

Aggregator C fetches were Cloudflare-blocked to WebFetch (HTTP 403 across every
aggregator C path) and web.archive.org is blocked in this environment. The two
structural pages below were retrieved DIRECTLY via a full-browser render (Apify
apify/rag-web-browser, HTTP 200):

- `https://aggregator-c.invalid/lol/champions/sett/counters` (patch 26.13 / 16.13, Emerald+, Ranked Solo).
- `https://aggregator-c.invalid/lol/champions/sett/build` (same patch).

The GPI axis list was fetched via WebFetch of `https://aggregator-c.invalid/gpi/`.
Live-companion / overlay behavior (pre-game playstyle badges) is from Aggregator C'
own blog copy returned in WebSearch snippets, NOT a rendered capture - it is
labeled "reported" below where the pixels were not seen. Everything tagged
"observed" is from the two HTTP-200 renders. RC citations are grep/read-verified
against the working tree (a verifier gate re-confirmed the build-critical anchors;
one agent line-number was corrected: get_archetype_for is core/archetype_picks.py:592,
not :32).

---

## Feature 1 - Lane-matchup tags

### 1. WHAT (the mechanic / UX)

Aggregator C does NOT put an "Easy / Even / Hard" difficulty word on an individual
lane matchup. Observed, the matchup surface is win-rate-driven plus prose, in
three presentations:

- Counters page ("Sett Top Counters"): a header hex-tier badge (an "A" glyph from
  `hex-tiers/A.svg`), a stat block (Win rate 50.6% / Pick 5.3% / Ban 1.7% /
  Matches 152,718, each with a trend-arrow icon), then a `best picks vs Sett` /
  `worst picks vs Sett` toggle (thumbs up / thumbs down), then a table with
  columns Champion | WR | Matches | Guide. Rows are sorted by the counter
  champion's win rate against Sett (Singed 55.2%, Vayne 54.4%, Gragas 53.1%, ...
  Riven 51.1%), anchored by an "Overall Average 49.4%" baseline row. Every row
  deep-links to a dedicated per-matchup guide page (`/lol/champions/sett/counters/top/vs-singed`).
- Counter-tips block: three prose cards, each with a topic icon - "Laning Against
  Sett", "Strategy VS Sett", "Sett Power Spikes" - roughly three sentences each of
  how-to-play-against advice that inlines the enemy ability icons (Q/W/E/R).
  Example observed text: "Avoid extended trades with Sett early. He has a lot of
  physical damage and will win most auto-attack trades." A like / dislike voting
  control sits on the tips.
- Build page "Sett Matchups Overview": three compact chip-rows - "Weak Against" (6
  champs, each with the champion's own WR e.g. Singed 44.8%), "Strong Against" (6
  champs e.g. Yasuo 55.6%), and "Best Synergy (DUO)" (6 champs with a role icon +
  WR).

So the "tag" is really: a tier badge on the champion, a numeric WR per matchup,
and a best/worst (strong/weak) bucket. The only literal word-tag observed is on
the "related champions" cards (see Feature 2): a difficulty word Easy / Average /
Hard, which is the champion's global learning curve, not a per-matchup rating.

### 2. HOW (under the hood)

Observed: the matchup rows are pre-rendered server-side into the HTML (they
survive a headless render with no client interaction), each carrying win rate,
match count, and a canonical `vs-<slug>` href. The numbers are aggregate win rate
from ranked matches at a rank/region/queue/patch filter (Emerald+, All regions,
Ranked Solo, 16.13 observed as active filter chips). The tip cards are static
curated prose keyed to the champion + role + patch, not generated per-viewer. The
build-page "Weak/Strong Against" chips are the same win-rate table truncated to
top-6 each way and inverted. No numeric "matchup difficulty score" beyond win rate
was present in the DOM.

### 3. HAVE (does RC already do this?)

RC has the compute AND a shipped panel, and it is arguably richer than Aggregator C
on the fight model, thinner on the win-rate table:

- 1v1 fight verdict engine + route: `dashboard/routes_ds_matchup.py` serves
  `GET /api/ds-matchup?champ_a=&champ_b=` returning `verdict` in {all_in, trade,
  back_off, even}, `net_swing` [-1,1], `swing_pct`, `favored`, `pct_a_removed` /
  `pct_b_removed`, `a_can_full_combo` / `b_can_full_combo`, and a `notes` list
  (shape at `dashboard/routes_ds_matchup.py:28-41`).
- Panel: `web/js/panels/ds_matchup.js` renders that as a verdict chip - the label
  map at `ds_matchup.js:56-62` emits "ALL IN" / "TRADE" / "BACK OFF" / "EVEN" -
  plus a swing bar with "% removed" end labels and a notes list ("full combo"
  markers at `ds_matchup.js:162-181`). It mounts at `#csv-sugg-ds-matchup`
  (`web/index.html:2165`), fed the operator's locked champ vs the first committed
  enemy (`ds_matchup.js:239-267`).
- Win-rate matchup data exists elsewhere (the aggregator G/101qq lanes via
  `core/smoothed_rates*.py` and the rewind history DB), but RC's champ-select
  matchup card is a SIMULATION verdict, not a Aggregator C-style win-rate-sorted
  counters table, and RC has NO curated "how to play against" prose taxonomy.

Net: RC HAS a compact matchup verdict tag (a stronger read than a raw WR). RC
LACKS (a) the best/worst win-rate list framing and (b) the three-card prose tip
taxonomy.

### 4. WHERE (concrete RC integration point)

- A compact matchup-difficulty WORD tag alongside the existing verdict: pure panel
  JS in `web/js/panels/ds_matchup.js` (a chip in the `dsm-head` block built at
  `ds_matchup.js:210-215`), fed by the existing `favored` + `swing_pct` fields. No
  engine or route change.
- Best/worst counter framing: a route+data job in `dashboard/routes_ds_matchup.py`
  or a new small route over `core/smoothed_rates*.py` win-rate rows - heavier, and
  it introduces the live-WR dependency.
- The prose tip cards would be a content pipeline (curated or Claude-authored),
  which collides with the "no new Claude dependency" guardrail.

### 5. EFFORT + RISK

- Verdict-word chip over the existing `/api/ds-matchup` payload: presentation-only,
  no new data/dependency, snapshot-testable. LOW effort / LOW risk - but it
  duplicates information the existing verdict chip already conveys.
- Win-rate best/worst counters table: needs the win-rate lane wired into
  champ-select + a new render; MED effort, MED risk (live-source dependency, cache,
  rank/region filters).
- Curated prose tip cards: new content dependency (authoring or Claude); HIGH
  effort, HIGH risk (violates the no-new-Claude-dependency intent + the
  Error-Handling rule if Claude-generated live). Out of scope for a presentation
  lift.

### 6. LIFT verdict

MED. The high-value half (curated lane tips, WR counters list) is a data/content
lift RC deliberately avoids; the genuinely cheap half (a difficulty word chip)
duplicates information RC's verdict chip already conveys, so the marginal
presentation gain is small.

---

## Feature 2 - Player combat-style / playstyle tags

### 1. WHAT (the mechanic / UX)

Two distinct Aggregator C surfaces, and neither is a per-champion "poke / all-in /
kite / dive / burst" tag row:

- Champion CLASS + difficulty tag (observed). On both the counters and build pages,
  the "related champions" cards each render a Riot champion-class icon
  (`champions-classes/fighter.svg`) plus the champion subtitle ("the Berserker")
  plus a one-word difficulty tag - observed "Hard" (Kayn, Riven) and "Average"
  (Olaf, Rek'Sai). This class icon (Fighter / Mage / Marksman / Assassin / Tank /
  Controller / Specialist) is the closest thing to a champion combat-style tag on
  the web app. Aggregator C does NOT expose Riot subclass words (Juggernaut / Diver /
  Skirmisher / Artillery / Burst / Battlemage) as visible tags in what was rendered.
- GPI player playstyle (observed on /gpi/). The Gamer Performance Index is a PLAYER
  radar of eight named axes: Fighting, Farming, Vision, Aggression, Toughness,
  Teamplay, Consistency, Versatility, each scored 0-100 and drawn as a
  "fingerprint" polygon. This is player-behavior, not champion combat-style.
- Pre-game playstyle badges (reported, not rendered here). Aggregator C' blog copy
  describes the live-companion Pre Game marking summoners with colored behavioral
  badges (green positive / red negative / yellow neutral) such as "Fatigue" (6+
  hours) and "Extra Hot Streak" (5-game win streak). These are per-SUMMONER
  tendency tags, again not champion combat-style.

Honest finding: the framing "poke / all-in / scaling / dive / kite / burst" is NOT
literally a Aggregator C web feature. Aggregator C tags champions by Riot class +
learning difficulty, and tags players by GPI axes + behavioral badges.

### 2. HOW (under the hood)

Observed: the class icon is a static asset keyed to Riot's class taxonomy
(`champions-classes/<class>.svg`); the difficulty word is a curated per-champion
attribute rendered inline in the card. The GPI axes (from /gpi/) are described as
ML-derived from the player's own match data, normalized 0-100. The pre-game badges
are (per Aggregator C' text) algorithmic over per-player match stats with a
green/red/yellow polarity - the live DOM was not captured, so the exact badge set
+ thresholds beyond the two named examples are not citable.

### 3. HAVE (does RC already do this?)

RC already has BOTH a champion combat-style classifier and a player GPI radar, and
the champion classifier is wired end-to-end:

- Champion combat-style classification (RC's "class" equivalent):
  `core/archetype_picks.py:58` defines `ARCHETYPES = (carry, bruiser, tank, mage,
  assassin, enchanter)`; `get_archetype_for(champion)` (`core/archetype_picks.py:592`)
  resolves a champion to a primary+secondary archetype from an explicit pick or a
  DDragon-tag default. `core/build_order_precompute.py:270 def archetype_for(champion)`
  is the engine-side classifier. Six dedicated scorers back these
  (`agents/daemon_slayer/__init__.py`).
- Live route: `dashboard/routes_archetype.py` serves
  `GET /api/cs-archetype-pick?champion=<id>` returning the resolved archetype plus
  the enum metadata (`routes_archetype.py:47-70`).
- Champion "shape" (richer than a single class tag): `web/js/panels/ds_profile.js`
  renders EIGHT labelled axes per champion - Mobility / Sustain / Scaling /
  Waveclear / Range / Zone / Objective / Duel - with HIGH/MED/LOW tier tints
  (`ds_profile.js:19-26`). Mounts at `#csv-sugg-ds-profile` (`web/index.html:2186`).
- Build-variant badges (a compact combat-style-ish chip row already):
  `web/js/panels/champ_select.js:1252-1264` maps variant keys to colored badges -
  on-hit, crit, ap-burst, tank/bruiser, lethality-poke, adc-crit, support.
- Player GPI radar (near-1:1 with Aggregator C GPI): `web/js/panels/player_gpi.js`
  renders an eight-spoke radar over aggression / farming / vision / objectives /
  survival / tempo / versatility / consistency from `GET /api/player-profile`.
- Archetype-mismatch nudge chip: `core/archetype_mismatch.py` renders a small chip
  when a buy contradicts the archetype pick.

What RC does NOT have: the resolved archetype primary is used internally (scorer
routing, build-variant selection, the DS cache key at `champ_select.js:1399`), and
the picker was removed (LEDGER 823), so there is NO read-only one-word combat-style
chip (CARRY / BRUISER / TANK / MAGE / ASSASSIN / ENCHANTER) rendered per champion
the way Aggregator C stamps a class icon on each card.

### 4. WHERE (concrete RC integration point)

- Smallest: a read-only archetype tag chip in champ-select, rendered by
  `web/js/panels/champ_select.js` from the archetype value it ALREADY caches in
  `_CSV_ARCH_CACHE[champ].primary` (`champ_select.js:1399`, resolver
  `_csvResolveArchetype` at `champ_select.js:2179`). Zero backend change - the data
  is already client-side.
- Cleaner-home alternative: add the chip to the `ds_profile.js` header, fed by a
  new `archetype` field on `/api/ds-profile` (one trivial backend field).

### 5. EFFORT + RISK

- Read-only archetype chip from the existing cached primary (frontend-only in
  `champ_select.js`): presentation-only over already-computed data, no new
  Riot/Claude dependency, no schema lift, snapshot-testable. LOW effort / LOW risk.
- Pre-game behavioral player badges (Fatigue / Hot Streak): would need per-summoner
  history aggregation RC does not compute today; MED-HIGH effort, out of the
  "presentation over existing DS math" lane.

### 6. LIFT verdict

HIGH. RC owns all the substrate (archetype classifier, live route, cached client
value, six scorers) and merely fails to render the one-word tag; surfacing it is a
small, testable, dependency-free presentation add that directly matches
Aggregator C' class-tag glanceability.

---

## Recommendation

There is one HIGH-lift, LOW-risk, presentation-only slice buildable in this run,
and it is Feature 2, not Feature 1: a read-only combat-style tag chip on the
champ-select My Pick card, showing the champion's archetype word (CARRY / BRUISER /
TANK / MAGE / ASSASSIN / ENCHANTER) sourced from the value already resolved + cached
at `champ_select.js:1399` (source of truth `core/archetype_picks.get_archetype_for`,
route `/api/cs-archetype-pick`), reusing the existing `.csv-build-badge` tint
family. No backend change, no Riot/Claude dependency, no new math, snapshot-testable.

Deferred to BACKLOG (NOT built in-run): the Feature-1 win-rate "best/worst counters"
list (needs the live-WR lane wired into champ-select - a data dependency, MED risk)
and the curated "how to play against" prose tip cards (a content/Claude dependency
that collides with the no-new-Claude-dependency + Error-Handling guardrails). RC's
existing `/api/ds-matchup` verdict chip already covers the cheap, dependency-free
half of Feature 1.

---

## R89 build outcome (this run)

SHIPPED the recommended Feature-2 slice. The read-only combat-style archetype chip
now renders on the champ-select My Pick card (SR + ARAM path), below the champion
name, fed by `_csvResolveArchetype(myName).key`.

- New pure module `web/js/panels/archetype_chip.js` - `archetypeChipHtml(primary)`
  maps the resolved archetype to an existing `.csv-build-badge` tint (carry->crit,
  bruiser/tank->tank, mage->ap, assassin->lethality, enchanter->support, unknown->
  default), uppercases + escapes the label, returns "" fail-soft on empty.
- `web/js/panels/champ_select.js` - imports + interpolates the chip next to
  `#csv-mypick-name`.
- `web/css/panels/champ_select_view.css` - one compact `.csv-archetype-chip` rule
  (width:auto override of the 200px build-badge bar; font-size inherits --fs-xs).
  No new CSS file, so bundle parity holds; asset-hash auto-reload (ADR-008), no RC
  restart.
- Tests: `web/js/panels/archetype_chip.test.mjs` (node --test, 7/7) +
  `tests/snapshot_panels/test_champ_select_archetype_chip.py` (CI contract, 7/7) +
  a `/api/cs-archetype-pick` fixture in `tests/snapshot_panels/conftest.py` so the
  headless render exercises the chip. Full snapshot_panels suite 359/359.
- Visual proof: `tests/snapshot_panels/screenshots/champ-select_aram.png` shows the
  compact "CARRY" chip under "Jinx". 5-phase UI audit (STRUCTURE / TYPOGRAPHY /
  HIT-TARGETS / ASCII / HIERARCHY) passed - the one MUST-FIX (200px build-badge
  width) was resolved in-slice via the compact override.

FUTURE (deferred): Arena My Pick pane parity for the chip (it uses a separate
`_csvArenaPaneHtml` layout); Feature-1 WR counters list + prose tips (BACKLOG).
