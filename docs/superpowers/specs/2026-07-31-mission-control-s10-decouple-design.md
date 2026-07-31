# Mission Control S10 - decouple from the RC dashboard

- **Status:** design APPROVED by operator 2026-07-31. Not yet implemented.
- **Parent spec:** `docs/MISSION_CONTROL_PLAN.md` (S1-S9 as shipped; S10 decisions).
- **Blast radius:** Tier-2. New process, new port, new auth surface, route
  de-registration from the live dashboard, 159 tests relocated or re-pointed.

## Operator requirement, verbatim 2026-07-31

"i want to have this mission control to be separate away from the RC game
overlay : and accessible remotely via ip or something . that way when someone is
changes on the rc game overlay and dashboard - the mission control is not
affected."

## Why - the coupling is measured, not stylistic

Mission Control is a settings card inside the RC game dashboard and shares FOUR
failure domains with the thing it controls:

| Coupling | Where | Consequence |
|---|---|---|
| Same process | `web_dashboard.py` `:8888`, supervisor-managed | an RC restart for an overlay change bounces Mission Control too |
| Same dispatch table | `dashboard/_dispatch.py:147` + `:210` | a fault in dispatch takes the control plane with it |
| Same JS bundle | `web/js/panels/dev.js` (1286 lines, mostly game concerns) | one scope error anywhere in that file kills Mission Control |
| Same page | `#loop-status-body` in `web/index.html` | the control plane is only reachable by loading the whole game dashboard |

**S9 demonstrated row 3 for real.** A single `mk` ReferenceError in `dev.js` -
game-dashboard code, not Mission Control code - left the INTERRUPT victim list
unrendered while the armed kill button still displayed. The most
safety-critical element of the control plane was broken by proximity to
unrelated UI code.

The reverse direction is equally real: Mission Control is the surface you reach
for WHEN the dashboard is misbehaving, and today it dies with it. A control
plane that shares a failure domain with the thing it controls is not a control
plane.

## Decisions - RESOLVED by operator 2026-07-31

| # | Question | Decision |
|---|---|---|
| 1 | Port | **8895**. Measured free (in use: 8888, 8889, 8890, 8891, 8893, 8894, 8901). |
| 2 | Auth | **Bearer token, POST-only.** GET stays open behind the bind scope. |
| 3 | Bind scope | **Tailnet + loopback only** - `100.70.22.55` and `127.0.0.1`. LAN `192.168.8.x` cannot reach it. |
| 4 | Lifecycle | **Own scheduled task `RC-MissionControl`** (ONLOGON). Not a `rc_supervisor.py` entry - that file is frozen AND it would re-couple both processes to one watchdog. |
| 5 | Old dashboard card | **Removed entirely, no link left behind.** |

## Architecture

### Process

New root entry `mission_control.py` plus a new `mc/` package:

```
mission_control.py   entry point; pythonw-safe, no console
mc/__init__.py
mc/server.py         bind + TLS + serve_forever
mc/handler.py        minimal BaseHTTPRequestHandler - _send, JSON body read,
                     static serve from web/mc/, dispatch to the route tables
mc/auth.py           bearer-token resolution + the POST gate
mc/routes.py         GET/POST tables assembled from the EXISTING route modules
```

`web_dashboard.py` is untouched. `main.py` is untouched. Neither process imports
the other.

### Route reuse - zero fork

`mc/routes.py` imports `dashboard.routes_loop_status` and
`dashboard.routes_loop_control` **directly**. The handler contract is already
minimal and portable: a route is `(matcher, handler)`, the handler is called
with an object exposing `_send(status, body_bytes, ctype)` and, for POST, the
parsed JSON body. `tests/test_loop_status_route.py` already exercises the routes
against a 6-line `FakeHandler`, which is the proof that the contract does not
require the dashboard's `Handler`.

All control-plane LOGIC stays in `ops/loop/*` (lanes, launcher, steer,
interrupt, intents). S10 moves the SERVING layer only. Nothing is duplicated;
there is no second copy of anything to keep in sync.

### The dependency budget - and the one dashboard edit

