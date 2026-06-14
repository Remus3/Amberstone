# P3 PRUNE SWEEPS - work-map

DEEP-AUDIT phase P3. Slicer = `tools/p3_ascii_census.py` (bucketed non-ASCII
census + BOM/.ps1-mojibake-risk report). Mirrors the cycle-16/17 partition
harness. Newest-first.

P3 charter scope (DEEP_AUDIT_CHARTER line 52): vanguard/CV/capture caveats out;
2-PC/gamepc out; BOM/smart-quote/encoding retro-sweep; em-dash drift check.

---

## DONE - cycle 20 (item 416): SAFE-BULK ASCII glyph sweep slice A2 (tools/ + agents non-DS)

- Ran tools/p3_ascii_sweep.py (cycle-19 transformer) on tools/** + agents/ NON-DS
  source. 10426 comment-glyph subs / 69 .py (tools/ 7261 of 134 scanned / 27
  changed; agents non-DS 3165 of 81 scanned). commit `74cca91d`.
- EXCLUDED: agents/daemon_slayer/** + Share/** (B1, load-bearing). The 2 changed
  tools/daemon_slayer_*.py are EXTRACTORS, NOT the engine. 3 FROZEN bridge_*.py
  swept comment-only (actions 314 / classify 71 / history 259; charter frozen-auth
  + cycle-19 precedent). tests/** = 0 subs (already ASCII-clean comments, no-op).
  NO UNMAPPED comment glyph in either tree.
- Gate: py_compile 69/69 OK; token-equivalence proof - every non-COMMENT token
  byte-identical pre/post across ALL 69 (exhaustive; dominates a suite run for a
  comment-only edit). Tier-0 by R5/R6: no suite, no DS-dir, no ENGINE bump, no
  DS :8893 restart, no live RC restart.

---

## DONE - cycle 19 (item 415): SAFE-BULK ASCII glyph sweep slice A (comment-token only)

- NEW tools/p3_ascii_sweep.py - tokenize-based transformer; rewrites decorative
  glyphs to ASCII INSIDE Python COMMENT tokens ONLY (provable zero-behavior: a
  comment is never emitted, asserted, or parsed). STRING-token glyphs untouched
  -> auto-protects every load-bearing emitted/regex-matched arrow (dps.py note,
  aram_coach item_build wire-split stay; confirmed aram_coach STRING 76 intact,
  dps.py untouched). Conservative GLYPH_MAP; an unmapped comment glyph is left
  as-is (1: U+2705 in scripts/wakeup_prune.py - emoji, P8 territory).
- 16277 substitutions / 108 .py rewritten / 310 scanned. Trees: core dashboard
  lcu app vision_server coach_integration coaches tft modes modules game_reader
  scripts ops + root .py (composition_advisor/role_profiles/item_advisor/
  performance_tracker/web_dashboard/main). EXCLUDED (own cycles): agents/**,
  agents/daemon_slayer/** + Share/** (DS load-bearing), web/** (UI-gated/non-py),
  tools/** (next slice), _archive/**, tests.
- 13 FROZEN files swept comment-only (charter line 11 deep-audit frozen auth +
  cycle-18 precedent): app/{__init__,_loop,_game_lifecycle,_health_monitor,
  _remediation,_state_authority}.py, core/{game_snapshot,log_setup,moon_proxy}.py,
  dashboard/routes_bridge.py, lcu/lcu_client.py, ops/{rc_dev_runtime,rc_supervisor}.py.
- Gate: py_compile 108/108 OK; tests/ suite 7887p/2s/109sub exit 0 (BYTE-IDENTICAL
  to the cycle-18 baseline). DS-dir NOT re-run (0 DS-engine/Share file touched ->
  DS behavior provably identical). NO ENGINE bump, NO DS :8893 restart, NO live
  RC restart (comment-only, Tier-0 by R5; suite run as tool-bug ground-truth).

---

## DONE - cycle 18 (item 413): encoding sub-track slice 1 (safe, self-contained)

- BOM retro-sweep: stripped 4 non-protective UTF-8 BOMs (ops/rc_supervisor.py
  [frozen], config/CONFIG_AUTHORITY.md, tools/DEV_WORKFLOW.md, web/css/dashboard.css).
  KEPT 4 .ps1 BOMs (PROTECTIVE - PS5.1 decodes BOM'd .ps1 as UTF-8; stripping
  re-opens the ANSI-decode hazard). KEPT 3 UTF-16 Task XML (canonical schtasks
  export format).
- em-dash / smart-quote DRIFT CHECK = PROVEN CLEAN for authored content. Every
  em/en-dash (U+2013/U+2014) + smart-quote (U+2018/U+2019/U+201C/U+201D) hit in
  the tree is upstream data (DDragon/Meraki/wiki JSON), scraped HTML
  (data/meta_build/_phase3_html), or generated reports (agent6_auditor) -
  patch-regenerated, OUT OF SCOPE - EXCEPT the one authored hit:
  ops/RC-BridgeWatcher.xml [frozen] Description em-dash -> fixed to '-'
  (UTF-16LE byte-preserving).
- .ps1 LATENT-MOJIBAKE-RISK class CLOSED: the 2 no-BOM .ps1 holding non-ASCII
  (ops/rc_league_watcher.ps1 237xU+2500+3xU+2192, tools/bridge_watcher_update_check.ps1
  264xU+2500) swept to ASCII (comment dividers only, 0 load-bearing; PARSE-OK).
  New invariant guard tests/test_ps1_encoding_hygiene.py: no tracked .ps1 may be
  no-BOM AND non-ASCII.
- BUG FIX (surfaced by census): tft/tft_coach_engine.py held cp1252-roundtrip
  mojibake in EMITTED TFT coach text (9x bullet U+2022, 4x arrow U+2192, 1x >=
  U+2265, 1x warn U+26A0 - shown to users as "a-euro-cent" garbage) -> ASCII.
  NOT caught by test_mojibake_hygiene (it guards only the 2 dash-class
  signatures). File now 100% ASCII.
- NEW TOOL tools/p3_ascii_census.py (durable P3 slicer). Gate: 176 tests
  (162 tft-ref + hygiene + 14 guards) green; py_compile + PS ParseFile OK.

---

## REMAINING P3 (future cycles) - the ~400-file ASCII glyph sweep + 2 semantic prunes

### A. SAFE-BULK ASCII glyph sweep (parallelizable, c16/c17 treatment)
TOOL = tools/p3_ascii_sweep.py (comment-token-only, provable-safe; cycle 19).
- A1 DONE cycle 19: the core RC runtime + product trees (108 .py). See above.
- A2 DONE cycle 20 (item 416): `tools/**` (7261 subs / incl 3 frozen bridge_*.py
  comment-only) + `agents/` NON-DS source incl agent3_testing/** suite (3165 subs)
  = 10426 / 69 .py, comment-token-only. `tests/**` was 0 subs (already ASCII-clean
  comments). Gate = token-equivalence proof (no owning-suite run needed). See above.
- A3 REMAINING (NOT comment-only - needs string/docstring judgement): the
  STRING-token + module-docstring box-draw banners p3_ascii_sweep intentionally
  skips. Some are print-banners a test may assert on -> per-hit verify, suite-gate.
Run order: A2 first (mechanical, same tool), A3 last (judgement). web/ .js/.css
glyphs are NOT python-tokenizable -> handled in B3 (UI-audit-gated), not here.

### B. LOAD-BEARING-COORDINATED (DEFER - engine+test+resync together, NOT a sed)
1. DS-engine agents/daemon_slayer/*.py (20 files, 2036 non-ASCII) + Share/src mirror
   (26 files, 2769): U+2192 arrows EMITTED into output that tests regex-match
   (c17 DEFER test_effects_expansion.py:3892 <- dps.py "armor X -> Y" note). Coordinated
   engine-emit + regex + test slice; Tier-2 full DS suite + Share re-sync + DS :8893 restart.
2. coaches/aram_coach.py 28xU+2192: the item_build wire-convention arrow (c16 DEFER) -
   production coach splits on the LITERAL arrow; needs coordinated coach + Haiku-prompt +
   11 peer tests (tests/phase2_smoke/test_aram_coach_item_class_peers.py).
3. web/js + web/css: RENDERED UI glyphs (U+21BB refresh, U+2715 close, U+2605 star,
   U+25B6 play, emoji U+1F507/1F50A, CSS `content:` pseudo-glyphs) are load-bearing -
   UI-audit-gated; distinguish comment-dividers (safe) from rendered glyphs (visual check).

### C. DOCS (-> P8 territory, not mechanical)
Root CLAUDE.md/ROADMAP.md/BACKLOG.md/README.md + docs/*.md status emoji
(U+1F7E1/U+2705/U+1F6AB) + box-draw + arrows. docs/history_notes.md,
docs/ROADMAP_HISTORY.md, docs/LEDGER.md = IMMUTABLE history, OUT OF SCOPE
(like _archive). Status-emoji -> ASCII is a readability decision -> P8 doc rewrite.

### D. gamepc/2-PC prune (charter auth 5b) - SEPARATE semantic cycle(s)
1791 hits / 212 files. NOT a blind strip: tools/gamepc_*.py are the Legion-LOCAL-
relocated agents (misnamed, still live - "gamepc_screen_agent.py 2-PC-era name now
Legion-local"); core/game_host.py RC_GAME_HOST is load-bearing; scripts/{discover_champion_codes,
probe_missing_codes,team_planner_sync} hardcode 192.168.8.237 (-> 127.0.0.1/RC_GAME_HOST);
the Game-PC cross-Claude BRIDGE is KEPT (item 215d). GEMINI scope-consult: rename-vs-delete
the gamepc_*.py set; which refs are live vs retired.

### E. vanguard/CV/capture caveat prune (charter auth 5a) - SEPARATE semantic cycle
180 hits / 48 files. Distinguish "Vanguard-safe" as a STILL-TRUE positive
architectural constraint (Electron overlay reads only :2999+LCU, no memory/injection)
from retired BSOD/capture CAVEATS. Many hits are upstream TFT data ("Vanguard" trait in
tft_set17 meta) = data-class, OUT OF SCOPE. GEMINI scope-consult on the positive-constraint
vs caveat line.
