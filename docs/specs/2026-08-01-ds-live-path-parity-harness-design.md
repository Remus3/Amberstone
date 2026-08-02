# RM-143 - DS live-path parity harness (design)

Status: SPEC (not built). Filed 2026-08-01.
Origin: /insights "live-path parity harness" suggestion, triaged as the one
genuinely-missing item of three (the other two are already shipped as R7 /
Session Default / RC-CIWatchdog / lanes.py).
Blast radius: Tier-1 while REPORT-ONLY, Tier-2 once armed. No engine change, no
ENGINE_VERSION bump, no `data/` write.

---

## 1. The bug class this closes

RC has independently rediscovered one failure shape at least four times and each
time filed prose rather than a gate:

| Measured instance | What green tests proved | What was actually true |
|---|---|---|
| `reference_ds_route_seam_transport_vs_flag` | seam flag settable, reachability guards green | `/dps` carried no `rune_ids`, `/ehp` no `targets_in_rotation`; the seam was arithmetically INERT |
| `reference_ds_probe_rank_vs_archetype_route` | probe returned a plausible ranking | `POST /rank` is the CARRY scorer and SILENTLY IGNORES `enemy_ad_share` / `enemy_ap_share` |
| `feedback_guard_on_nondefault_call_path_is_untested` | suite green | deleting the guard entirely stayed green - it sat on a non-default call path |
| `reference_ds_probe_empty_build_artifact` | two headline RM-92 findings | probing at `item_ids=[]` under-ranks amp items; both findings were artifacts |

Common root cause: **a unit test imports the engine function and passes kwargs
directly, while the live caller reaches the engine through an HTTP route that
parses a JSON body.** Anything the route fails to carry between those two is
invisible to every existing guard.

`tools/truth_gate.py` reconciles CLAIMS (suite re-run, file content, CI via gh).
It does not compare route output to engine output. Repo-wide grep for `parity`
returns docs and plans only - no runner exists.

---

## 2. Three legs, matching the three gates

A DS route seam has THREE gates (flag / transport / owner). A naive
output-diff harness passes an inert seam, so it would reproduce the very bug it
exists to catch. The harness therefore has three legs.

### Leg A - static transport map (no live dependency)

`tools/ds_parity_map.py` AST-scans `agents/daemon_slayer/server.py`:

- for every entry in `_POST_ROUTES` (`server.py:2570`), collect the body keys the
  handler actually reads - the string literals passed to `_opt_int` / `_opt_str`
  / `_opt_float` / `_opt_bool` / `_required_str` / `_coerce_str_list` and any
  `body.get("...")`;
- resolve the engine callee each handler invokes and record its
  `inspect.signature` parameter names (signature, never the docstring - the
  RM-118 prose was wrong in BOTH directions in a single run);
- emit `ops/runtime/ds_parity_map.json`: `route -> {body_keys, engine, engine_params, carried, dropped, unreachable}`.

`carried` = engine param reachable from the body. `unreachable` = engine param no
route can set. `dropped` = a body key the handler parses but never forwards.

Guard test `tests/test_ds_parity_map.py` asserts:
1. every seam flag in the registry (`apply_rune_offense_grants`,
   `apply_canonical_cast_rate_keys`, `apply_ad_axis_ability_damage`,
   `apply_passive_damage`, `apply_target_vuln`, `assume_passive_as_stacks`,
   `apply_passive_mitigation`, `include_conditional`, `score_by`) is `carried` by
   at least one route, and the test names WHICH routes - so a shrinking reach is
   a failing diff, not a silent regression;
2. `unreachable` is empty or explicitly allow-listed with a reason.

This leg alone catches the transport-vs-flag class and costs no live server.

### Leg B - silent-drop detection

Same map, runtime view. A caller that POSTs `enemy_ad_share` to `/rank` today
gets a plausible carry-scored answer with the key silently discarded.

`tools/ds_parity_run.py --lint-fixtures` validates every fixture body against the
map and FAILS the fixture (not the engine) when it sends a key the target route
does not read. This makes the `/rank` trap unauthorable rather than merely
documented. It is also the cheapest leg to adopt: it turns a memory entry into a
lint.

### Leg C - live value parity

For each fixture `(route, body)`:
1. call the handler in-process: `_POST_ROUTES[route](body)`;
2. POST the identical body to live `http://127.0.0.1:8860{route}`;
3. diff, with per-field tolerance (exact for ids/labels/ordering, relative
   1e-9 for floats).

