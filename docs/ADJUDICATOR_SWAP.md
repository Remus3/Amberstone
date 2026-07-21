# Adjudicator swap - Gemini to local Claude

The autonomous headless loop has an external "brain" that does two jobs each
cycle: DIRECTOR (reads repo state, writes the next directive) and AUDITOR
(reads the cycle's diff, returns CLEAN or REGRESS). That brain was hard-wired
to the Gemini CLI. It is now a pluggable ADJUDICATOR with two backends, so
losing Gemini credits is a config event rather than a rebuild.

The brain never writes files. It DECIDES and DIRECTS; the Claude executor
cycle does every write. That is true of both backends and is enforced by the
permission mode each one is invoked with.

## The swap, three ways

**1. Automatic - the expected path. No operator action.**
When the active backend returns nothing AND its stderr carries a credit or
quota exhaustion signature, the controller:

- logs `ADJUDICATOR FAILOVER: gemini -> claude (reason: <signature>)`
- atomically writes `ops/loop/control/adjudicator_active.txt` with the new
  backend, so the state survives a controller restart and is visible at a glance
- RETRIES THE SAME director or auditor call on Claude, so the cycle is not lost
- stays on Claude for the rest of the run

Signatures that trigger it: `quota`, `exhausted`, `insufficient credit`,
`out of credit`, `billing`, `top up`, `429`, `RESOURCE_EXHAUSTED`.

A `503` / `unavailable` / overload does NOT trigger it. That is deliberate:
`gemini-3-pro-preview` 503-overloads for hours at a time and once caused a
9-hour outage. Treating a transient overload as exhaustion would swap vendor on
a blip. The existing 3-plus-2 retry ladder still absorbs those.

**2. Manual - one key.**
Set `"adjudicator": "claude"` in `ops/loop/config.json` and relaunch. That is
the entire swap.

**3. Mid-run, without a relaunch.**
Write the backend name into `ops/loop/control/adjudicator_active.txt`. The
controller reads it at cycle boundaries.

## Why Claude adjudicator spend is not metered

`ceiling_usd` (default 200) exists as a runaway backstop on the METERED vendor.
The operator has declared Claude spend uncapped, so
`claude_adjudicator.count_against_ceiling` defaults to `false`. Without that,
swapping backends would silently inherit Gemini's dollar rail and stop the run
partway through - a stop condition that would look like a bug, not a budget.

Note the asymmetry: with Gemini gone, `max_cycles` becomes the only real
limiter. That is intended.

## Config keys

All additive with behavior-preserving defaults. A `config.json` that predates
this seam still runs the old path exactly.

| key | default | meaning |
|---|---|---|
| `adjudicator` | `gemini` | active backend |
| `adjudicator_fallback` | `claude` in the shipped config, empty in code | failover target |
| `adjudicator_failover` | `true` | arm automatic failover |
| `claude_adjudicator.cmd` | the npm `claude` shim | CLI to invoke |
| `claude_adjudicator.model` | see config | model for director + auditor |
| `claude_adjudicator.timeout_sec` | see config | per-call timeout |
| `claude_adjudicator.count_against_ceiling` | `false` | see above |

The code default for `adjudicator_fallback` is deliberately EMPTY while the
shipped config carries `claude`. A pre-seam config must never swap vendor on a
429 it was written before anyone imagined. Every real launch reads the shipped
config, so the capability is armed in practice.

## Bridge liveness

The AutoHotkey bridge rewrites `ops/loop/control/ahk_heartbeat.txt` with a bare
unix-epoch-seconds integer roughly once per second, temp-then-move so a
mid-write read yields the previous value and never a truncated one. The
heartbeat continues mid-directive, chunked into sub-second slices, so a long
directive does not read as a dead bridge.

The controller treats a heartbeat older than 60 seconds as stale and logs
`AHK BRIDGE STALE (<n>s)` immediately, instead of burning the full
`cycle_deadline_sec` of 5400 seconds - 90 minutes of dead air per hang. It is
advisory: the deadline logic still decides when to stop.

## After a swap - verify

1. `ops/loop/control/controller.log` shows a `ADJUDICATOR FAILOVER` line or the
   backend named at loop start.
2. `ops/loop/control/adjudicator_active.txt` names the expected backend.
3. The next `ops/loop/control/directive.md` is well-formed and ends with the
   `done_sentinel.py` FINAL STEP line. A malformed directive is the first
   symptom of a backend whose prompt contract is not being honored.
4. `ops/loop/control/budget.json` carries `adjudicator` and `adjudicator_usd`
   alongside the legacy `gemini_usd` key.

## Rollback

Set `"adjudicator": "gemini"`, delete
`ops/loop/control/adjudicator_active.txt`, relaunch. Failover state is
per-run and does not persist across a clean launch, because
`launch_loop.ps1` pre-cleans that marker.

## What did NOT change

Director and auditor prompt contracts, the output-token contracts (a directive
or the literal `NO_WORK`; a `VERDICT:` first line), the empty-output-is-never-a-
usable-answer sentinel, the UTF-16 stderr decode that once masked a real API
error behind NUL-interleaved warnings, the Gemini retry ladder, and the
`gemini_usd` budget key.
