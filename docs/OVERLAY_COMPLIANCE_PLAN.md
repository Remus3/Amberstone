# Overlay Platform M submission compliance plan (drafted 2026-08-11)

Status: PLAN ONLY. Nothing here is executed. Sources are the Overlay Platform M dev docs
(`overlay platform M developer docs` Riot compliance + project roadmap + framework overview) and
the app-proposal form itself, read 2026-08-11. Repo claims below carry file
citations and were greped this session.

## 0. Framework verdict: ow-electron (not Overlay Platform M Native)

Decision is forced by RC's shape, not preference:

| Need | Native (CEF wrapper) | ow-electron |
|---|---|---|
| Existing Electron shell (`rc-shell/package.json` v0.4.0, electron 33, electron-builder 26) | rewrite from zero | reuse |
| Native node modules / local sidecar process (DS `:8860`, supervisor, vision server) | no story | supported ("full support for native node.js modules") |
| Existing web UI served from an origin (`web/js/main.js` + panels) | port to OW window model | loads as-is |
| Overlay Platform M ads + Tebex subs + GEP + in-game overlay | yes | yes |

Both frameworks get the ads stack, overlay, analytics, installer. The
differentiator is node-native + the sunk Electron work. **Pick ow-electron.**
Declare it on the proposal form field "framework".

## 1. Two approvals, not one

1. **Riot Games 3rd-party application process** (developer.riotgames.com portal).
   Required BEFORE Overlay Platform M will host a public app.
2. **Overlay Platform M DevRel** proposal form -> whitelisting -> Phase 2 dev -> store review.

No published timeline on either. Assume the Riot leg is the long pole and start it first.

## 1b. STATUS as of 2026-08-11

Landed this session, all verified green (RC `tests/` 18470 passed / 104 skipped
/ 0 failed; DS `agents/daemon_slayer` 10495 passed / 83 skipped / 0 failed;
`tools/ds_share_sync.py --check` in sync at engine 1.277.0, 533 files):

| Item | State | Note |
|---|---|---|
| B1 enemy summoner-spell tracker | **DONE - deleted** | Panel, backend producer, mounts, CSS, 4 test files. |
| B2 summoner + ultimate cooldown ledger | **DONE - deleted** | Panel, `core/summoner_cooldowns.py`, `dashboard/_state_cooldowns.py`, pane, 8 threading sites. `summoner_cooldowns` stays on `/api/state` as a permanent null so consumers degrade. |
| B3 power-spike cue | **CORRECTED 2026-08-12 - the deletion was real but INCOMPLETE; closed for the live surface by B4-b** | `spike_cue.js` + CSS + registry entry + 2 test files went, and `spike_curve` / `spike_markers` survive as pre/post-game analysis. But the spike NOTIFICATION lived on a second mount and kept firing for 1 more day. See the corrected row below. |
| B4 coach imperatives | **BUILT 2026-08-12 (a-e); only B4-f is open** | See 6c + `docs/OVERLAY_B4_DESIGN.md`. Silent branch capture in-game, review post-game. |
| B5 champ-select names | **DONE - obfuscated at the producer** | `lcu/champ_select_shape._obfuscated_name`, positional so it is identical on every client. 3 mock fixtures updated. |
| B6 TFT augment stats | **REFUTED - no action** | See the corrected row below. |
| B7 Riot Brawl exclusion | **DONE** | See the corrected row below. |
| B8 vision / OCR capture | OPEN | DevRel question. |
| B9 LCU | OPEN | Declare in the Riot application. |
| B10 cooldown-watch (found mid-work) | **DONE - deleted, then rebuilt compliant** | See B10 below. |

Every removal left an INVERTED guard test behind rather than a hole: the old
cases asserted the banned surface must exist, and now assert it must stay gone.
Reinstating any of them turns a test red.

One frozen-file edit was made with explicit operator approval on 2026-08-11:
`core/game_snapshot.py`, for the B7 gate. It is the only place every mode
consumer routes through, so the gate cannot live anywhere else.

## 2. Hard blockers in RC today (must be removed or re-scoped)

Each row is a measured surface, not a guess.

