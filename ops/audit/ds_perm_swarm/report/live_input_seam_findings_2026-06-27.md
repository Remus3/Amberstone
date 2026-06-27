# Live-Input DS Seam + Overlay Findings (2026-06-27)

Session: RC live-flip validation. DS ENGINE 1.153.0, patch 16.13.1. Operator ran
Practice Tool games (KSante / Briar / Ezreal) to close the "live half" of the
offline-confirmed DS seam flips. Result: the live half is NOT a passive eyeball -
it is blocked by unwired plumbing. Ground truth cited for each finding.

## 1. Live-flip seams are unwired across the DS /rank HTTP boundary (BLOCKER)

The seam flags exist ONLY in the in-process scorers + tests + the offline harness
`ops/audit/ds_perm_swarm/live_flip_eyeball.py`:
- R5 missing-HP heal-amp: `assume_missing_hp_heal_amp` + `caster_missing_hp_pct`
  (agents/daemon_slayer/ability_hps.py only)
- DSP2 off-class WIN-exemption: `exempt_offclass_by_win` (agents/daemon_slayer/rank.py:611)
- DSP11 kit-axis credit: `prefer_kit_axis_by_win` (agents/daemon_slayer/rank.py:621)

The live chain `dispatch_for_coach` (coach_integration/archetype_dispatch.py:232)
-> `daemon_slayer_client.rank_for_primary_archetype` -> server.py `/rank` passes
NONE of them, and server.py `/rank` does not accept them (only `target_current_hp_pct`
/ `target_missing_hp_pct`, enemy-side, server.py:899). So the live build-chooser
(/api/state `daemon_slayer_picks`) runs every scorer at DEFAULT-OFF.

Live proof: Briar at 7% HP (133/1860) produced byte-identical `daemon_slayer_picks`
to 100% HP - Runaan's 76.34 / BotRK 53.55 / Heartsteel 49.95 / Trinity 43.04 /
Yun Tal 41.08. Zero HP sensitivity. Same mechanism blocks R12 / R30 / RF1 / RF3.

To flip default-ON usefully: plumb the flags through `/rank` -> client -> dispatch
(+ pass live hp/hp_max as `caster_missing_hp_pct` for R5), ENGINE bump, Tier-2.
This is a headless build task, NOT a default-ON toggle.

## 2. R12 (Evenshroud target-vuln) is SR-untestable on 16.13.1

Evenshroud id 3001 is purchasable=False / inStore=False / maps all False on SR;
the 22-prefixed Arena alias 223001 has maps.30=true. Evenshroud is Arena-only this
patch. The live build-chooser correctly never offered it (respects map
purchasability). R12 needs an Arena game for any live eyeball; the offline verdict
still holds (the consumer is map-agnostic).

## 3. KSante GAME 1 RF3 was over-called

What was observed live was the EHP scorer ranking defensive items vs a 5-tank comp
(Warmog / Jak'Sho / Kaenic Rookern / Sterak's / Heartsteel) - the scorer's DEFAULT
behavior, identical with the RF3 flag on or off. The RF3 survivability-credit flag
itself was never isolated (same /rank blocker as #1). cc-floor WAS confirmed live
(fight_rule "62% CC saturation").

## 4. No in-game build-chooser overlay widget

Screenshot (Ezreal, in-game): the CALL overlay renders (coach action/objective,
e.g. "PUSH BOT LANE / Setup Drake 4:59"), but there is NO item-build widget on the
overlay. `daemon_slayer_picks` render ONLY on the :8888 dashboard (the Chrome log
shows it fetching pick icons 3085 / 3153 / 3036 / 3097 / 3031). The overlay has no
build surface at all.

## 5. Overlay layout hotkeys dead in-game (Ctrl+Shift+A / Alt+Shift+A / Alt+Shift+R)

These are page-level keydown handlers in web/js/lib/overlay_layout.js (line 259:
"page-level keydown never fires - the OS-level hotkey is the only path"). In-game,
League owns keyboard focus (borderless included), so the overlay never receives
them. The working pattern is Ctrl+Shift+1/2 (coach decisions) via Win32
RegisterHotKey in tools/hotkey_listener.py (global, anti-cheat-safe). The A/R global
registration is referenced as "future" (overlay_layout.js:320) and was never built.
Fix = register the layout hotkeys globally + signal the overlay. (Build target #4.)

## 6. Long coach tick when base under attack (operator-reported, untraced)

Not yet traced; today's log is DEBUG-HTTP spam with no tick-duration instrumentation.
Needs a coach-loop timing trace correlated to inhib/turret/nexus events.

## Haiku-to-zero remaining (grep ground truth)

Live in-game per-tick consumers still on `claude-haiku-4-5`:
- aram_coach.py (4 calls), arena_coach.py (6), brawl_coach.py (2)
- vision OCR escalation (vision server runs Haiku)

SR coach (coach_integration/_coach.py) shows NO hardcoded haiku call in the grep -
appears already off live Haiku (confirm the SR LLM path separately). Peripheral /
not-per-tick: champ_select_coach, replay_coach, experimental_builder,
aram_team_analyzer. To zero: port ARAM/Arena/Brawl onto SR's precompute pattern
(DS scenario tables + A/B deterministic); decide vision-Haiku separately.
