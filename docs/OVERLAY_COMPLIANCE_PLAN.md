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
| B3 power-spike cue | **DONE - deleted** | Cue, CSS, registry entry, 2 test files. `spike_curve` / `spike_markers` survive as pre/post-game analysis. |
| B4 coach imperatives | **DECIDED, NOT BUILT** | See 6c. Silent branch capture in-game, review post-game. |
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
| B3 | `web/js/panels/spike_cue.js` - fires "the instant the operator crosses an ULTIMATE power spike" | "Notifications that alert players when a power spike hits" | Remove the live cue. The static build-planning curves (`spike_curve.js`, `spike_markers.js`) are pre/post-game analysis, not live notifications - keep them OUT of the in-game overlay and they survive. |
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