| # | RC surface | Rule broken | Required action |
|---|---|---|---|
| B1 | `rc-shell/test/enemy_spells_tracker.test.js` + `web/js/panels/enemy_spells_timer.test.mjs` (enemy summoner-spell tracker) | "Tracking of enemy summoner spells cooldowns" | DELETE the enemy-side tracker entirely. No manual-click carve-out is documented; do not assume one. |
| B2 | `web/js/panels/cd_ledger.js` + `core/summoner_cooldowns.py` + `dashboard/_state_cooldowns.py` - per-player summ + ULT cooldown ledger for all 10 players | enemy summ cooldowns AND "use of Ultimate timers is strictly forbidden" | Drop the `ult` block for every player (ally too - the ban is unqualified). Restrict `summs` rows to own party only. |
| B3 | `web/js/panels/spike_cue.js` - fires "the instant the operator crosses an ULTIMATE power spike" | "Notifications that alert players when a power spike hits" | **CORRECTED 2026-08-12 - see the B3 row below. The filed fix was right and INCOMPLETE: deleting the named panel did not remove the artefact.** |
| B4 | `web/js/panels/right_now.js` - "immediate coaching actions"; `coach.action` / `coach.immediate` / `coach.fight_rule`; `coaches/voice_coach.py` | "Notifications that dictate player action based on the current game state" | Highest-cost item. In-game overlay must stop issuing imperatives. Options: (a) move the whole coach to pre-game + post-game surfaces, (b) reword to non-directive descriptive state. (a) is defensible; (b) is a judgement call a reviewer can reject. |
| B5 | `web/js/panels/champ_select.js` + mocks under `web/data/ui_mock/champ_select_*.json` render summoner names | non-party names must be "Ally 1..5", consistent across clients | Obfuscate at the producer, not the renderer, so every consumer inherits it. Loading screen is exempt; champ select is not. |
| B6 | ~~TFT augment win/placement data~~ | TFT: no Legend win rates, no Augment win rates, no Augment average placements | **REFUTED 2026-08-11 - this row was WRONG when filed. Measured: `coaches/tft_coach.py` displays none of the three. Its `placement` hits are the operator's OWN board and unit placement. `core/augment_external_source.py` is an ARENA / Mayhem win-rate prior, and Riot's augment-stats ban is scoped to Teamfight Tactics, so it does not reach Arena. NO ACTION. Acting on the original row would have deleted a working Arena feature under a misapplied rule.** |
| B7 | Riot "Brawl" mode + League Classic: no data aggregation or display | RC's `MODE_BRAWL` is a NAME COLLISION (it covers the ROTATING modes - URF / ARURF / ONEFORALL / GAMEMODEX / NEXUSBLITZ), NOT Riot's Brawl | **DONE 2026-08-11, and it was worse than a naming problem.** `mode_from_game_mode_string` matched none of its branches on `"BRAWL"`, so a real Brawl game fell through to the `MODE_SR` default and was coached as a normal game - a live routing bug. Meanwhile three OTHER sites matched substring `"BRAWL"` and therefore matched ONLY Riot Brawl, never RC's rotating modes. Fixed with `FORBIDDEN_GAME_MODES` + `is_forbidden_game_mode()` + `MODE_UNSUPPORTED` in `core/game_snapshot.py`, checked FIRST so nothing can reach the SR default; `MODE_UNSUPPORTED` is absent from `MODE_COACH_MAP` so no coach loads. Second fences at `core/archetype_mismatch.py`, `dashboard/routes_adaptive_summoners.py` (dropped the `"BRAWL": "brawl"` aggregation key) and `coaches/brawl_coach.py`. Prefix-matched, so `BRAWL_RANKED` is caught too. |
| B10 | `dashboard/routes_cooldown_watch.py` + `agents/daemon_slayer/cooldown_watch.py` - `/api/cooldown-watch`, per-enemy "highest-threat hard-CC ability + its max-rank base cooldown" | "Tracking of enemy ability cooldowns" | **DONE 2026-08-11 - deleted, then REBUILT compliant.** Found while mapping B2; its frontend had already been deleted in 2026-07 (LEDGER 765) but the route and engine module survived. It also had a hidden second consumer: `core/laning_scenario_precompute.py` was joining enemy CC to enemy cooldowns into the precomputed laning tables, so the banned data was arriving by a second road. See section 6d for the replacement. |
| B8 | `modes/shared_vision.py` + `screen_agent.py` + `:8889` frame relay (OCR / Sonnet vision on captured frames) | Not named in the Riot list, but it is out-of-band game capture that a reviewer will scrutinise, and Overlay Platform M expects capture through its own APIs | Re-route any retained capture to the Overlay Platform M capture API, or drop the in-game vision path and keep OCR for out-of-game surfaces only. Raise it with DevRel explicitly rather than shipping it silently. |
| B9 | LCU lockfile client (`lcu/lcu_client.py`, RC-LCUAgent) | Not banned in the Overlay Platform M doc, but Riot's 3rd-party policy governs LCU use | Declare LCU usage in the Riot application. Do not assume tolerance. |

## 3. Monetization rework

- Third-party monetization is prohibited. Only Overlay Platform M Ads and/or Tebex subs.
- Ads: 70 percent to the developer. Tebex subs: 15 percent total fee (10 Overlay Platform M + 5 Tebex).
- **No ads during active gameplay.** Loading screens, post-match, menus only.
- Consequence for RC: the live Haiku spend has no third-party billing route. The
  Haiku-to-ZERO precompute program stops being an optimisation and becomes the
  unit-economics precondition. Any residual per-user LLM cost must fit inside
  70 percent of ad revenue or a Tebex subscription tier.

## 4. Product / store requirements

