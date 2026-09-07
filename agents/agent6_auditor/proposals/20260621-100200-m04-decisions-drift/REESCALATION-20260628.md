# M-04 re-escalation - eleventh audit (2026-06-28)

Audit-10 (2026-06-21) filed phase3-d021 (ADR-011 1-PC), phase3-d022
(101.qq.com live-wire), phase3-d023 (DS live truth) in `PROPOSAL.md`.
Agent 1 has not applied; the file is still version `phase3-1.1`,
`locked_at` 2026-04-22.

In the 7 days since audit-10 the drift has grown by TWO MORE entries
which should be folded into the same bump:

## Additional drafts

```jsonc
{
  "id": "phase3-d024",
  "title": "ADR-012 RC<->Peer cross-Claude bridge decommissioned",
  "decided_at": "2026-06-24",
  "summary": "Commit 49b1c9ea removed dashboard/routes_health_peer.py, the entire ops/runtime/peer_health/ folder, every bridge_watcher_*.py polling tool, and the core.bridge.send() outbound route. Charter line 'no cross-machine authority - never write to \\\\192.168.8.237\\RCClient\\*' still holds, but the rationale is now 'Game-PC + Peer peers no longer exist in the topology', not 'peer is read-only'. /api/health/all no longer carries a peers block; agent6 + supervisor + DS rollup remain. Do NOT re-pitch a bridge revival - operator-decided closure.",
  "source": "CLAUDE.md / Settled / ADR-012 + commit 49b1c9ea",
  "authority": "operator"
},
{
  "id": "phase3-d025",
  "title": "Overlay all-panels doctrine + click-through interactivity (ledger 644-648)",
  "decided_at": "2026-06-27",
  "summary": "rc-shell overlay: every panel individually accessible with per-panel opacity/scale; panel-set abstraction retired (commit b16bfce1). 3 panels stay interactive while playing via passive click-through zones (commit c79508d2). Draggable launcher widget acts as layout control center (commit 6370f7da). Enemy-spell tap-tracker + API stats mini-panel landed (commit 5ff56099). cd-ledger CSS contract codified for the all-panels doctrine (commit 9bb382dd). In-game ACTIVE hotkey routes through tools/hotkey_listener.py Win32 + signal file (Electron globalShortcut dead under League focus). Do NOT re-pitch a single-panel or panel-set design.",
  "source": "CLAUDE.md / Settled / overlay redesign + ledger 644-648",
  "authority": "operator"
}
```

## Header bump

- `"version": "phase3-1.2"`
- `"locked_at": "2026-06-28"`

## Companion code change

- `agents/_supervisor_common.py` `EXPECTED_DECISIONS_VERSION = "phase3-1.2"`.

## Why this matters

Charter L18 ("`resolved_decisions.json` is the source of truth for
locked decisions; any code that drifts from it is a finding") is
structurally weaker with every elapsed week the file stays at
2026-04-22. Audit-11 cannot cite the file to flag drift because the
file itself drifts further than any code does. M-04 has now been open
across audits 10 and 11 unresolved.

## Recommended sequencing

One slice covers all five entries (d021..d025) + the version bump + the
companion `_supervisor_common.py` constant. Agent 1 owns the apply.

## CLOSURE (appended 2026-06-28, post-item-651)

SUPERSEDED - M-04 was applied 11 minutes after this re-escalation was
filed. Item 651 (work commit `68e08265`, ledger e37d7e7e) appended
d021..d025 to the runtime `agents/state/resolved_decisions.json` and
advanced `locked_at` -> 2026-06-28; count 20 -> 25. See
`APPLIED-20260628.md` for the full disposition.

The `version` field was kept at `phase3-1.1` DELIBERATELY, not skipped:
the phase3-1.2 bump asked for here is INCOMPLETE and would brick RC boot.
`EXPECTED_DECISIONS_VERSION` is fail-closed-validated (RuntimeError on
mismatch) in three sites this note never named - the FROZEN
`ops/rc_supervisor.py`, `agents/_supervisor_common.py:43`, and the pinning
test `agents/agent3_testing/suite/test_supervisor.py:36` (asserts
`== "phase3-1.1"`). A bare JSON version bump mismatches that validator so
the supervisor refuses to boot. Appending decision entries is
schema-compatible at 1.1 (both validators + the test stay green). The
formal 1.2 migration touches a frozen file and was operator-DECLINED.

Do NOT re-escalate M-04 - it is CLOSED.
