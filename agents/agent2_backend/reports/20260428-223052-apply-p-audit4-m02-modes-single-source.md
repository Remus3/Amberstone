# Report: apply P-audit4-m02 — mode list single source-of-truth

**Task:** `t-4be5ae557e67`
**Proposal:** `P-audit4-m02-modes-single-source`
**Severity:** medium
**Date:** 2026-04-28
**Agent:** agent2_backend

## Summary

`SUPPORTED_MODES` was hardcoded as `("sr_draft", "sr_ranked", "aram", "arena", "brawl")` in four
independent locations and `MODE_DBS` as a parallel filename list in a fifth.  Any change to the
supported mode list required manual edits in at least five files with no enforcement of consistency.

This change introduces `lib/modes.py` as the single source of truth, derived at import time from
`resolved_decisions.json`'s `db.files` key, and replaces every hardcoded occurrence with an import.

## Changes made

### New file: `lib/modes.py`
- Reads `agents/state/resolved_decisions.json` at import time.
- Exports `PHASE3_MODES: tuple[str, ...]` — mode names with `.db` suffix stripped.
- Exports `verify_modes()` — re-reads the JSON at supervisor startup and raises `RuntimeError` on
  drift (belt-and-suspenders; the tuple is already dynamic but catches future hardcoding attempts).

### `coaches/adaptation_hint.py` line 37
```diff
-SUPPORTED_MODES = ("sr_draft", "sr_ranked", "aram", "arena", "brawl")
+from lib.modes import PHASE3_MODES as SUPPORTED_MODES
```

### `agents/agent4_coach_mentor/analyzer.py` line 40
```diff
-SUPPORTED_MODES = ("sr_draft", "sr_ranked", "aram", "arena", "brawl")
+from lib.modes import PHASE3_MODES as SUPPORTED_MODES
```

### `agents/agent2_backend/pipeline/orchestrator.py` line 66
```diff
-SUPPORTED_MODES = ("sr_draft", "sr_ranked", "aram", "arena", "brawl")
+from lib.modes import PHASE3_MODES as SUPPORTED_MODES
```

### `agents/agent3_testing/suite/test_supervisor.py` line 21
```diff
-MODE_DBS = ["sr_draft.db", "sr_ranked.db", "aram.db", "arena.db", "brawl.db"]
+from lib.modes import PHASE3_MODES
+MODE_DBS = [f"{m}.db" for m in PHASE3_MODES]
```
The existing assertion `assert data["db"]["files"] == MODE_DBS` (line 38) is unchanged and
continues to validate the round-trip from JSON → PHASE3_MODES → MODE_DBS → JSON.

### `agents/supervisor.py`
- Added top-level import: `from lib.modes import verify_modes as _verify_modes`
- Added call in `Supervisor.start()` immediately after `_verify_decisions_version()`:
  ```python
  # AUDIT P-audit4-m02: assert PHASE3_MODES still matches db.files.
  _verify_modes()
  ```

## Verification

```
$ python -c "from lib.modes import PHASE3_MODES, verify_modes; print(PHASE3_MODES); verify_modes(); print('OK')"
('sr_draft', 'sr_ranked', 'aram', 'arena', 'brawl')
OK

$ python -c "
from coaches.adaptation_hint import SUPPORTED_MODES as A
from agents.agent4_coach_mentor.analyzer import SUPPORTED_MODES as B
from agents.agent2_backend.pipeline.orchestrator import SUPPORTED_MODES as C
from agents.agent3_testing.suite.test_supervisor import MODE_DBS
from lib.modes import PHASE3_MODES
assert A == B == C == PHASE3_MODES
assert MODE_DBS == [f'{m}.db' for m in PHASE3_MODES]
print('All consistent.')
"
All consistent.
```

## Backward compatibility

All four consumer sites retain the name `SUPPORTED_MODES` (aliased via `as`), so call-sites within
each module (`_db(mode)`, `for m in SUPPORTED_MODES`, argparse `choices=list(SUPPORTED_MODES)`)
require no further changes.  `MODE_DBS` in the test file remains a list (not a tuple) to match the
JSON array type that `test_resolved_decisions_written` compares against.

## Status

COMPLETE — no frozen files touched, no restart required.
