---
description: End-of-session ritual — auto-commit any pending changes, push, do the /wrap checks, then signal "ready for /clear" so the next session starts fresh without context bloat. Use when work is wrapped and you want a clean exit.
---

The user wants to end the session cleanly so the next one starts with a fresh context window. This is /wrap, but with auto-commit instead of "stop and ask". Run all sections in order; surface a tight final banner.

### 1. Auto-commit any pending changes

- `git -C "C:/Riot Commander" status -s`
- If output is empty: skip to §2.
- Otherwise:
  - **Audit before staging**: refuse to auto-commit any path matching `*SECRET*`, `*HANDSHAKE*`, `*PIVOT*`, `*REPLY*`, `*TOKEN*`, `*KEY*`, `.env*`, `local_paths.json`, `API-Key-Claude.txt`, or anything that looks like credentials. If matched: stop and ask the operator before proceeding.
  - **Frozen-file guard**: per `CLAUDE.md`, several files require explicit user approval before editing. If any modified path is in the frozen list, stop and ask — auto-commit is too dangerous here. Frozen list lives at the top of CLAUDE.md.
  - Stage only the changes you authored this session (`git add <specific files>`). Do NOT use `git add -A` — accidentally commits .env / runtime junk.
  - Draft a one-line commit message summarising the session's work (1-2 sentences, "why" over "what"). If multiple distinct themes: list them as bullets in the body.
  - Commit with the standard `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.
  - If pre-commit hooks fail: fix and create a new commit (never `--amend`).

### 2. Push

- `git -C "C:/Riot Commander" log @{u}.. --oneline` — list local commits not on origin.
- If empty: skip.
- Otherwise: `git -C "C:/Riot Commander" push origin <branch>`. No confirmation prompt — pushing is part of the exit ritual.
- Surface the push result (e.g. `23854e1..b56f247 main -> main`) in the final summary.
- Only ask the operator if the push fails (auth, conflict, hook).

### 3. Background tasks started this session

- TaskList — show anything still running.
- Each one: TaskStop. DO NOT leave monitors armed; they're useless after /clear.

### 4. Game-PC bridge auto-flow loop liveness

- Dispatch a quick probe via `tools/bridge_task.py --target gamepc --summary "loop liveness check" --prompt "Reply with hostname + brief status via bridge_post_result.py. Plain JSON body."`
- If no result lands within 90s: the loop is dead. Flag it in the banner so next session knows to re-run `/loop /process-bridge-tasks` on Game-PC.

### 5. RC restart pending

- Check `C:/Riot Commander/restart_trigger.txt` — if non-empty, RC may still be reloading. Confirm `ops/runtime/health.json` shows `alive=true` AND `last_reload_ok=true` before declaring done.

### 6. WAKEUP_NOTES update

- The next session will bootstrap from `C:/Riot Commander/WAKEUP_NOTES.md` + `MEMORY.md` + git log. Make sure tomorrow-you can pick up cleanly.
- Append a short entry (≤20 lines) describing this session's work: commits shipped, key decisions, what's next. Don't rewrite history; just append.
- Note explicitly any blockers or things tomorrow-you should NOT redo (e.g. "lobby pill fix already shipped in bb4cff9 — don't re-investigate").

### 7. Memory updates

- List new/modified files under `C:/Users/Administrator/.claude/projects/C--Riot-Commander/memory/` since session start.
- Confirm `MEMORY.md` indexes any new memories; add if missing.

### 7b. Triage incoming lessons from peers

- Invoke the `/process-incoming-lessons` skill — drains any `kind=lesson` envelopes from the cross-Claude bridge that landed during the session. Apply / queue / discard decisions ride on the skill's schema gate + `does_not_apply_when` filter; we just want them off the queue before /clear so nothing is lost between sessions.
- If "no lessons": include "✅ no pending lessons" in the banner.
- If it applies any: include "✅ applied N lessons" with one-line titles.
- If it errors: surface the error ABOVE the banner and add "⚠️ resolve <X>" to the bottom line — but don't block /clear over a triage failure since a fresh session can re-pull from the bridge log.

### 8. Game state safety check

- Hit `https://127.0.0.1:8888/api/state` (or `https://192.168.8.230:8888/api/state` if local fails) — note `lcu.phase` and `mode_key`.
- If user is mid-game: warn that /clear right now will kill live bridge access until next session starts.

### 9. Final banner

Print a tight banner — exactly this format:

```
══════════════════════════════════════════════════════════════════
  /done complete — context ready for /clear
══════════════════════════════════════════════════════════════════
  • commits this session : <count> (pushed: <push range>)
  • background tasks     : stopped <count>
  • bridge gamepc loop   : ✅ alive | ⚠️ stale (<age>s) | ❌ dead
  • RC health            : pid=<pid> alive=<bool> reload_ok=<bool>
  • WAKEUP_NOTES         : updated (+<N> lines)
  • lessons triaged      : <N applied | none pending | err: …>
  • mid-game             : no | YES — wait until safe to /clear
══════════════════════════════════════════════════════════════════
  Type /clear to start a fresh session with reset token budget.
══════════════════════════════════════════════════════════════════
```

If anything failed (commit blocked, push failed, mid-game, etc.), surface the issue ABOVE the banner and substitute "⚠️ resolve <X> before /clear" on the bottom line.

### Safety rails

- NEVER force-push, NEVER use `--amend`, NEVER skip hooks (`--no-verify`).
- NEVER auto-commit secrets, frozen files, or runtime junk.
- NEVER run `/clear` from inside the skill — it's a Claude Code built-in handled by the harness, not the model. Just print the banner and let the operator type it.
- If git push needs auth (gh CLI prompt, etc.): stop and ask. Don't keep retrying.
