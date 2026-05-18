# Task Report - P-audit3-m01: Supervisor charter-fail-loud

- **Task id:** `t-2854f3be403b`
- **Operation:** `apply-proposal-p-audit3-m01-charter-fail-loud`
- **Agent:** agent2 (Backend / Charter)
- **Completed:** 2026-04-22T14:22:47Z
- **Result:** NO-OP - fix already applied

## Finding

`agents/supervisor.py` lines 476–496 already contain the full fix described in
proposal P-audit3-m01.  The code was applied (presumably by an earlier agent
session) and includes:

1. **Audit comment** (lines 476–479) explicitly citing P-audit3-m01 and the
   rationale (missing-charter spawns silently widen authority, burn budget).

2. **`EphemeralStubNotWired` raise - file missing** (lines 483–486):
   ```python
   if not charter_path.exists():
       raise EphemeralStubNotWired(
           f"charter missing for agent{agent} at {charter_path}"
       )
   ```

3. **`EphemeralStubNotWired` raise - file unreadable** (lines 489–492):
   ```python
   except OSError as e:
       raise EphemeralStubNotWired(
           f"charter unreadable for agent{agent} at {charter_path}: {e}"
       ) from e
   ```

4. **`EphemeralStubNotWired` raise - file empty** (lines 493–496):
   ```python
   if not charter.strip():
       raise EphemeralStubNotWired(
           f"charter empty for agent{agent} at {charter_path}"
       )
   ```

All three cases route through the existing H3 dispatcher path that calls
`Scheduler.fail()`, keeping the task visible with a `failed` status rather than
silently completing or spawning without scope constraint.

## Verification

- `EphemeralStubNotWired` docstring (lines 397–404) updated to clarify retained
  uses: CLI-missing and the explicit no-charter guard.
- `--append-system-prompt` is only omitted when `charter == ""` (i.e., agent
  has no entry in `AGENT_CHARTERS`), which is intentional for unchartered
  utility agents.  Any agent *with* a declared charter path now hard-fails
  before reaching the subprocess build.

## Status

**CLOSED - already shipped.** No code changes required in this session.