This leg does NOT test the engine twice for nothing - it tests the DEPLOYED
process against the repo. It is aimed squarely at RC's measured deployment-skew
traps: `project_loop_controller_stale_code` (a controller ran 5h of its own
fixes unloaded), `reference_schtasks_end_run_race_ds_8893`, and the standing
CLAUDE.md warning that a mid-suite DS bounce fakes anchor-mismatch failures.

**Verdicts are three-valued, not two.** Before diffing, the runner compares live
`/health` ENGINE_VERSION against `agents/daemon_slayer/__init__.py`:

- match + outputs agree -> `PARITY`
- match + outputs differ -> `FAIL` (a real divergence)
- mismatch -> `SKEW` (the live process is stale; re-run after the bounce settles)

`SKEW` must never be reported as `FAIL`. A gate that cries wolf during a normal
DS restart is a gate that gets disabled within a week.

---

## 3. Fixtures

Seeded, not exhaustive. Selection rule: **every route that has previously
required a post-ship correction**, mined from `docs/LEDGER.md` and
`agents/daemon_slayer/CHANGELOG.md`, plus one baseline fixture per archetype
route so the `/rank` vs `/rank-<archetype>` distinction is permanently pinned.

Fixture file: `tests/fixtures/ds_parity_fixtures.jsonl`, one object per line:
`{"id", "route", "body", "why"}`. `why` cites the LEDGER item or memory that
motivated it, so no fixture is unexplained.

Explicit anti-pattern, from `reference_ds_probe_empty_build_artifact`: no
fixture may use `items: []` for a ranking route unless its `why` states that the
empty build IS the thing under test.

---

## 4. Phasing and acceptance

Each phase is TDD (failing test first) and independently shippable.

**P1 - Leg A map + guard test.** Accept: `ops/runtime/ds_parity_map.json`
generated; `tests/test_ds_parity_map.py` green; deleting any seam flag's
transport from a route turns the guard RED (prove it by temporary mutation, per
`feedback_guard_on_nondefault_call_path_is_untested` - a guard nobody has seen
fail is not a guard).

**P2 - Leg B fixture lint.** Accept: a deliberately wrong fixture sending
`enemy_ad_share` to `/rank` fails the lint with a message naming the correct
route.

**P3 - Leg C runner, REPORT-ONLY.** Accept: `ops/runtime/ds_parity_report.json`
written atomically; exit 0 always; `SKEW` demonstrated by running it against a
deliberately stale server; `FAIL` demonstrated by a temporary one-line engine
mutation.

**P4 - arm.** Accept: `--arm` exits 2 on `FAIL` only (never on `SKEW`), wired
into the Tier-2 DS bump ritual next to the existing suite + Share mirror steps.
Arming waits until P3 has been observed quiet across several real DS batches -
the same discipline `tools/stop_claim_gate.py` used, and for the same stated
reason: "a gate that fires wrongly once gets disabled forever".

---

## 5. Non-goals

- Not a per-edit hook. `pytest_guard.py` stays py_compile-only by default; this
  runs at Tier-2, on DS batches, not on every Edit.
- No engine, schema, or `ENGINE_VERSION` change. The harness observes; it never
  corrects.
- RC-side serving parity (`/api/ds-preview`, `core/daemon_slayer_client.py`) is
  a deliberate later phase - the DS route seam is where the measured failures
  are.
- Not a replacement for `truth_gate.py`. Different question: truth_gate asks
  "did the worker's claim happen", parity asks "does the deployed path agree
  with the repo path".

---

## 6. Known risks

- **Fixture rot.** A route signature change makes fixtures stale. Mitigated by
  Leg B lint running first and failing loudly on unknown keys.
- **Serialization with DS restarts.** The runner must tolerate a bounce
  mid-run; that is what `SKEW` is for, plus a single settle-and-retry.
- **Cost.** Leg C is N HTTP round-trips per Tier-2 batch. Keep the seeded
  fixture set small (target under ~40) and let it grow only by measured
  post-ship corrections.
- **Over-trusting Leg C.** Two agreeing processes running the same stale code
  agree perfectly. Leg C is a deployment check; only Leg A can see an inert
  seam. Neither leg alone is sufficient, which is why the spec has three.