The two route modules import `equals` from `dashboard._dispatch`. Importing
`_dispatch` pulls in `dashboard.api_schema` and `pydantic` at module level,
which would leave Mission Control sharing a failure domain with dashboard schema
code - a quiet re-coupling that defeats the point.

**Fix:** extract the two matcher factories into a new stdlib-only
`dashboard/_matchers.py`:

```python
def equals(path): ...
def prefix(p): ...
```

`dashboard/_dispatch.py` re-exports both, so all 40-plus existing route modules
are unchanged and no other caller churns.

Verified structural fact that makes this work: `_dispatch.py` imports the game
route modules **lazily**, inside the `_GET_CACHE` / `_POST_CACHE` builder
functions, not at module level. Nothing in the game route tree is reachable from
an `mc/` import.

Resulting Mission Control dependency set on `dashboard/`:

| Module | Imports |
|---|---|
| `dashboard/_matchers.py` | stdlib only (new) |
| `dashboard/_errors.py` | `json` |
| `dashboard/_idempotency.py` | stdlib only |
| `dashboard/routes_loop_status.py` | the three above |
| `dashboard/routes_loop_control.py` | the three above |

No pydantic. No `api_schema`. No game routes. No `Handler`. No `_context`, no
`builders`, no `_state_builder`.

### TLS and reachability

Reuses the existing mkcert material at `ops/tls/rc.pem`. The SAN list in
`tools/regen_rc_cert.ps1` already carries `localhost`, `legion-rc`,
`legion-rc.tailc150de.ts.net`, `127.0.0.1`, `192.168.8.230`, `100.70.22.55`.

**A SAN is host-scoped, not port-scoped, so `:8895` needs NO cert regen.**
`https://legion-rc:8895/` and `https://100.70.22.55:8895/` both validate against
the same cert Legion already trusts. `-k` is not used and not acceptable here.

Bind is explicit and narrow: sockets on `127.0.0.1` and `100.70.22.55` only. The
dashboard's dual-stack wildcard bind is deliberately NOT copied - a wildcard
bind would silently expose the control plane on the LAN.

### Auth contract

```
POST  /api/loop-control     Authorization: Bearer <token>   REQUIRED
GET   /api/loop-status      open (bind scope is the perimeter)
GET   /  , /mc.css, /mc.js, /arm_confirm.js                 open
```

Token resolution mirrors `core/vision_token.py`, first hit wins:

1. env `RC_MC_TOKEN`
2. `config/mission_control_token.txt` (first line, stripped)

**No hardcoded fallback.** If neither source yields a token, every POST is
refused with **503** and a plain message - it must NOT fall open. This is the
inverse of the usual fail-soft rule and is deliberate: a control plane that can
kill processes fails CLOSED.

Failure codes:

| Condition | Status | Body |
|---|---|---|
| no token configured on the server | 503 | `{"ok": false, "error": "auth not configured"}` |
| missing or malformed header | 401 | `{"ok": false, "error": "unauthorized"}` |
| wrong token | 401 | same body (no oracle) |

Comparison uses `hmac.compare_digest`. The token is never logged, never echoed
in a response, and never placed in a URL or query string.

Client: the page prompts once, stores the token in `localStorage` under
`rc_mc_token`, and sends it on every POST. A 401 clears the stored value and
re-prompts. A 503 renders "auth not configured on the server" and disables every
control - it does not retry.

### Asset tree

New, self-contained, importing no game code:

```
web/mc/index.html           the whole control plane page
web/mc/mc.css               lock rows, lane rows, arm/confirm, INTERRUPT block
web/mc/mc.js                the renderer - moved from dev.js
web/mc/arm_confirm.js       moved from web/js/lib/ (already pure and portable)
web/mc/arm_confirm.test.mjs moved WITH it - the `node --test` suite for the
                            pure arm/confirm logic. Leaving it behind would
                            orphan the only real coverage of that module.
```

No `main.js`, no `header.css`, no design-token file shared with the dashboard.
Tokens the page needs are inlined in `mc.css`. This is the one place a small
amount of CSS duplication is accepted on purpose: sharing a stylesheet with the
dashboard would restore the failure domain S10 exists to break.

