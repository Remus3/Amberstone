# P2 per-file code-audit fanout manifest (built cycle 6, item 400)

Charter lens (docs/DEEP_AUDIT_CHARTER.md P2): every source file audited for
correctness, security hardening, efficiency, and friction classes (BOM/encoding,
PS5.1 quirks, stale-pipe), from programmer/user/outside-reviewer perspectives.
Verifiable findings + concrete sourcing only - re-probe live, never trust memory.

Inventory basis: git-tracked source files (.py .js .css .ps1 .cmd .bat .spec),
EXCLUDING Share/ (generated mirror - audit sources instead), docs/_archive/,
agents/agent*/ artifacts, data/, logs/. Census 2026-06-11: 1307 files / 399052 LOC.
_archive/ (14 files / 5.6k LOC) is quarantined dead code - SKIP per the standing
quarantine policy (reference_archive_dir); note-only if grep shows a live import.

## Slice protocol (every wave)

- Orchestrator-merge: disjoint file sets per worktree agent; agent returns
  structured findings (file:line, class, severity, FIX-NOW vs DEFER) + applies
  FIX-NOW edits in its slice only; subagents run ruff before reporting.
- Verifier gate (.claude/agents/verifier.md) re-probes claims; tools/truth_gate.py
  PROCEED before merge/commit. TDD: regression test first for every behavior fix.
- Frozen files are OPEN (charter auth 1) but every frozen edit is named in the
  cycle ledger entry.
- Sizing: ~10-15 files or ~4-6k LOC per slice; one wave (or half-wave) per cycle.

## Waves (priority order; tick when a cycle completes a slice set)

### W1 runtime spine (live product path) - ~15 slices
- [x] core/ 103 files / 29531 LOC - DONE cycle 7 (7 slices A-G, merge 6273d655;
      FIX-NOW applied incl 2 security fixes in lessons_receiver; DEFER findings
      in ops/audit/P2_FINDINGS.md)
- [x] dashboard/ 78 / 20629 - DONE cycle 8 (5 slices A-E, octopus a5d266b3;
      FIX-NOW incl backslash path-traversal source disclosure in routes_static,
      dead-since-birth pickban cleanse advisory import, statcheck OverflowError
      crash, shared ro_conn close poisoning; DEFER in ops/audit/P2_FINDINGS.md)
- [x] coaches/ 27 / 8657 - DONE cycle 9 (2 slices A-B, merge 6350c6d1; FIX-NOW
      incl base-coach fast-path prev-state bug (compared state to itself since
      ARCH-002), NaN/inf Live Client coercion, KIWI mayhem-tag fix, numeric
      patch-dir sort, ddragon cache-poisoning fix; DEFER in ops/audit/P2_FINDINGS.md)
- [ ] app/ + game_reader/ + modes/ + lcu/ + lib/ + vision_server/ +
      coach_integration/ + modules/ 33 / 8917 (~2 slices; app/* + lcu_client frozen)

### W2 DS engine - ~8 slices
- [ ] agents/daemon_slayer non-test src (engine, scorers, registries, effects
      facade; ~90 files / ~48k LOC - exact split at wave start)
- [ ] agents/ supervisor set: supervisor.py + _supervisor_{http,common,ephemeral}.py
      + _minimap_bbox.py 5 / 2719 (1 slice)

### W3 web surface - ~8 slices
- [ ] web/js 58 / 27020 (~5 slices; panels are independent)
- [ ] web/css 48 / 16635 (~3 slices; tokens.css first)

### W4 operational tooling - ~10 slices
- [ ] tools/ 164 / 43633 (~8 slices; bridge family frozen-but-open; gamepc_*
      tools get P3-prune verdicts here, not deep audit)
- [ ] scripts/ + ops/ + rc-shell/ + tft/ + (root) + riot-commander.spec
      114 / 24433 (~2-3 slices)

### W5 test corpus (lighter lens: assertion correctness, fixture pins, dead tests)
- [ ] tests/ 359 / 81155 (~6 slices, grep-driven: data-fragile assertions,
      stale pins, skipped/xfail rot)
- [ ] agents/daemon_slayer/tests ~200 files / ~81k LOC (~6 slices, same lens)

## Standing finding classes (from cycles 1-6, watch for siblings)

- bare-py launcher usage (guard: tests/test_bare_py_ban.py - keep allowlist tight)
- scattered version-literal fallbacks (JS guard bans semver literals in web/js)
- retention-less growth files (task logs, jsonl ledgers, caches)
- port-race / duplicate-launcher vestiges (RC-VisionServer class)
- logging-after-close shutdown noise (raiseExceptions class)
- stale fixture/data pins (DS fixture policy: tests/test_ds_fixture_policy.py)
