---
description: |
  Live-game tutor tick. Surface coach state + UI staleness while a League/TFT/Arena game is in progress.

  CONTRACT: Check `https://127.0.0.1:8888/api/state` (skip cert verify; it's mkcert self-signed).

  GATE: If `mode_key` NOT in `{sr, arena, aram, tft, brawl}` OR `liveclient` is null/empty, emit zero text and stop. No tool calls beyond the state probe.

  OTHERWISE: Capture the live game frame on Legion (League runs ON Legion now). PRIMARY: GET `http://127.0.0.1:8889/latest-frame` with header `X-RC-Token` from `core.vision_token.get_vision_token()` (plain HTTP, not https; never paste the token value) - the same in-process vision frame the coaches read via `modes/shared_vision._capture_screen`. ESCALATION (only if the frame is missing or stale): a Legion desktop screenshot. Compare the dashboard render against `liveclient` (game_time / cs / level / kda / hp / gold / owned_items) and `coach` (action / immediate / next / fight_rule / watch / target / objective).

  Surface in 3-5 lines max:
  1. Active coach action one-liner with key timing (next drake/baron/respawn).
  2. Any UI staleness - top-bar CS/KDA/items panel mismatch between /api/state and dashboard render.
  3. Next imminent objective from `coach.next` or `coach.objective`.

  If nothing is actionable (between rounds, mid-base, etc.), say "tick OK" only - one line, no tool calls beyond the state probe.

  Do NOT engage the user with mid-fight commentary unless something dangerous (low HP at fight, dragon contest with majority enemies missing, etc.) warrants interruption. The user is in a game; brevity matters.
---

> **DISPATCH (FLEET-KIT v10 banner; MAIN 2026-10-08 0839 ORDER step 4).** In an interactive main session this skill is never run inline.
> 1. The main session dispatches the WHOLE skill to ONE sub-agent (Agent tool): this file plus the invocation arguments. It relays only that agent's final output - the line(s) this skill names as its chat output, nothing when it names none - with no narration around it.
> 2. No quick-read or trivial-edit exception in the main thread; this supersedes any "may inline" line in this file. Its Bash / PowerShell / Read / Edit / Write / Grep / Glob / NotebookEdit calls meet the kit PreToolUse hook `ops/fleet_kit/fleet_subagent_first.py` (gitignored mode file `ops/loop/control/subagent_first.mode`: log first, then deny).
> 3. The dispatched sub-agent, and a headless run (the kit's `spawn()` sets `FLEET_SUBAGENT_FIRST=off`), execute this skill directly and never re-dispatch the whole of it.

> **RACE GUARDS (FLEET-KIT v12, FLEET-COMMON item 16; MAIN 2026-10-08 2031 ORDER step 5).** Enforced by the kit hook `ops/fleet_kit/fleet_claims.py` (PreToolUse + SubagentStop in the project settings), not by this text.
> 1. Every `git commit` / `git push` runs through the tree's git lock: `python ops/fleet_kit/fleet_gitlock.py run --owner <id> -- git commit -F <tmpfile>` (same shape for `git push ...`). Python code uses `fleet_gitlock.git_lock(dir, owner)`. A bare commit or push is denied.
> 2. A WHOLE suite (pytest naming no test file) runs through the machine-wide gate: `python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- <suite cmd>`. A slice that names its test files needs no gate.
> 3. `<id>` is your own claims owner id, `<session_id>.<agent_id>` (`.main` in a main thread); a deny reason names it. The hook also denies an edit, a redirect or a `git add` of a file another live agent holds - leave that file to its agent.

.

## :8889 frame probe - failure table

Resolve the token once per shell, from the repo root (never echo or paste the value):

```bash
TOK=$(python -c 'from core.vision_token import get_vision_token as g; print(g())')
```

| Symptom | Cause | Check | Fix |
|---|---|---|---|
| curl status `000` on every :8889 path, http included | Dead relay: nothing listening on :8889 (a detached child; RC respawns it only at startup when the port is down) | `curl -s -o /dev/null -w "%{http_code}" -H "X-RC-Token: $TOK" http://127.0.0.1:8889/health` prints `000` | `echo restart > restart_trigger.txt`; if the port listens on old code, taskkill the listener PID first (memory `reference_vision_server_restart_does_not_redeploy`) |
| curl status `000` or an empty body, yet `/health` over http answers 200 | Wrong scheme: `https://` against the plain-HTTP relay | `curl -s -o /dev/null -w "%{http_code}" -H "X-RC-Token: $TOK" http://127.0.0.1:8889/latest-frame/meta` answers where the https form gave `000` | Use `http://`, never `https://` or `-k`, on :8889 (memory `reference_vision_relay_probe_needs_http_and_token`) |
| HTTP `401` with `{"error": "unauthorized"}` | Missing token: no `X-RC-Token` header, or one the listener does not hold | `curl -s -o /dev/null -w "%{http_code}" -H "X-RC-Token: $TOK" http://127.0.0.1:8889/latest-frame/meta` is 200 with the resolved `$TOK` | Send the header from `core.vision_token.get_vision_token()`, never a pasted value; 401 WITH the resolved token means a rotation the listener missed (memory `reference_vision_token_canonical`) |
| 200 and a frame, but the pixels disagree with `liveclient` | Stale frame: `/latest-frame` serves the LAST frame (load screen, alt-tab) | `curl -s -H "X-RC-Token: $TOK" http://127.0.0.1:8889/latest-frame/meta` and compare its `ts` with now and with `liveclient` game_time | Re-capture once the frame is fresh, else escalate to a desktop screenshot; never tick on an untimed frame (memory `feedback_capture_artifact_staleness`) |