**Cache policy.** `dashboard/_static.compute_asset_hash` walks `web/` for the
`:8888` process only, so `web/mc/` gets no cache-busting hash and an edited
`mc.js` would serve stale from the browser cache. `mc/handler.py` therefore
sends `Cache-Control: no-store` on its own assets. A control plane is not a
high-traffic surface; correctness beats a cached byte.

**Syntax checking.** `node --check` returns exit 0 on a duplicate `const` in an
import-leading file, which `mc.js` will be. It must be validated through the
ESM sweep at `tests/test_web_js_esm_parse.py`, never a bare `node --check`.

### Lifecycle

Scheduled task `RC-MissionControl`:

- trigger ONLOGON, run as Administrator, HIGHEST privileges
- `pythonw.exe mission_control.py` (no console flash). The child-process flash
  caveat is already handled downstream: the only thing this process ever spawns
  is a lane, and `lane_launcher` already uses `CREATE_NO_WINDOW`.
- **restart on failure: `RestartCount=3`, `RestartInterval=1 minute`** (operator
  decision 2026-07-31). Choosing a scheduled task over a `rc_supervisor.py`
  entry bought independence at the cost of the supervisor's auto-restart, and an
  ONLOGON trigger fires exactly once. Without this setting a crashed control
  plane stays dead until noticed. Task Scheduler is the watchdog; no new process
  and no new code.
- **no hot-reload watcher.** `core.hot_reload` is deliberately NOT started. A
  control plane must not restart itself because an unrelated `.py` changed.
  Restarting Mission Control is an explicit act: end and re-run the task.
- **its own log file**, `logs/mission_control-YYYY-MM-DD.log`. Two processes
  appending to the shared `logs/YYYY-MM-DD.log` is a Windows file-lock hazard,
  and a control plane whose log is interleaved with game-dashboard chatter is
  harder to read at exactly the moment it matters.

**Bind failure must be loud.** `dashboard/server.py:195` logs a warning and
keeps going when the port is unavailable. Copying that pattern yields a control
plane that is silently absent. `mc/server.py` instead logs and **exits
non-zero**, so the task's Last Result reports the failure and the restart policy
above engages.

An RC restart via `restart_trigger.txt` cannot touch this process. That is the
acceptance criterion, and it holds structurally rather than by convention.

### Properties that do not survive a restart - stated, not fixed

`dashboard/_idempotency.py:55` is a plain in-memory `OrderedDict` with no
persistence. A Mission Control restart therefore **wipes every stored
idempotency key**, so a request retried across a restart RE-EXECUTES rather than
replaying its original result. For `interrupt` that means a second kill attempt
against a re-probed victim set.

This is not a regression - the dashboard behaves identically today - but S10
makes the control plane independently restartable, so the window is entered far
more often. It is recorded here rather than fixed because the S9 design already
covers the dangerous case: `interrupt` re-probes and REFUSES on fingerprint
mismatch instead of killing what it now finds. Persisting the table is a
candidate follow-up, not S10 scope.

### Repo-wide guards a new module auto-enrolls in

New `.py` files are swept by guards that scan the whole tree, so `mc/` must
comply from the first commit rather than be retrofitted:

- every module carries a `# arch: ... | section=... | frozen=no` header line
- `tests/test_skip_condition_hygiene.py:884` and
  `tests/test_dead_endpoint_cleanup_item186.py:199` `rglob` every `.py`
- `tests/test_drift_guard.py` must report 0
- ruff clean on all new files

Verified so it is not re-derived: there is **no set-equality guard on root
`*.py`**, so adding `mission_control.py` beside the existing 11 root modules
breaks nothing.

### Lanes and INTERRUPT semantics - unchanged, verified

`ops/loop/lane_launcher.py` spawns with `CREATE_NO_WINDOW` and no job object
(`DETACHED_PROCESS` is deliberately absent - it produces a silent no-op worker,
documented in that file at line 112). Windows does not kill children on parent
exit absent a job object, so **lanes outlive the server that fired them** both
before and after S10.

