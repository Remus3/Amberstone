# Lane gated - run s133g008-a02abf (session 133, cycle 8, 2026-10-25)

No game this window: League client open at home, no lobby, no champ select, no game.

```
IN-GAME  0 min                                   |  IDLE whole cycle (03:43 to about 04:10 local)
DRAINED  0 rows                                  (GATE 1 re-read: every row needs a lobby or champ select)
READY    2 rows: G3-01 (probe tool + predicate), G3-02 (DOM-vs-LCU bench CHECK + PRUNE CANDIDATE note)
REFUTED  2 predicate drafts for G3-01, by two independent verifier passes (details below)
BLOCKED  0 new
```

## Live state (read-only probes)

- `/api/state`: `mode_key='client'`, `liveclient` empty, LCU phase `None` at 03:43 and on every re-probe.
- `:8889/latest-lcu` (token read from the main checkout; the worktree has no `config/vision_token.txt`):
  idle capture cadence 12 distinct captures in 12 s, median gap 1.031 s; a later 6 s run gave 1.03 s,
  max poll gap 0.076 s.

## Prep shipped

1. **G3-01** (E7a / E7 TODO-1 bench swap). "Visibly faster" restated as a predicate over two clocks in the
   agent process: the `[cmd] bench_swap` line in `logs/lcu_agent.log` and the relay capture `data.ts`.
   With one agent every natural capture gap exceeds the 1.0 s wait, so a gap under 0.95 s is the wake.
   PASS = a wake capture showing the new pick within 2 x c_est + 0.25 s. FAIL needs dense polls and no
   wake. Coincidence, a late LCU, a hidden wake, a second writer or sparse polls give NO_RESULT.
   One command: `python tools/gated_bench_swap_probe.py --watch 90`, run from the main checkout, then
   click the bench on the RC DASHBOARD (a swap made in the League client tests nothing).
2. **G3-02** (KEYSTONE residual). CHECK: rendered `.csv-bench-cell` `data-bench-id` order equals the
   relay `champ_select.bench[:10]` (the probe reports it as `bench_after`). PRUNE CANDIDATE for a human:
   the bug was fixed and proven live 2026-05-17 (`docs/history_notes.md:24438`); the operator's triage
   mark is `?` with plan disposition PRUNE (`:35846`). Nothing struck.

## Gates

- Verifier pass 1: REFUTE. A relative off-cadence test could false-PASS under the old code, and missed
  polls inflated its baseline. An unpolled wake or a late LCU could false-FAIL. A second agent could fake
  wakes. G3-02 overstated the operator mark. All adopted.
- Verifier pass 2: confirmed those fixes, then REFUTED once more. A capture that lives in the relay
  for less than one poll can hide a wake and false-FAIL, and the 0.95 s boundary was unpinned. Both
  adopted. A mutant without the hidden-wake rule fails its test.
- Tier-1 tests: `tests/test_gated_bench_swap_probe.py` plus the two existing gated probe files gave
  "32 passed". Ruff clean, py_compile OK.
- Doc guards: 37 test files citing the touched docs, plus the ledger / budget / gated files.
  "811 passed, 275 subtests passed", EXIT=0.
- Added lines: 0 non-ASCII bytes.

## Decisions recorded

- The tool carries no `# arch:` header (161 of 191 `tools/*.py` carry none). With the header, the
  pre-commit archmap check demands a `docs/ARCHITECTURE.md` regen, and that file is outside this lane's
  write set.

## Incident (self-reported)

- The doc-guard pytest output was redirected to `../../../ops_tmp_ignore`, which resolved to the MAIN
  checkout root. It was an untracked 1.4 KB scratch file created by this run at 04:02. Removed at once
  with `rm` (replaceable scratch, no consumer). The main checkout was not otherwise touched.

## Merger follow-ups

- Optional: add `# arch: ... | section=tools | frozen=no` to `tools/gated_bench_swap_probe.py` and run
  `python tools/gen_archmap.py`, so the tool appears in `docs/ARCHITECTURE.md`.
- None needs a restart or a game.

## Next candidate

- GATE 3 champ-select rows are now all readied or re-filed. The next unready ARAM rows are the in-game
  G3-14 accrual read. RM-852 shipped, so recount with its filter. The shadow files are excluded for A22
  right now.
