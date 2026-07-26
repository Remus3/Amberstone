---
description: |
  Live-game tutor tick. Surface coach state + UI staleness while a League/TFT/Arena game is in progress.

  CONTRACT: Check `https://127.0.0.1:8888/api/state` (skip cert verify; it's mkcert self-signed).

  GATE: If `mode_key` NOT in `{sr, arena, aram, tft, brawl}` OR `liveclient` is null/empty, emit zero text and stop. No tool calls beyond the state probe.

  OTHERWISE: Capture the live game frame on Legion (League runs ON Legion now). PRIMARY: GET `https://127.0.0.1:8889/latest-frame` (skip cert verify) - the same in-process vision frame the coaches read via `modes/shared_vision._capture_screen`. ESCALATION (only if the frame is missing or stale): a Legion desktop screenshot. Compare the dashboard render against `liveclient` (game_time / cs / level / kda / hp / gold / owned_items) and `coach` (action / immediate / next / fight_rule / watch / target / objective).

  Surface in 3-5 lines max:
  1. Active coach action one-liner with key timing (next drake/baron/respawn).
  2. Any UI staleness - top-bar CS/KDA/items panel mismatch between /api/state and dashboard render.
  3. Next imminent objective from `coach.next` or `coach.objective`.

  If nothing is actionable (between rounds, mid-base, etc.), say "tick OK" only - one line, no tool calls beyond the state probe.

  Do NOT engage the user with mid-fight commentary unless something dangerous (low HP at fight, dragon contest with majority enemies missing, etc.) warrants interruption. The user is in a game; brevity matters.
---

.
