# Proposal M-02 - game-summary emitter must skip Unknown-champion payloads

**Filed:** 2026-07-27 by agent6 during `t-f19b4cb85b1d` full-audit-pass
**Owner:** Agent 1 (queue) -> Agent 2 (backend / game-lifecycle emitter)
**Severity:** medium

## What
`agents/state/task_queue.jsonl` currently carries 79 completed
`game-summary` dispatches (recorded window 2026-04-26 - 2026-07-26). Every
one has:

```
payload.champion == "Unknown"
result.inserted == False
result.reason == "missing champion"
```

Every dispatch travels the full pipeline: emit -> queue append (under
lockfile) -> dispatch -> `game_ingest.ingest_game_summary` -> refuse.
Nothing on the emit side backs off, so a stale `coaching_data.json` read
manufactures another queue no-op every time the game-lifecycle heartbeat
fires.

## Why
Auditor "bad process" scope (not "bad advice"). The pipeline correctly
rejects the insert, but the emitter should never have queued it. The
queue is a growing ledger of guaranteed no-ops, and the lockfile plus
queue append are non-zero cost.

## Fix (pseudo-code, NOT applied - lives in Agent 2 codepaths)

In the game-summary emitter (owner: Agent 2, likely in
`app/_game_lifecycle.py` or an `agents/agent2_backend/game_ingest.py`
helper) - before enqueue:

```python
UNKNOWN_CHAMPION = {"", "Unknown", None}

def _should_emit_game_summary(payload) -> bool:
    if payload.get("champion") in UNKNOWN_CHAMPION:
        _log.info("game-summary emit skipped: champion=%r finished_at=%s",
                  payload.get("champion"), payload.get("finished_at"))
        return False
    return True
```

Belt-and-braces: keep the ingest-side `result.reason == "missing
champion"` refusal as the safety net.

## Test / verification
- Add a unit test on the emitter that asserts an Unknown-champion payload
  never reaches the `queue.append` call.
- After deploy, count `game-summary` entries in `task_queue.jsonl` over
  a 24h window; expect 0 for the Unknown case, non-zero only for real
  finishes.

## Not agent6 autonomous scope
Emitter lives in Agent 2's code. `app/_game_lifecycle.py` is a FROZEN
file (see `phase3-d001`) so any edit there requires explicit operator
approval. If the emit call actually lives in `agents/agent2_backend/*`
(non-frozen), Agent 2 can land it directly.
