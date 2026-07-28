# M-02 audit - APPROVE with amendments

**Auditor:** agent6 (Auditor) - task `t-12989b480e78`
**Ground-truth probed:** 2026-07-27
**Verdict:** APPROVE the intent + fix shape; amend the file-path, the
payload-shape claim, and the guard scope before Agent-2 lands it.

## Verified claims

- 583 total `game-summary` rows in `agents/state/task_queue.jsonl` (5798 lines).
- 79/79 rows with `result.reason == "missing champion"` - proposal count exact.
- Splits: 63 from `coaching_data.json` (SR CLASSIC), 16 from
  `aram_coaching_data.json` (mode `KIWI`). Emitter is one code path;
  distribution just reflects which mode file was newest at
  game-end.
- Ingest-side refusal path: `agents/agent2_backend/game_ingest.py:212-216`,
  `if not champion or champion == "Unknown": return inserted=False,
  reason="missing champion"`. Confirmed the pipeline WOULD reject.

## Corrections to proposal

### 1. Emitter location is `agents/supervisor.py`, NOT `app/_game_lifecycle.py`

Grep results:
- `app/_game_lifecycle.py` - NO `game-summary` / `game_summary` / summary-emit
  references. Frozen-file concern is a false alarm.
- Emitter is `Supervisor._file_post_game_summary`
  (`agents/supervisor.py:679-770`), called from the game-end
  transition handler at `agents/supervisor.py:665`.
- The actual `scheduler.file_task(op="game-summary", ...)` call is at
  `agents/supervisor.py:762-768`.

`agents/supervisor.py` is NOT in the CLAUDE.md frozen list. Agent 2 (or
whoever owns the supervisor scheduling path) can land the guard
directly - no operator gate needed for M-02 itself.

### 2. Payload shape - `champion` is ABSENT, not `"Unknown"`

Sample row (excerpted): `"payload":{"prev_mode":"game","new_mode":"",
"finished_at":"...","mode":"game","game_mode":"KIWI",
"source":"aram_coaching_data.json"}` - no `champion` key.

The ingest side normalizes `payload.get("champion") or "Unknown"`, so
the "== Unknown" claim describes the normalized value, not the wire
payload. The proposed guard `payload.get("champion") in {"", "Unknown",
None}` still handles the case correctly (`.get()` returns `None` for
absent keys), so the fix code is sound - only the docstring is
misleading.

### 3. Trigger is a transition edge, NOT a heartbeat

`_maybe_file_post_game_summary` fires only when `prev_norm in
{"game","in_progress"}` AND `new_norm` isn't - once per game end. The
proposal's "every time the game-lifecycle heartbeat fires" is off;
observed rate (~79 skipped emits over 3 months) is consistent with
per-game-finish, not per-tick.

### 4. Missed sibling class - 91 `unknown game_mode` rows

`grep -c '"reason":"unknown game_mode' task_queue.jsonl` -> 91. Same
guaranteed no-op shape: the mode-DB router refuses at
`game_ingest.py:206-211` before the champion check. A pure
Unknown-champion guard leaves these behind.

Recommended widening (still emit-side, single early-return):

```python
UNKNOWN_CHAMPION = {"", "Unknown", None}

def _should_emit_game_summary(payload) -> bool:
    if payload.get("champion") in UNKNOWN_CHAMPION:
        _log.info("game-summary skip: no champion (source=%s game_mode=%s)",
                  payload.get("source"), payload.get("game_mode"))
        return False
    # Precheck the same mode-DB router the ingester uses - if it would
    # refuse, do not enqueue. Import path is stable in-tree.
    from agents.agent2_backend.game_ingest import _select_mode_db
    game_mode_raw = payload.get("game_mode") or payload.get("mode_category") or ""
    if _select_mode_db(game_mode_raw) is None:
        _log.info("game-summary skip: unknown game_mode=%r", game_mode_raw)
        return False
    return True
```

Keeps `_select_mode_db` as the single source of truth (no duplicated
`KIWI -> aram` map on the emit side). Ingest-side refusals remain the
belt-and-braces net.

## Test asks (added to proposal)

- Unit test on `_file_post_game_summary`: build two payloads (no
  `champion`, and unknown `game_mode`), stub scheduler, assert
  `scheduler.file_task` NEVER called; then a happy-path payload does
  call it once.
- After deploy, 24h count of `game-summary` rows with
  `result.reason in {"missing champion","unknown game_mode"}`
  should be 0.

## Autonomous scope

With the emitter located in `agents/supervisor.py` (not frozen), this
is Agent-2-autonomous (owner of the supervisor scheduling path).
`requires_operator_approval` should stay `false` on the dispatch.
Auditor recommends handing to Agent 2 with the amendments above; no
further gate from agent6.