- Public app (not private); Valorant private apps are no longer accepted at all.
- At least one desktop window indicating the app is running.
- Overlay must not cover or interfere with the game UI.
- Original code, design and ideas; do not clone a competitor's UI/UX.
- Disclaimer string required: "Riot Commander isn't endorsed by Riot Games ..." (use Riot's current exact wording).
- No Riot logo.
- Overlay Platform M manually curates and performance-tests every app.

## 5. Proposal-form answers to prepare

First/last name, email, company, country, app name, website, description
(50-1400 chars), framework = ow-electron, supported games (League of Legends,
plus TFT/Arena if kept), category (Guides & Trainers + Stats + Performance
Tracker are the closest of the 20), monetization (Overlay Platform M Ads, optionally
Tebex), and acceptance of Developer Terms + Monetization Terms.

## 6. Suggested order of work

1. Start the Riot 3rd-party application (longest lead, gates everything).
2. Land B1 + B2 + B5 (deletions and an obfuscation at the producer - cheap, unambiguous).
3. Decide B4 (coach directive scope). This is an operator decision, not an engineering one, and it defines what the app IS.
4. B3, B6, B7 cleanup + documentation.
5. Raise B8 + B9 with DevRel in writing before building against either.
6. Port `rc-shell` to ow-electron; wire Overlay Platform M ads with the no-ads-in-gameplay gate.
7. Land the Haiku-to-ZERO precompute far enough that residual LLM cost fits ad revenue.
8. Submit the proposal form.

## 6b. Riot-side blockers found 2026-08-11 (NEW - not in the Overlay Platform M list)

Sourced from developer.riotgames.com/policies/general + the Legal Jibber Jabber policy.

| # | Finding | Action |
|---|---|---|
| N1 | **The product name "Riot Commander" uses Riot's trademark.** Policy: no Riot logos or trademarks anywhere in the project, website, advertising or publications without a written license; no domain names or social accounts using them. | RENAME. Blocks the Riot application itself, so it is the first item, ahead of any code. Scope: repo dir, `rc-shell` productName + installer + updater feed, GitHub repo + release channels, cert CN / MagicDNS `legion-rc`, docs, dashboard title, any future domain, and `docs/HEXCORE.html` + `docs/HEXCORE_offline.html` (Hextech / Hexcore is Riot IP from Arcane). Ties into memory `project_pre_release_name_scrub`. |
| N1a | **"Daemon Slayer" is NOT usable as the public product name.** `DEMON SLAYER KIMETSU NO YAIBA` is registered to Shueisha covering downloadable and recorded computer game software; "Daemon" is a homophone of "Demon" in the same goods class, and Aniplex/Shueisha enforce actively. | Keep Daemon Slayer as the INTERNAL engine codename only - it never appears on a store listing. Not a legal opinion; get one before betting the name. Domain probe 2026-08-11 (NS lookup): every single-word `.gg` is taken (sigil, familiar, grimoire, pact, conjure, auspex, pythia, cadence, coldiron). Available at probe time: `saltcircle.gg` + `.app`, `lanewarden.gg` + `.app`, `lanecommander.gg` + `.app`, `sidelane.gg`, `laneoracle.gg`, `laneaugur.gg`, `chalkline.gg`, `ironcircle.gg`, `reliquary.gg`. Availability rots - re-probe before committing. |
| N2 | "Cannot replace official ranking systems (no MMR/ELO calculators)" | Audit `web/js/panels/draft_elo.js` and any RC-computed rating. A draft-strength heuristic is probably fine; anything presented as a player MMR/ELO is not. |
| N3 | "Cannot de-anonymize players" | Audit player lookup / history surfaces for anything that links accounts or infers identity. |
| N4 | Production key needs a public website, Terms of Service and Privacy Policy, and demonstrable user flows | None of the three exist today. They are deliverables, not paperwork. |
| N5 | One product per production key; RC runs on a Personal key today | Register the product, then migrate off the personal key. |
| N6 | Must offer a free tier; content must be "transformative" | Satisfied by the ad-supported free build. State the transformative claim explicitly in the application (DS computes original DPS math, it does not restate Riot data). |
| N7 | Required disclaimer, exact wording | "<product> isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties." Must be readily visible. |
| N8 | Approved assets only: Data Dragon, Press Kits, TFT/LOR asset packs | Audit every image and icon shipped in `web/` and `rc-shell/` for provenance. |

### Registration path (operator action, cannot be automated)

Developer Portal -> Register Product -> choose personal vs larger-scale ->
online form -> product verification -> DevRel review -> approval unlocks
production rate limits. Requires a Riot account login and a form submission,
so the click is the operator's; everything feeding it is prepared here.

## 6c. B4 resolution (operator decision 2026-08-11)

Live coaching moves to pre-game and post-game. The retained in-game behaviour is
**silent capture of decision branch points**: RC computes the multi-path choice
set at each decision moment DURING the game, writes it to the match record, and
renders NOTHING live. Post-game review then replays "here is the branch you were
at, here is what each path was worth, here is what you chose".

This is compliant on a plain reading: the banned artefact is a NOTIFICATION that
dictates action or announces a power spike. Computation and logging are neither.
The compliance boundary is the RENDERER, not the engine - so the in-game overlay
must not surface the branch set, the recommended path, or any spike edge while
the game is live. Confirm with DevRel before shipping, since a reviewer sees the
UI and not the design intent.

Side effect: this is the same precompute the Haiku-to-ZERO program needs, so the
compliance path and the cost path converge rather than compete.

## 6b2. Product-name shortlist (operator-kept, 2026-08-11)

The rename is N1 and it gates the Riot application, so the shortlist lives here
rather than in a scratch file. Constraint set: no Riot IP (Riot, League, LoL,
Rift, Summoner, Hextech / Hexcore, champion names), no confusable-with-Demon-
Slayer construction, and not "closely resembling Riot's games or products".

**OPERATOR PICK 2026-08-11: "Reliquary" (product) + "Daemon Slayer" (engine).**
The pairing is right - a reliquary is the vessel that holds the dangerous thing.
**But Reliquary probed BADLY and the finding is recorded here before anything is
renamed:**

- **Domains:** only `reliquary.gg` is free. `.app`, `.com`, `.io`, `.dev`,
  `getreliquary.com` and `reliquaryapp.com` are ALL registered. Contrast Salt
  Circle, which has `.gg` AND `.app`.
- **USPTO:** EAM Corporation holds `RELIQUARY OF SOULS` and `THE RELIQUARY
  PROJECT`, both registered for downloadable computer game software - the same
  class RC would file in. Neither is the bare word, and a composite mark is
  weaker against a common English noun, but the field is not clear.
- **Prior use, and this is the practical problem rather than the legal one:**
  "Reliquary" / "Reliquary Reincarnations" is a Minecraft mod by P3pp3rF1y with
  **over 100 million CurseForge downloads**. That is the SAME ECOSYSTEM RC would
  ship into - game mods and companion apps - so the collision is with an
  audience RC shares, not a distant industry.

Not a legal opinion. The honest read is that Reliquary is usable but contested,
where Salt Circle is clear on every axis probed. Operator decision pending.

**Reliquary-family alternatives (probed 2026-08-11).** Two ways out: keep the
WORD in a distinct two-word mark, or keep the CONCEPT with a cleaner word.

Keep the word - all `.gg` AND `.app` free, and a two-word mark clears the
Minecraft-mod collision that a bare "Reliquary" walks into:

- **Iron Reliquary**, **Hollow Reliquary**, **Vigil Reliquary**
- also free at `.gg`: Ash Reliquary, Bound Reliquary, Salt Reliquary
- **AVOID "Black Reliquary"** - that is an existing Darkest Dungeon mod.

Keep the concept. The strongest of these is not a generic container at all - a
**monstrance / ostensorium is a reliquary whose entire purpose is to DISPLAY
what is inside it** (from *ostendere*, "to show"). For a product whose whole job
is to surface what the Daemon Slayer engine computes, that is exact rather than
merely thematic.

| Name | `.gg` | `.app` | Note |
|---|---|---|---|
| **Ostensorium** | free | free | "the thing that shows". Zero software or game products found under it. Five syllables is the only cost. |
| **Monstrance** | free | taken | Same meaning, far more pronounceable. |
| **Phylactery** | free | free | The vessel that holds a soul or power - gamer-legible via the D&D lich, and the tightest fit with a "Daemon Slayer" engine specifically. |
| **Feretory** | free | free | A portable reliquary. Obscure, clean, easy to say. |
| **Halidom** | free | free | A holy relic, or the sanctuary holding it. |
| Chasse / Theca / Pyxis / Ossuary | free | taken | All genuine reliquary vocabulary; `.app` gone on each. |
| Aumbry, Scrinium, Tabernacle | free | not probed | Aumbry is the cupboard for sacred vessels; scrinium the Roman scroll-box. |

Searched for prior software / game use on Monstrance, Ostensorium and Feretory:
**none found** - the terms return liturgical-supply commerce only.

### 6b2.1 Name usability deep-dive (2026-08-11)

Operator framing, which is the correct test: **aggregator B / aggregator A / Aggregator C all
win because they are easy to say, spell and remember.** Scored the three
finalists against that bar.

**The mechanism, from the literature.** Pronounceability drives *processing
fluency*, and fluency is not a nicety - Song and Schwarz (2009) found
hard-to-pronounce names were rated as **riskier** (more harmful food additives,
more dangerous amusement rides) than easy ones describing the same thing, and
simple names were recalled correctly far more often. A name a user cannot say
is a name they will not repeat, and word of mouth is exactly how a League
companion app spreads ("just get aggregator A").

**What the successful names actually share.** It is NOT brevity alone:

| Name | Syllables | Why it works |
|---|---|---|
| aggregator A / aggregator B | 2 | trivially short, zero spelling ambiguity |
| Overlay App E | 1-2 | common word |
| Overlay Platform M | 2 | compound of two common words |
| **Aggregator C** | **4** | **transparent blend - moba + analytics** |
| **Overlay App F** | **4** | **transparent pun - poro + professor** |

So length is survivable; **opacity is not**. Aggregator C is four syllables and
still works because a listener reconstructs the spelling from parts they
already know. That is the property to hunt for.

**All three finalists are long AND opaque - the one quadrant with no winners.**

| | Phylactery | Ostensorium | Feretory |
|---|---|---|---|
| Syllables | 4 (fi-LAK-ter-ee) | 5 (os-ten-SOR-ee-um) | 4 (FER-i-tor-ee) |
| Spell from hearing | **FAILS** - `PH` for /f/; users type "filactery". Also -ery/-ary. | Mostly phonetic, but 11 letters | **FAILS** - heard as "ferretory" / "feritory"; the "ferret" mishearing is near-certain |
| Say from reading | **Contested stress** - dictionaries give fi-LAK-ter-ee, D&D players often say FIL-ak-ter-ee. A name whose own audience splits on stress. | Determinate | Determinate |
| Familiarity anchor | **Strongest** - the D&D lich phylactery is widely known to gamers | **None** | None |
| Confusion neighbours | few | sanatorium, auditorium, **crematorium** | refectory, territory, factory |
| Morphologically transparent | no | no (Latin *ostendere*) | no |
| Search / typo tolerance | poor - a mistyped `f` finds nothing | fair | poor |

Ranking within the set: **Phylactery > Feretory > Ostensorium.** Phylactery has
the only real recognition anchor; Ostensorium has none and is the hardest to
repeat. But none of the three clears the aggregator A bar, and the `PH` on the front of
the best one is a direct hit on discoverability.

**The structural argument, which decides it.** RC already has a rich, esoteric
name doing the flavour work: **Daemon Slayer**, internal, never on a listing.
The public name's job is the OPPOSITE job - be repeatable. Spending the
esoteric budget twice leaves nothing carrying the plain-spoken half. The pairing
works best as **evocative engine + plain vessel**, not two obscure Latinates.

**What clears the bar while keeping the containment concept:**

| Name | Syllables | Properties |
|---|---|---|
| **Wardstone** | 2 | two common words, spells itself, one pronunciation, `.gg` free |
| **Salt Circle** | 3 | same, plus `.gg` AND `.app` free |
| **Iron Circle** | 3 | same |

Each pairs with a Daemon Slayer engine exactly as well as Reliquary did - the
vessel that holds the dangerous thing - at half the syllables and none of the
spelling traps.

### 6b2.2 PHYLACTERY - DISQUALIFYING FINDING (2026-08-11)

**"Phylactery" is the standard English word for TEFILLIN**, the small leather
cases holding Torah texts that observant Jewish men wear on the arm and forehead
at morning prayer. That is not an archaic sense - it is the ONLY sense in which
the word is still in live use outside fantasy gaming.

Consequences, all verifiable:

- A rabbi has publicly characterised the D&D usage - an undead parasite draining
  life through a "phylactery" - as antisemitic.
- **Paizo already removed the word** from Pathfinder 2nd Edition, replacing it
  with "soul cage". A major publisher in the same genre made this call
  deliberately.
- The gaming sense is therefore a **decaying** recognition anchor: the argument
  for the name rests on familiarity that its own source publishers are retiring.

A commercial product named Phylactery is naming itself after a sacred object of
a living religion, on the strength of a pop-culture association the industry is
actively walking away from. **DISQUALIFIED - do not revisit.** The
concept (a vessel that binds a powerful entity) is fine and is exactly the
Reliquary idea; this particular word is the problem.

### 6b2.3 The Wardstone objection is CORRECT (operator, 2026-08-11)

Operator observation, upheld: **"ward" names a mechanic RC cannot measure**
beyond vision score, so Wardstone promises ward / vision analytics the product
does not deliver. A name should not write a cheque the engine cannot cash.
Wardstone is withdrawn on those grounds - but note this argues against the WORD,
not against plain compounds generally. **Salt Circle** and **Iron Circle** carry
no mechanical implication at all and keep the containment concept intact.

### 6b2.4 The screen that kills most candidates: LEAGUE VOCABULARY COLLISION

The operator's Wardstone objection generalises into a screen nobody had been
applying, and it eliminates most of the shortlist including BOTH of my own
recommendations. **This market has a dense reserved vocabulary. A name that
collides with a rank, an item, a rune or a piece of player slang inherits that
meaning whether you want it or not.**

| Candidate | Collision | Verdict |
|---|---|---|
| Wardstone | "ward" names a mechanic RC cannot measure past vision score | WITHDRAWN (operator) |
| **Salt Circle** | **"salt" / "salty" is THE gaming word for tilt and bitterness.** A League coaching product called Salt Circle reads as "the tilted-players circle". Also conceptually wrong under the refined criterion: a salt circle is a BARRIER that excludes, not a vessel that BINDS. | **WITHDRAWN** |
| **Iron Circle** | **Iron is the LOWEST RANK in League.** An "Iron" product name says bottom-tier to every player who sees it. | **WITHDRAWN** |
| Keystone | a Riot rune-system term | screened out |
| Crucible | Mikael's Crucible is a League item; also Destiny's PvP mode. `.gg` taken | screened out |
| Vessel | Senna is "the Vessel" in League lore. `.gg` taken | screened out |
| Bindstone | an MMO respawn mechanic (WoW, Vanguard, Rise of Agon), an existing game (`bindstone.online`), AND an existing companion app ("Bindstone - Soulbound: Online Companion") | **DISQUALIFIED** |

### 6b2.5 Binding-vessel candidates that survive every screen

Screens applied: no live-religious-object referent (the Phylactery lesson), no
League vocabulary collision, no existing game or software product, spells itself
from hearing, one obvious pronunciation, domains free.

| Name | Syl | `.gg` | `.app` | Read |
|---|---|---|---|---|
| **Sealstone** | 2 | free | free | the stone that seals something in. Spells itself, single pronunciation, no collision found. Strongest on the mechanics. |
| **Anchorhold** | 3 | free | taken | the cell an anchorite is walled into for life - a binding vessel for a person. Clean, no products found. |
| **Fetter** | 2 | free | not probed | a chain that binds. Shortest, plainest, unambiguous. Carries an imprisonment connotation, which is the concept but reads dark. |
| **Brazen Vessel** | 4 | free | not probed | Solomon bound seventy-two demons in a brass vessel - THE binding-vessel archetype in Western occultism, and the closest literal match to a "Daemon Slayer" engine. Cost is four syllables and two words. |
| Bindery | 3 | free | taken | a place where binding happens, but the dominant real-world sense is bookbinding - reads as a print shop. |

### 6b2.6 Deep dive: Sealstone vs Brazen Vessel (2026-08-11)

**SEALSTONE - survives, but it is bland and slightly off-concept.**

- No company, product or trademark owns it. Clean field. `.gg`, `.app` and `.io`
  all free.
- **But it is a recurring generic in-game item noun**: "Sealstone of Water"
  (Xenoblade Chronicles 2), "Seal Stone" (MapleStory), "Forest Seal Stone"
  (Pokemon TCG). Same CLASS of problem that disqualified Bindstone, one notch
  milder - no product to compete with, but the name feels unownable and carries
  an SEO tax against those item queries.
- **Conceptual defect.** A real sealstone - the Met has a collection, and
  Chinese/Japanese carving stock is sold under the name - is an engraved stamp.
  It MARKS and AUTHENTICATES. It does not bind. The "seal" that binds (sealed
  away) is a DIFFERENT SENSE of the word, so for anyone who knows the object the
  pun resolves the wrong way.
- Cold surface read for a lay listener is the marine mammal.
- Verdict: nothing kills it, nothing distinguishes it. The safe pick.

**BRAZEN VESSEL - the imagery is even better than claimed, and the head word
now means the wrong thing.**

- **Confirmed and stronger than stated:** the Lemegeton's seventy-two spirits
  are canonically titled **"the Spirits of the Brazen Vessel"**. Solomon
  imprisoned them in a brass vessel and cast it into the sea; Babylonians broke
  it open expecting treasure and released them. This is a real named thing, not
  a construction - the tightest possible literal fit for a Daemon Slayer engine.
- **The killer: "brazen" has semantically drifted.** Its dominant modern sense
  is shameless / impudent ("a brazen disregard for the rules"); the brass sense
  is the archaic root. To a modern audience the name reads **"Shameless
  Vessel"**. Merriam-Webster and the OED both carry the drift.
- "Brazen Bull" - an ancient torture device - is adjacent unpleasant imagery.
- Some tellings make the seventy-two **jinn** rather than demons, and jinn are
  part of live Islamic belief. Much weaker than the Phylactery problem (a brazen
  vessel is not itself a sacred object, and the Solomonic material is a Western
  grimoire tradition) but the same family of risk, stated rather than buried.
- "Vessel" is also Senna's League epithet - the collision already screened at
  6b2.4 applies to the second word.
- Four syllables, two words: fails the operator's own ease test.
- Verdict: best imagery in the whole exercise, worst ergonomics. **Better as an
  internal codename or a release name than as the product name** - the same slot
  Daemon Slayer already occupies successfully.

### 6b2.7 Alternatives, same treatment

**AMBERSTONE - the strongest conceptual fit found in this exercise.**
Amber binds an insect permanently, preserves it, AND displays it. That is the
binding property and the monstrance display property in one object, which is
what the product actually does with the engine's output. 3 syllables, spells
itself from hearing, one pronunciation, no League vocabulary collision, `.gg`
and `.app` both free, no gaming trademark found.
*Adversarial:* two non-gaming companies exist (Amberstone Ventures, a VC;
Amberstone Digital, a South African software consultancy) and hold
`amberstone.com` - dilution outside `.gg`, not a conflict inside it. "Amber" is
warm and soft, which may read insufficiently sharp for a combat-math product.
US audiences carry an Amber Alert association.

**OUBLIETTE - fails the operator's own criteria, hard.** `.gg` + `.app` free
and the concept is strong (a hole you drop someone into and forget), but:
spelling trap (`ou-`, double `t`, `-ette`), French pronunciation (oo-blee-ET),
and the semantics are about FORGETTING - exactly wrong for a product whose value
is retained knowledge. REJECTED.

**GAOLSTONE - rejected on sight.** "Gaol" is the British spelling of jail. A
pure spelling trap.

**VAULTSTONE / AMBERVAULT / SEALWARD / BINDWELL** - all `.gg` free (and
`.app` free for the first two), all clean, all generic. Fallbacks, not picks.

### 6b2.8 The soul-container field, swept (2026-08-11)

Operator question: what OTHER words mean "a magical container holding a life
force or soul", indifferent to the physical form? Swept the field. **The answer
that matters: the trope is explicitly form-indifferent, and amber is one of its
canonical forms - so Amberstone is not a departure from the phylactery idea, it
IS that idea in a form with no baggage.**

Folklore research: the canonical trope name is **Soul Jar**, and "a soul jar is
not necessarily a jar; common examples in mythology and fairy tales are
paintings, **gems**, still beating hearts, eggs, or trees". It recurs in Vodun,
Zuni and Egyptian mysticism; Koschei the Deathless hid his soul in an egg
(nested inside a duck, a hare, a chest, a tree); the Irish "The Soul Cages"
(Croker, 1825) has a merman keeping souls in cages. Amber is a **gem-form soul
jar** - and the only form on that list that occurs in nature already holding a
real creature, visibly, forever.

**Why the field is nearly exhausted.** Almost every good word here fails one of
two screens, and they are the two screens this exercise already learned:

*Live religious object - the Phylactery trap:*

| Word | Referent |
|---|---|
| Nkisi | Bakongo power object that houses a spirit - live practice |
| Shem | the name-scroll animating a golem - Jewish tradition |
| Butsudan, spirit tablet | live Buddhist / Confucian household practice |
| Tabernacle, Ark | live Christian / Jewish sacred furnishings |
| Ka statue | Egyptian; the ka inhabits the statue if the body is destroyed - the closest true antique match, but "Ka" is one ambiguous syllable |

*Already owned by a major game - the Bindstone trap:*

| Word | Owner |
|---|---|
| **Horcrux** | Warner Bros. Not available under any circumstances. |
| **Soulstone** | Diablo / Blizzard |
| **Soul Gem** | Elder Scrolls / Bethesda |
| **Soul Cage** | Paizo's official phylactery replacement, AND a Minecraft spawner |
| **Emberstone** | Emberstone Interactive (London studio) + Heart of the Emberstone (Cloudhead VR). `.gg` and `.app` are free, the name is not. |
| Talisman | Games Workshop board game; `.gg` taken |
| Grail | Fate/stay night's Holy Grail War, plus the Christian relic |
| Simulacrum | a D&D spell - and it MEANS a copy, positioning the product as not-the-real-thing |

*Failed on their own merits:*

- **Koschei** - the perfect myth, an impossible spelling (Koschei / Kashchei / Koshchey).
- **Effigy** - dominant sense is "burned in effigy"; a poppet is a proxy for HARMING someone, not a container. `.app` taken.
- **Athanor** - an alchemical furnace, not a container. Obscure with no recognition anchor (the Ostensorium problem). `.app` taken.
- **Barrow** - a grave, and the primary modern sense is wheelbarrow. `.app` taken.
- **Fetish** - the anthropological sense is exactly right; the modern sense ends it.
- **Soul Jar** - the trope's own name, therefore generic and unownable.
- Locket, Anima, Chrysalis, Heartwood - all `.gg` AND `.app` gone.

**The one clean survivor: WILLSTONE.** `.gg` and `.app` both free, zero products
found anywhere, 2 syllables, spells itself, one pronunciation, no League
collision, invented so nothing can collide later.
*Adversarial:* invented compounds read generic-fantasy, "will" is ambiguous
between volition and testament, and it is markedly less distinctive than
Amberstone. Mechanically flawless, characterfully thin.

**Verdict: nothing displaces Amberstone.** Willstone is the only alternative
that survives every screen, and it is blander. Also free if wanted:
`corestone.gg`, `quickstone.gg`, `souljar.gg`, `soulcask.gg`, `amberkeep.gg`.

### 6b2.9 NAME LOCKED (operator, 2026-08-11)

**Amberstone** (product) + **Daemon Slayer** (engine, internal, unchanged).

Rationale on record: amber is a canonical soul-jar form (6b2.8) that binds,
preserves AND displays what is inside it - the phylactery concept with no
religious referent and no game-industry owner. 3 syllables, spells itself from
hearing, one pronunciation, no League vocabulary collision, `amberstone.gg` and
`amberstone.app` both free at probe.

Execution plan: **`docs/RENAME_SWEEP_AMBERSTONE.md`** (scoped, not executed).
Headline from that scoping: only ~946 of the repo's **4163** "riot" occurrences
are the product name - the other ~77 percent are NOMINATIVE (Riot Games, Riot
API, Riot Live Client) and must survive. A blind find-replace would break the
legally required disclaimer, which must literally read "isn't endorsed by
**Riot Games**".

**KEPT (superseded by the lock above, retained for the record):**

| Name | Domains at probe | Register |
|---|---|---|
| **Salt Circle** | `saltcircle.gg` + `saltcircle.app` | occult containment - what you draw to hold a daemon. Pairs with the Daemon Slayer engine: the engine summons, the product contains and presents. |
| **Lane Oracle** | `laneoracle.gg` | advisory / divinatory, grounded in the game by "lane". |

**Further candidates, all unregistered at probe (2026-08-11, NS lookup):**

Advisory / divinatory register, siblings of Lane Oracle:

- **Bellwether** (`bellwether.gg`) - the leading indicator. Reads as analytics.
- **Portent** (`portent.gg`) - a sign of what is coming. Short, ownable.
- **Auspice** (`auspice.gg`) - the reading of omens before a decision. Note the
  bare `auspex.gg` and `pythia.gg` are both taken; `auspice` is the survivor.
- **Lane Augur** (`laneaugur.gg`) - the augur read birds before a battle.
- **Lane Almanac** (`lanealmanac.gg`) - quieter, reference-book framing.
- **Lane Warden** (`lanewarden.gg` + `.app`) - the most literal and the safest.

Occult / containment register, siblings of Salt Circle:

- **Wardstone** (`wardstone.gg`) - the stone that holds a boundary.
- **Hollow Circle** (`hollowcircle.gg`), **Iron Circle** (`ironcircle.gg`),
  **Chalk Line** (`chalkline.gg`) - the same containment idea, different material.
- **Candlewright** (`candlewright.gg`), **Banewright** (`banewright.gg`),
  **Nightsmith** (`nightsmith.gg`) - maker-of register.
- **Thornbind** (`thornbind.gg`), **Ashline** (`ashline.gg`),
  **Bind Sigil** (`bindsigil.gg`), **Sigilcraft** (`sigilcraft.gg`) - binding.
- **Reliquary** (`reliquary.gg`) - the vessel that holds the dangerous thing.

Carried from the first pass: **Lane Commander** (`lanecommander.gg` + `.app`,
lowest rename churn, keeps the existing equity) and **Sidelane** (`sidelane.gg`;
`sidelane.app` is taken).

**Taken at probe, do not re-check:** lodestar, sightline, coldiron, sigil,
familiar, grimoire, pact, conjure, auspex, pythia, cadence, wardens, and every
other bare single-word `.gg` tried. Availability rots - re-probe before
committing to any of the above, and clear the final pick against USPTO.

## 6c2. B3 CORRECTED - deleting the panel did not remove the artefact

Filed 2026-08-12, during B4-b. **B3 was recorded DONE on 2026-08-11 and the
power-spike notification was still firing in-game a day later.** The row is
corrected here rather than quietly re-marked, because the failure mode is
reusable and would have repeated on B1 / B2 / B10.

**What was true:** `web/js/panels/spike_cue.js` really was deleted, along with
its CSS, its registry entry and 2 test files, and an inverted guard was left
behind so re-adding it turns a test red. Nothing about that work was wrong.

**What was missed:** the banned artefact was never confined to that panel. The
spike lines are generated server-side in `core/event_callouts.py` and shipped
on the TOP-LEVEL `/api/state` key `callouts`, which feeds `#rn-callouts` - one
of only three mounts the overlay shell keeps visible
(`web/css/overlay.css:127`):

- `core/event_callouts.py:119` "Your lvl-6 spike - look for all-in"
- `core/event_callouts.py:127` "2-item spike - force fights now"
- `core/event_callouts.py:126` "1-item spike - fight on cooldowns up"

Those are the B3 artefact ("notifications that alert players when a power spike
hits") AND the B4 artefact (an imperative) in the same string. The same feed
also carries objective imperatives - `:107` "Drake spawns 5:00 - set up vision",
`:109` "Plates fall 14:00 - shove for gold".

**Status now: closed for the live surface, by B4-b (`495c2b88`), not by B3.**
`dashboard/_state_builder.suppress_live_envelope` blanks `callouts` and
`lead_projection` while a game is live, and `web/js/panels/callouts.js`
self-gates as defence in depth. The generators are untouched and remain
available out of game, which is correct - a spike table read pre-game or
post-game is analysis, not a live notification, exactly as the original B3 row
intended for `spike_curve` / `spike_markers`.

**The transferable lesson, worth applying to any future removal here: a banned
artefact is a BEHAVIOUR, not a file.** The audit that produced the B1-B10 table
searched by panel, so it found the panel that was named after the feature and
missed the second producer that emits the same thing through a different mount.
When closing a row, grep for the STRING the user sees and for every mount that
can render it - not for the component whose name matches the rule.

### Applying that lesson to B1 / B2 / B10 (checked 2026-08-12)

The correction is only worth writing if the same miss is not sitting in the
neighbouring rows, so they were swept the same way - by behaviour, not by file.
**Result: no second live producer found. One dead residual, no violation.**

- **B1 / B2 - clean, and the one residual is now REMOVED (2026-08-12).** The
  only surviving enemy-side symbol was `core/match_metrics.py`
  `"enemy_summs_tracked"`, a dead entry in
  `Recorder._PAYLOAD_METRIC_MAP` - the registry that decides what
  `record_state_snapshot` persists to `data/match_metrics.db`. Proven dead on
  three axes before deletion: no writer anywhere in the tree (it was the sole
  non-doc, non-test hit), no renderer (`st-enemy-summs` had already gone from
  `web/`), and **zero rows out of 246,928 in the live DB**, so there was no
  historical data to recover either. Never a live violation - an optics one,
  since a reviewer grepping "enemy_summs" would find an enemy metric that
  looked declared and wired for persistence. Deleted with an inverted guard
  (`tests/test_cc_threat_cell_riot_compliance.py`
  `EnemySummsRegistryResidualTests`), including a broader
  any-key-matching-enemy+summ assertion, because the lesson above is that the
  ban is on the behaviour and not on one spelling.
- **B10 - clean.** `cooldown-watch` survives only in docs, ROADMAP, WAKEUP,
  LEDGER and `web/index.html` prose. No route, no producer.
- **Deliberately retained and correct:** `my_ult_cd_s`
  (`core/laning_scenario_precompute.py:613-664`) is the operator's OWN
  ultimate, which the file already documents as intentionally kept, and
  `ally_summs_up` is own-party, which the B2 row explicitly permits
  ("restrict `summs` rows to own party only"). Neither is an enemy timer.

## 6d. The CC threat cell - where the line actually falls

Operator question 2026-08-11: enemy cooldowns are publicly observable, so how
deep should the culling go? The answer is that Riot's wording is "**tracking** of
enemy ability cooldowns" - the verb carries the rule. DDragon publishes every
per-rank cooldown and the client shows them in its own champion info, so the
prohibition is not about secrecy. It is about per-instance live state: this
enemy, this cast, this countdown.

What that means in practice:

- **The DS engine's cooldown math is untouched and must stay that way.**
  `agents/daemon_slayer/combo.py` still reads per-rank `cooldown` lists, runs the
  cast-time/cooldown clock, and marks `status="on_cooldown"` to skip a spell in a
  rotation. DPS, combo timelines and rotation math all depend on it.
- **Champ-select CC advice is fine.** "Enemy comp has 4 hard-CC abilities -
  Cleanse or QSS is worth a slot" is composition analysis over public champion
  identities, pre-game, with no live state. `cc_pressure` / `cc_pairing` /
  `cc_conditional` / `cc_output` and their three routes are all intact.
- **Two boundaries to hold:** never attach SECONDS to a named enemy ability in a
  live surface (that reconstructs the watch card), and never make it STATEFUL
  ("their E is up now").

The rebuild, replacing the deleted `cooldown_window` block:

| Was | Now |
|---|---|
| `cooldown_window_cell` | `cc_threat_cell` |
| `window_verdict` | `cc_threat_verdict` |
| cell key `cooldown_window` | cell key `cc_threat` |
| `_window_chip` / `_WINDOW_LABELS` | `_threat_chip` / `_THREAT_LABELS` |
| `enemy_cd_s` (banned) | **removed - no successor** |
| `enemy_cc_s`, `enemy_threat_spell`, `my_ult_cd_s` | kept |
| label "Punish - their {spell} is down" | "Bait their {spell}, then commit" |
| outcome "their Q cd ~20s; your ult is your window" | "their Q locks you for ~1.25s; bait it, then your ult" |

The old label and outcome both ASSERTED KNOWLEDGE OF AN ENEMY COOLDOWN, which is
why both changed. The verdict vocabulary (`punish_now` / `wait_cd` / `even`) is
deliberately unchanged so every downstream consumer kept working.
`my_ult_cd_s` stays: it is the operator's own ability, not an opponent's.

Built TDD - `tests/test_cc_threat_cell_riot_compliance.py`, 10 cases red before
implementation, green after. One case fails on ANY key matching `enemy_*_cd_s`,
so the scalar cannot creep back under a new name.

**Trap worth recording.** The obvious CC source, `agents/daemon_slayer/_per_spell_cc.py`,
is EMPTY BY DESIGN at this engine version ("forward-marker: the registry is empty
at 1.29.0 ... all calls return `()`"). Sourcing from it would have shipped a
silent zero in every cell, degrading the block to `even` everywhere while every
test and health signal stayed green. The live registry is
`agents/daemon_slayer/ability_dps._PER_SPELL_CC_DURATIONS` (89 champions). The
test asserting Leona's CC is `> 0` exists precisely to catch that substitution.

## 7. Open questions for DevRel / Riot

- Is a MANUAL, player-clicked enemy summoner-spell tracker permitted? (Competitor
  teamgap.gg ships mouse-wheel-adjusted summ timers on Overlay Platform M, so a carve-out
  may exist in practice. Do not act on that inference - ask.)
- Does the ultimate-timer ban cover the player's OWN ultimate?
- Is out-of-band screen capture + OCR acceptable, or must all capture route through Overlay Platform M?
- Does a Python sidecar process shipped in the installer pass review?
