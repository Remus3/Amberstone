# M-01 audit - 2026-07-27T19:50Z (agent6, task t-f74e954a7532)

Reviewer: agent6 ephemeral (opus-4-7). Source task: t-f19b4cb85b1d.
Target: `agents/state/resolved_decisions.json`.
Verdict: **APPROVE WITH REVISIONS** (do not apply as-written).

## Drift claims - both CONFIRMED against disk

- **Locus 1 = topology decision.** File line 86-91 carries the stale
  3-machine summary (Legion + Game-PC + Peer peers, bridge live). Drift
  is real. **ID mis-cite:** proposal names this `phase3-d008`; on-disk
  `phase3-d008` (line 62) is the py_compile-gate decision. The topology
  entry is `phase3-d011` (line 86, title "Tailnet topology - 3
  machines, prefer tailnet hostnames").
- **Locus 2 = `cross_machine` appendix (lines 384-393).** Fields
  `share_unc / writable_zones / credential_store / auth_user /
  forwarder_restart_signal` all still describe `\\192.168.8.237\RCClient`
  SMB pipe as an operating parameter. Drift is real. **ID mis-cite:**
  proposal names supersession `phase3-d020`; on-disk d020 is the
  framework-version pin. The relevant supersessions actually on-disk
  are `phase3-d021` (ADR-011, 2026-05-29), `phase3-d024` (ADR-012,
  2026-06-24), and `phase3-d026` (SMB push deadcode pending cleanup,
  2026-06-28).

## Blocking issues before Agent 2 applies

1. **Correct the two decision IDs in the PROPOSAL.md diff sketch:**
   - `phase3-d008` -> `phase3-d011`
   - `phase3-d020` -> `phase3-d026` (or list d021 + d024 + d026 as the
     supersession chain).
2. **Do NOT touch the `"version"` field** of the JSON. M-04 CLOSURE
   (2026-06-28) records that `EXPECTED_DECISIONS_VERSION` is fail-closed
   at three sites, one of them FROZEN (`ops/rc_supervisor.py`), and a
   bare bump bricks RC boot. The current M-01 diff does not touch it,
   good; keep it that way.
3. **Update the seed generator in the SAME slice.** `ops/phase3_setup.py`
   lines 153-162 still emit the old `cross_machine` shape into a freshly
   seeded file. If the seed ever re-runs (any Phase 3 reset) the drift
   returns. Slice must land: (a) live JSON edit + (b) seed literal edit
   matching. `ops/phase3_summary.py:259` prints hardcoded old strings
   too - fold into the same slice.
4. **`*_historical` rename risk.** The proposal argues the rename is
   intentional "to flush dead consumers." Grep-of-record BEFORE commit:
   - `resolved_decisions.json["cross_machine"]["share_unc"]` has no live
     reader in `agents/` or `dashboard/` (empty search); the appendix
     is currently vestigial. Safe to rename.
   - `agents/agent0_gatekeeper/target_allowlist.json` and
     `agents/agent2_backend/smb_push.py` also carry a `share_unc` -
     **separate keyspace**, own file, own consumers. Not this slice.
     They fall under the `phase3-d026` future cleanup pass; do NOT
     collapse them into M-01.

## Preferred shape (nit, not blocking)

Rather than rewriting the d011 summary text in place and losing the
audit trail, append a `superseded_by` field and preserve the historical
text. Example:

```jsonc
{
  "id": "phase3-d011",
  "title": "Tailnet topology - 3 machines, prefer tailnet hostnames",
  "decided_at": "2026-04-22",
  "superseded_by": ["phase3-d021", "phase3-d024"],
  "summary": "SUPERSEDED 2026-05-29 by phase3-d021 (ADR-011 1-PC) and 2026-06-24 by phase3-d024 (ADR-012 bridge decom). Historical: ..."
}
```

This keeps the char-diff small and machine-readable (`superseded_by`
is a stable pattern any future auditor can key off; a text-only
rewrite is not).

## Verification hooks the applier must run

- `python -c "import json; json.load(open(r'agents/state/resolved_decisions.json'))"` parses (baseline confirmed 19:50Z).
- Full Agent 3 supervisor pin test (`agents/agent3_testing/suite/test_supervisor.py`) stays green (asserts `version == "phase3-1.1"` - do NOT bump).
- `git grep -nE 'cross_machine[^\w]*(\.|\[)["'\'']?share_unc'` under `agents/` and `dashboard/` returns empty. (Confirmed empty this session.)
- After edit, re-run agent6 audit-probe suite:
  `agents/agent6_auditor/_audit_probes.py`.

## Disposition

- **Recommendation to Agent 1:** dispatch to Agent 2 for apply, but
  ONLY after the PROPOSAL.md diff is edited to fix the two ID mis-cites
  and to add `ops/phase3_setup.py` + `ops/phase3_summary.py` as
  co-slice targets.
- **Autonomous?** No - stays outside agent6 autonomous scope (charter
  L11-14). Requires operator approval + Agent 2 hands.
- **Severity confirmed:** high (truth-source drift; the auditor's own
  contract weakens each week the file lags).

--
End of audit.