The lane lock is re-pointed at the WORKER pid (S5), and S9's INTERRUPT walks
descendants of the LOCK HOLDER, not of the serving process. Moving the serving
layer therefore does not change the victim set. Mission Control never appears in
its own interrupt preview.

### Removal from the RC dashboard

| File | Change |
|---|---|
| `web/js/panels/dev.js` | delete the Mission Control block, approx lines 342-1020 (~680 lines): `_loopControl`, `_LOCK_STATES`, `_loopAge`, `_loopLockRow`, `_MC_SHORTCUTS`, `_mcSetTimer`, `_mcMsg`, `_mcFire`, `_LANE_LABELS`, `_mcSteerKey`, `_mcRunId`, `_mcFireLane`, `_mcPaintLanes`, `_MC_IRQ_ID`, `_mcIrqForget`, `_mcVictimLine`, `_mcIrqPreview`, `_mcIrqFire`, `_mcPaintInterrupt`, `_mcPaint`, `renderLoopStatus` |
| `web/index.html` | delete the Mission Control S4 card at 1626 including `#loop-status-body` |
| `web/css/panels/header.css` | delete lines **2956-3178** (223 lines, ends before `.mode-pill` at 3179). NOTE: this is TWO blocks, not one. Grepping "Mission Control" finds only the S4 sub-block at 3018; the 2026-06-07 base card CSS above it is titled `/* Headless loop status card` and carries `.loop-status-body`, `.loop-dot`, `.loop-btn`, `.loop-line` and the rest of the foundation. Taking only 3018+ leaves dead CSS behind and gives the new page half its styling. Verified no non-Mission-Control code uses any `loop-*` class. |
| `web/js/lib/arm_confirm.js` | move to `web/mc/` |
| `dashboard/_dispatch.py` | drop `routes_loop_status.GET_ROUTES` (`:147`) and `routes_loop_control.POST_ROUTES` (`:210`); add the `_matchers` re-export |
| `dashboard/routes_loop_*.py` | stay in place, imported by `mc/` only. Header trust-model docstrings updated to describe the new bearer gate. |

After this, `/api/loop-status` and `/api/loop-control` no longer exist on
`:8888` at all. Any caller pointed at the old URLs gets a 404, which is the
correct loud failure.

## Test plan

Current surface: **159 tests** across **8 files** (the parent plan says 65 across
7 - both stale, corrected here).

| File | Tests | Disposition |
|---|---|---|
| `tests/test_mission_control_panel.py` | 38 | re-point `INDEX`/`DEV_JS`/`CSS`/`ARM_JS` to `web/mc/*`. Note `:94` asserts the LITERAL string `from '../lib/arm_confirm.js'`, which becomes a same-dir import - a string edit, not just a path constant |
| `tests/test_interrupt_panel.py` | 19 | same re-point |
| `tests/test_web_ascii_sweep.py` | n/a | names `web/js/lib/arm_confirm.js` at `:79`; update to the new path or the sweep silently stops covering it |
| `tests/test_interrupt_route.py` | 12 | unchanged (route-level, path-agnostic) |
| `tests/test_interrupt_tier.py` | 19 | unchanged (`ops/loop/interrupt.py`) |
| `tests/test_loop_status_route.py` | 25 | unchanged |
| `tests/test_lane_launcher.py` | 23 | unchanged |
| `tests/test_steer_channel.py` | 23 | unchanged |

Plus the JS-side suite: `web/js/lib/arm_confirm.test.mjs` moves to `web/mc/` and
its `node --test` invocation path updates. Two docstrings that cite the old
location (`test_mission_control_panel.py:4`, `test_interrupt_panel.py:5`) update
with it.

New tests (`tests/test_mission_control_server.py`):

1. **Import-isolation guard.** Importing `mc.routes` must not import
   `pydantic`, `dashboard.api_schema`, `dashboard._handler`, or any
   `dashboard.routes_*` module other than the two loop ones. Asserted against
   `sys.modules` in a subprocess so it cannot be masked by test-order imports.
2. **Bind scope.** The resolved bind list is exactly `127.0.0.1` and
   `100.70.22.55`, and never `0.0.0.0` or `::`.
