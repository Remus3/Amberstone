# Agent 6 - Twelfth Audit (Phase 3 repo pass)

- **Date:** 2026-07-05 20:15 UTC (cron `t-39e957eb0cf8`)
- **Auditor:** Agent 6 (Opus 4.7, ephemeral, $3.00 spawn budget)
- **Scope:** Closure of audit-11 M-05, recency pass on the 428 commits
  between 2026-06-28 and 2026-07-05 (vision-OCR hardening, overlay
  drain, R77-R81 DS scorer waves, home mode-tabs, insights ORUN
  slices).
- **Follows:** `20260628-081728-eleventh-audit-phase3.md`.

## Live-state snapshot

- RC supervisor: pid 25408 alive=True last_reload_ok=true mode=game
  (operator IN game at probe time).
- Vision: alive=True (in-process :8889).
- Daemon Slayer: ENGINE 1.181.0 (was 1.154.0), patch 16.13.1 - 13
  engine bumps in one week (R77 crit-DR, R78 ARAM item_extra, R80
  basic-attack-DR, R81 phase-strength, plus HZ retomps).
- agent6 health block: status=green, last_outcomes len=3 with the
  most recent = t-fbcd49d7b4f0 completed 2026-06-28 08:20. The
  green rollup is correct - no 2-in-a-row-failed pattern.
- `agents/state/resolved_decisions.json`: version phase3-1.1,
  locked_at 2026-06-28, **26 decisions** (was 20). REFRESHED - the
  audit-11 M-04 finding is CLOSED: the file went from 67-days-stale
  to 7-days-stale in the interval, and picked up d021 (ADR-011),
  d022 (101.qq.com), d023 (DS live truth), d024 (ADR-012), d025
  (overlay all-panels), d026 (Game-PC SMB deadcode).

## Closure verification - audit-11 findings

### M-04 resolved_decisions.json drift - **CLOSED**

The file now carries decisions d021-d026 covering every settled
2026-05-19 -> 2026-06-28 topic that audit-11 flagged. Version pin
phase3-1.1 unchanged; locked_at bumped 2026-04-22 -> 2026-06-28.
No code drifts from any of the 26 decisions on a spot-check
(1-PC topology, 101.qq.com live-wire kill-switch, DS live-truth
accessor, bridge removal, overlay doctrine).

### M-05 Game-PC SMB push deadcode - **d026 ENFORCED, cleanup deferred**

Operator picked "Path A - defer-delete" and encoded it as d026:
- `agents/agent2_backend/smb_push.py:73` `share_reachable()`
  hard-returns False (no network probe).
- `push()` at line 146 raises `RuntimeError(_RETIRED_MSG)`
  BEFORE any live filesystem code; the historical body is
  preserved unreachable.
- `trigger_forwarder_restart()` at line 212 mirrors the same
  guard.
- No live import of `smb_push` in the runtime tree
  (`grep -rn "from agents.agent2_backend.smb_push"` finds only
  `agents/agent0_gatekeeper/evaluator.py` DOCSTRING references,
  no actual imports). The traversal guard in
  `agents/agent0_gatekeeper/evaluator.py:125-157` is kept as
  d026 specified.
- Charter line 16 in `agents/agent6_auditor/charter.md` documents
  the retirement. `_audit_probes.py` still references
  `192.168.8.237` UNC paths in its test fixtures - those are
  probe cases for the KEPT traversal guard, not live push
  attempts, so leave them.

Deferred cleanup (single deletion swing) remains queued per d026;
NOT re-escalated this pass - operator decision stands.

## New findings

### L-01 `vision_profiles.save_profile` accepts unvalidated `base` - **low, autonomous fix filed**

- **Location:** `core/vision_profiles.py:93-108` and its caller
  `dashboard/routes_vision_calibrator.py:214-227`.
- **What:** `_save_profile_from_body` validates the `regions`
  dict via `validate_regions()` (good: type + shape + range +
  monotonicity) but forwards `body.get("base")` untouched to
  `vp.save_profile(ck, clean, base)`. `save_profile` does
  `list(base)` and writes whatever iterable it receives.
- **Why it is wrong:** A malformed `base` (None, non-iterable,
  strings, negative or huge ints, wrong length) persists into
  the profile file and later becomes divisor state in
  `_scale_regions()` if a legacy_seed fallback ever reads it.
  Today the legacy-seed reader in
  `_profile_regions_payload():194-196` has defensive `if base
  and base[0]` / `if base and len(base) > 1 and base[1]` guards
  so a zero survives without a div-by-zero, but the invariant
  is fragile - a future reader without the same guard will
  crash or scale wrong.
- **Fix (concrete):** Add a `validate_base(base)` in the same
  module accepting only `[int|float, int|float]` with each
  coord in `(0, 10000]`. Return 400 from
  `_save_profile_from_body` before calling `save_profile` if
  the base is malformed. No breaking change to well-behaved
  clients; the calibrator page always sends `[width, height]`
  from the frame payload.
- **Fix action:** filed as a proposal for Agent 2 backend since
  the seam is under `core/` + `dashboard/` and the caller
  contract needs a matching route change. See
  `agents/agent6_auditor/proposals/20260705-201555-l01-vision-base-validation/`.

### I-01 DS engine bumps per week - **info, no action**

13 engine bumps between 1.154.0 and 1.181.0 in 7 days is normal
scorer-wave cadence (R77-R81 series) and the `current.txt` +
`/health` accessor pattern (d023) is holding - no stale-engine
finding on any coach output spot-check. Flagging for context
only; the pace validates the "live truth = /health" doctrine.

### I-02 no red audit runs since 2026-06-15 - **info, healthy**

t-9061a61f1ef1 is the only red outcome in `last_outcomes` and it
is 20 days old. The audit-10 C-01 stub mechanism landed
2026-06-21 so any future claude-exit-non-zero will now write a
failure stub. No red pattern to escalate.

### I-03 vision-calibrator surface hardening - **info, no action**

New `dashboard/routes_vision_calibrator.py` (dc1da7fd + dbc8c504)
is properly locked down for a :8888 tailnet endpoint:
`validate_regions` rejects zero-area / off-canvas / non-numeric
crops before disk touch; atomic write with a 3-attempt
`os.replace` PermissionError retry (matches the
`reference_os_replace_winerror5` guard); no raw exception text
leaks to the client; config_key sanitized via
`_safe()`:`re.sub(r"[^A-Za-z0-9._-]", "_", ...)[:120]` blocks
path-traversal via the profile key. The dedicated tests
`tests/test_vision_calibrator_routes.py` +
`tests/test_vision_calibrator_profile.py` +
`tests/test_vision_profiles.py` back the shape.

## Follow-up tasks filed to Agent 1

- `L-01` -> task **t-4802b906f485** (owner Agent 2, priority 200,
  op `implement-l01-vision-base-validation`). Proposal directory
  `agents/agent6_auditor/proposals/20260705-201555-l01-vision-base-validation/`
  carries the unified diff + test list.

## Summary

- Audit-11's two M-tier findings both closed (M-04 by the
  decisions-refresh on 2026-06-28, M-05 by the d026 enforcement).
- One new low-severity finding on the new vision-calibrator
  surface, proposal filed.
- No critical / high / medium findings this pass.
- Agent 6 status: green.
