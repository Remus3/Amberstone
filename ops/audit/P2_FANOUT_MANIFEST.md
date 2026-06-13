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
- [x] app/ + game_reader/ + modes/ + lcu/ + lib/ + vision_server/ +
      coach_integration/ + modules/ 33 / 8917 - DONE cycle 10 (2 slices A-B, octopus
      d61330b9; FIX-NOW incl snapshot_normalizer NaN/inf boundary coercion, postgame
      champ_name precedence bug (empty indexed column) + _int NaN/OverflowError guards,
      lcu_client ARAM queue 2400 Mayhem gap, archetype_dispatch NaN delta/gold killing
      DS panel JSON, rune-writer cache-poison + spell-pref race, OCR subprocess timeout;
      no frozen edits - all app/* + lcu_client findings were DEFER. DEFER in
      ops/audit/P2_FINDINGS.md). W1 runtime spine COMPLETE.

### W2 DS engine - COMPLETE  (census at wave start: 68 non-test files / 39127 LOC)
- [x] agents/daemon_slayer non-test src - COMPLETE across two half-waves.
      HALF-WAVE 1 cycle 11 (item 405): 4 slices A/B/C/F, 36 files / ~23.1k LOC of
      scorer-logic + engine-core/server; 47 new tests; FIX-NOW = 8 NaN/inf JSON-token
      + OverflowError guards across missile/dps_sweep/antitank/ability_hps + server.py
      500-handler raw-exc leak fix + float-chokepoint isfinite rejects.
      HALF-WAVE 2 cycle 12 (item 406): 3 slices D effects-data (3 files) / E passive-
      overrides (12) / G remaining-mechanics (17); 32 of the 47 new tests; FIX-NOW = 6
      non-finite-JSON-token guards (_effects_types resolve_damage/ItemShield/ItemHeal,
      _passive_resist/ally_grant resist paths, fight_report inf mana_pool -> null).
      No frozen edits (no DS file is frozen). DEFER in ops/audit/P2_FINDINGS.md.
- [x] agents/ supervisor set: supervisor.py + _supervisor_{http,common,ephemeral}.py
      + _minimap_bbox.py 5 / 2719 - DONE cycle 12 (item 406, slice H, folded into
      half-wave 2; 12 of the 47 new tests). FIX-NOW = _supervisor_http generic 500/502
      bodies + allow_nan=False, _supervisor_ephemeral stderr secret redaction,
      _supervisor_common atomic lockfile write, supervisor.stop logging-after-close
      silence. agents/supervisor.py is NOT frozen (ops/rc_supervisor.py is, untouched).

### W3 web surface - COMPLETE
- [x] web/js 58 / 27020 + web/css 48 / 16635 - DONE cycle 13 (item 407, audit commit
      db7952f2; the WHOLE web surface in one cycle via 10 disjoint parallel slices: 6 JS
      A-F + 4 CSS G-J). Dominant FIX-NOW = XSS (data-controlled strings into innerHTML
      unescaped - browser analog of the cycle 7-12 non-finite-JSON-token class); 18 JS
      files hardened via escapeHtml/escHtml/_esc + scorer_units finite guard + trigger_pill
      double-eval guard. CSS pixel-neutral net = dead .bo-excl rule removed. 2 over-reaches
      reverted in-cycle (rendered build_order.js glyphs; bridge_pending #F07E8B which is a
      guard-pinned brand color). +3 tests tests/snapshot_panels/test_xss_escaping.py
      (Playwright e2e + 2 node-subprocess primitive tests). No frozen edits (web/* has none),
      no ENGINE bump, no RC restart (ADR-008 asset-hash). DEFER in ops/audit/P2_FINDINGS.md.

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
