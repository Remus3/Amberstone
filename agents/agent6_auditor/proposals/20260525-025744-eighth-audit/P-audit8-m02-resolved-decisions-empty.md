# P-audit8-m02 - resolved_decisions.json has version stamp but empty decisions array

- **Severity:** MEDIUM
- **Owner:** Agent 1 (charter-level decision)
- **Source:** `20260525-025744-eighth-audit-phase3.md` M-02
- **File:** `agents/state/resolved_decisions.json`

## Observed

```
version: phase3-1.1
len(decisions): 0
```

Agent 6 charter (line 19-21): "Read. Don't guess.
`agents/state/resolved_decisions.json` is the source of truth for
locked decisions; any code that drifts from it is a finding."

Every prior audit's drift check has run against a vacuous spec.

## Proposed (operator-gated decision fork)

Pick ONE:

### A. Backfill the decisions document

Promote the locked items in CLAUDE.md "Settled - do not re-litigate"
into structured JSON entries. Candidates:

- ADR-006 Riot API key policy (key permitted, file location, gotchas)
- ADR-008 unified asset-hash (no RC restart for `web/{js,css}/panels/*`)
- Frozen-file list (`main.py`, `core/log_setup.py`, `core/moon_proxy.py`,
  `lcu/lcu_client.py`, `core/game_snapshot.py`, `ops/rc_dev_runtime.py`,
  `ops/rc_supervisor.py`, `app/__init__.py`, `app/_loop.py`,
  `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`,
  `app/_game_lifecycle.py`, bridge tool set)
- DS conditional arc operator-CLOSED (s232)
- No em-dash hard rule
- Atomic-write-only / `tmp.write_text -> tmp.replace`

After backfill, future audits have a real spec to drift-check against.

### B. Revise the charter

Drop the source-of-truth claim from charter line 19-21 and adopt
CLAUDE.md as the operating substrate. Honest but loses the
structured-JSON spec capability.

## Recommendation

**A.** The substrate exists (CLAUDE.md is curated by the operator and
re-read every session); promoting it into structured JSON costs one
session and gives audit 9+ teeth. B is the give-up option.

## Estimated cost

Option A: ~1 session to extract + normalize 10-15 locked items into
the existing schema (assumed `{id, source, locked_at, summary,
authority}` shape based on `version: phase3-1.1` stamp).
