# Proposal M-05 - Game-PC SMB push surface is deadcode post ADR-011/012

- Severity: medium
- Filed by: Agent 6 (eleventh audit)
- Owner: Agent 1 (decision) -> Agent 2 (execution, if Path A)
- Source report: `agents/agent6_auditor/reports/20260628-081728-eleventh-audit-phase3.md`

## Context

Game-PC retired from the live pipeline 2026-05-29 (ADR-011, item 215).
RC<->Peer cross-Claude bridge decommissioned 2026-06-24 (ADR-012, commit
49b1c9ea). The receiving end of `\\192.168.8.237\RCClient\*` is no longer
in topology. The push module + the gatekeeper UNC guard + multiple
charters still document and exercise the path as live.

## Touched surface

- `agents/agent2_backend/smb_push.py` (`SHARE_UNC = r"\\192.168.8.237\RCClient"`).
- `agents/agent0_gatekeeper/evaluator.py` (P-audit-h1 UNC defense).
- `agents/agent3_testing/suite/test_quality_pass.py` (imports
  `_sanitise_label`).
- Charter refs in:
  - `agents/agent2_backend/charter.md` ("Cross-machine push (smb_push.py)").
  - `agents/agent3_testing/charter.md` (`share_reachable()` skip-gate).
  - `agents/agent5_ui/charter.md` (`smb_push.push(local, remote_subdir='web', ...)`).
  - `agents/agent6_auditor/charter.md` ("never write to
    `\\192.168.8.237\RCClient\*`" - still factually correct but
    rationale shifted from "read-only peer" to "no longer exists").

## Path A - mark deprecated, defer delete (mirror Brawl-retirement pattern)

Mirrors s214 Brawl retirement (operator-blessed pattern: retired-from-flow
but backend left as deadcode for a separate cleanup pass).

1. Module docstring `smb_push.py` head: ADR-011/012 deprecation note,
   `raise RuntimeError("Game-PC SMB share retired ADR-011/012; reach the
   Legion :8888 dashboard instead")` from `push()`.
2. Skip-gate `share_reachable()` always returns `False`; tests stay
   green via the skip-path.
3. New `resolved_decisions.json` entry `phase3-d026`:
   "Game-PC SMB push deadcode pending cleanup pass (ADR-011/012)".
4. Charter lines in agents 2/3/5 updated to point at "Legion local
   filesystem - cross-machine push retired".
5. Agent 6 charter L16 reworded: "No cross-machine writes (Game-PC
   retired ADR-011, bridge decommissioned ADR-012)".

## Path B - delete now

1. Delete `agents/agent2_backend/smb_push.py`.
2. Delete P-audit-h1 guard + the test that exercises it.
3. Delete `test_quality_pass.py` import.
4. Strip the charter references in agents 2/3/5.
5. Add a SETTLED entry in resolved_decisions noting the deletion.

Path B is cleaner but loses the safety net of the gatekeeper UNC guard,
which was filed as a class-1 defense ("defends the share even when
callers bypass smb_push"). With the share gone there is nothing to
defend, but the guard pattern itself is documented in `agents/agent6_auditor/reports/20260422-095110-first-audit.md`
as a P-audit-h1 outcome.

## Recommendation

Path A (defer-delete). Matches the Brawl precedent. Lets a future
quiescent-point cleanup pass remove the module + tests + charter lines
in one swing, after the operator confirms no archive flow still needs
the symlink.

## Acceptance criteria

- `resolved_decisions.json` gains `phase3-d026` (or equivalent) entry.
- `share_reachable()` returns `False` everywhere; CI is still green.
- Charter docs for agents 2/3/5/6 reflect the post-ADR-012 reality.
- Future `grep -rn "192.168.8.237" agents/ ops/ tools/` returns ZERO
  hits in production code (charter text only).