3. **Auth gate - no token configured.** POST returns 503, and the action
   function is never reached.
4. **Auth gate - missing, malformed, and wrong token.** All 401. Assert
   `compare_digest` is used and that no response body or log line contains the
   token.
5. **Auth gate - correct token.** POST reaches the existing route handler and
   the idempotency layer still applies.
6. **GET is open**, and serving a static asset never consults auth.
7. **De-registration guard.** `dashboard._dispatch` GET and POST tables contain
   no `/api/loop-status` or `/api/loop-control` entry.
8. **Dashboard residue guard.** `dev.js`, `index.html` and `header.css` contain
   none of the Mission Control identifiers listed in the removal table. This is
   a set-equality style guard so a partial deletion fails.

Note the standing lesson that these tests cannot cover: **binding LIFETIME is
invisible to source-literal tests and to mutation testing.** Only a live browser
click found the two S9 defects. The 5-phase UI audit therefore stays mandatory
for `web/mc/index.html`, and the arm-then-confirm path is clicked live before
this is called done.

## Deploy order

Order matters; two of these are easy to leave until after the task is armed,
and both fail in a confusing way if you do.

1. **Write the token FIRST** - `config/mission_control_token.txt` (or set
   `RC_MC_TOKEN`) before `RC-MissionControl` is registered. A running task with
   no token serves a perfectly readable status page whose every button returns
   503. That is correct fail-closed behavior, not a bug, but it reads like one.
   Generate with `python -c "import secrets; print(secrets.token_hex(16))"`.
2. **Confirm inbound reachability for `:8895`.** No explicit Windows Firewall
   rule for `:8888` was found while designing, which means `:8888` is reachable
   over the Tailscale interface by some other mechanism (interface profile or an
   app-scoped rule). Verify how, rather than assume `:8895` inherits it - and if
   a rule is needed, scope it to the Tailscale interface, never to Any.
3. Register the task, start it, then run the acceptance criteria below.
4. Only then remove the dashboard card and de-register the routes. Landing the
   removal first would leave a window with no working control plane at all.

## Acceptance criteria

1. Mission Control answers on `https://100.70.22.55:8895/` **with `:8888`
   stopped**, cert validating without `-k`.
2. `echo restart > restart_trigger.txt` bounces RC and Mission Control keeps
   serving across it, same pid throughout.
3. `https://192.168.8.230:8895/` is refused (bind scope holds).
4. POST without a bearer token is 401; with the token, a `stop` action lands and
   `ops/loop/control/STOP` appears.
5. `:8888` returns 404 for `/api/loop-status` and `/api/loop-control`.
6. **`taskkill /F` the Mission Control pid; the task restarts it within about a
   minute and it serves again.** Proves the restart policy, which is the only
   thing standing in for the supervisor that was deliberately not used.
7. Port already in use: the process exits non-zero and the task's Last Result
   shows it, rather than logging a warning and idling.
8. Full suite green **run from the repo root**, ruff clean, `drift_guard` 0.
9. ESM sweep green over `web/mc/*.js`, and `node --test` green on
   `arm_confirm.test.mjs` at its new path.
10. 5-phase UI audit complete on the new page with every MUST-FIX resolved in
    the same slice, plus a live browser click through arm-then-confirm - the
    binding-lifetime defects S9 hit are invisible to every test above.

## Non-goals and explicit do-nots

- Do NOT fork `ops/loop/*`. The repo already carries one
  byte-identical-by-contract pair and does not need a second class of them.
- Do NOT edit `ops/loop/slots.py` or `ops/loop/winmutex.py` - ever.
- Do NOT edit `ops/rc_supervisor.py` (frozen, and a supervisor entry was
  rejected on design grounds anyway).
- Do NOT fire lanes 7 or 8. They have never been fired, deliberately, and both
  are gated on operator sign-off. The launch path is proven structurally.
- Do NOT widen the bind to a wildcard "just to test". Test against the two
  bound addresses.
- Do NOT add a link, redirect, or status mirror back into the dashboard.
- Do NOT start `core.hot_reload` in the Mission Control process.
