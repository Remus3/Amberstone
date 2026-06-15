# P3 PRUNE SWEEPS - work-map

DEEP-AUDIT phase P3. Slicer = `tools/p3_ascii_census.py` (bucketed non-ASCII
census + BOM/.ps1-mojibake-risk report). Mirrors the cycle-16/17 partition
harness. Newest-first.

P3 charter scope (DEEP_AUDIT_CHARTER line 52): vanguard/CV/capture caveats out;
2-PC/gamepc out; BOM/smart-quote/encoding retro-sweep; em-dash drift check.

---

## DONE - cycle 22 (item 418): SAFE-BULK ASCII glyph sweep slice A3b-1 (log/print-string-token-only)

- Carved the provably-safe subset off the load-bearing A3b remainder via per-hit
  AST classification. NEW durable `--log-apply` mode in tools/p3_ascii_sweep.py
  (+ `--log-dry` / `--log-unmapped`): GLYPH_MAP applied to glyphs inside string
  args of a logging call (log/logger/_log.{debug,info,warning,error,critical,
  exception}) or print(), AST-located + char-offset spliced. Log/console output =
  closest string-class to a comment (never asserted on by a glyph - the only tests
  holding these glyphs are the deferred aram peer suite + 2 snapshot fixtures,
  neither logs; never split-on; never an LLM prompt). commit `e3124286`.
- 42 tool subs / 22 .py + 1 hand-fix = 43. TOOL LIMITATION found: CPython 3.14 /
  PEP-701 shifts the col_offset of an f-string literal segment AFTER an
  interpolation -> a glyph there is silently MISSED (clean miss, never a mis-splice;
  extract_panels.py:273 hand-fixed; docstring note + re-scan workflow added).
- EXCLUDED: agents/daemon_slayer (0 log hits), Share, the 3 Share-mirrored
  tools/daemon_slayer_{extract,abilities_extract}.py + ds_max_priority_prefilter.py
  (-> B1 / ds_share_sync), and the 2 sweep-tool GLYPH_MAP literals (never touch).
  RESIDUAL by design: 3x U+26A0 warn-emoji (unmapped, P8) + 2x runtime em-dash from
  ASCII-escapes in tft_live_analysis (ASCII source, out of P3 byte-scope).
- Gate (Tier-1, suite-gated - strings change, NOT the token-equivalence class):
  py_compile 22/22 + tool OK; tests/ 7887p/2s/109sub exit 0 BYTE-IDENTICAL to
  baseline; glyph-swap PROOF (HEAD vs working difflib) 43 hunks all GLYPH_MAP /
  0 unexpected; idempotent. DS-dir not re-run (0 DS/Share file touched).

---

## DONE - cycle 21 (item 417): SAFE-BULK ASCII glyph sweep slice A3a (docstring-token-only)

- Extended tools/p3_ascii_sweep.py with an opt-in --doc-apply mode: same
  conservative GLYPH_MAP applied inside module/func/class DOCSTRING STRING tokens
  (located via AST - never an f-string, never a split-on/regex-matched code
  string). Docstrings are not emitted to coach output, not split-on, not
  regex-matched by production; only consumers = argparse --help (cosmetic) + 2
  __doc__ tests that assertIn() ASCII substrings (immune; neither target module
  is in the changed set). Same provable-safe class as the comment-token sweep.
  commit `74e3b659`.
- 576 docstring-glyph subs / 120 .py (core dashboard lcu app vision_server
  coach_integration coaches tft modes modules game_reader scripts ops agents
  non-DS tools + root .py). EXCLUDED: agents/daemon_slayer + Share (B1), web
  (B3), tests, _archive. GLYPH_MAP stays conservative (operator rejected a
  generic subscript-digit range); the lone unmapped docstring glyph - U+2080
  score-zero in core/augment_recommender.py - hand-fixed to ASCII score_0.
  0 residual non-ASCII in any swept docstring.
- Gate (Tier-0): py_compile 120/120 OK; token-equivalence proof - every
  NON-docstring token byte-identical to HEAD + identical type-sequence across
  ALL 120 (no code moved), every docstring token ASCII post-sweep. No suite,
  no DS-dir, no ENGINE bump, no DS :8893 restart, no live RC restart.

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
TOOL = tools/p3_ascii_sweep.py (comment-token + docstring-token + log/print-string modes, provable-safe; cycles 19/21/22).
- A1 DONE cycle 19: the core RC runtime + product trees (108 .py). See above.
- A2 DONE cycle 20 (item 416): `tools/**` + `agents/` NON-DS source = 10426 / 69
  .py, comment-token-only. `tests/**` was 0 subs. Gate = token-equivalence proof.
- A3a DONE cycle 21 (item 417): module/func/class DOCSTRING glyphs via the new
  --doc-apply AST mode (provable-safe: docstrings not emitted/split/regex-matched;
  __doc__ consumers = argparse --help cosmetic + 2 ASCII-substring tests, immune).
  576 subs / 120 .py + 1 hand-fix (U+2080 score-zero -> score_0). Gate =
  token-equivalence proof (non-doc byte-identical) + py_compile. See above.
- A3b-1 DONE cycle 22 (item 418): the log/print-string-arg subset (the provably-safe
  diagnostic-string class) via the new --log-apply AST mode. 42 tool subs / 22 .py +
  1 hand-fix. Gate = suite baseline-identical + glyph-swap proof. See above.
- A3b-2 REMAINING (NOT mechanical - per-hit judgement, owning-suite gate, several
  overlap section B): the rest of the CODE-STRING glyphs - the genuinely LOAD-BEARING
  ones the diagnostic-string carve-out left behind:
  - aram/brawl/arena_coach.py: the U+2550 prompt-section banners + U+2192 decision
    arrows INSIDE the Haiku prompt AND the item_build wire-arrow that aram_coach:147
    re.split on the U+2192 char keys -> B2 coordinated (coach + Haiku-prompt + the 11
    tests/phase2_smoke/test_aram_coach_item_class_peers.py peers).
  - scripts/rebuild_sim_fixtures.py: the U+2192 / U+00B7 in GOLDEN fixture item_build /
    next / dragon_state values = the SAME wire arrow scripts/audit_ddragon_items.py:86
    re.split consumes; change fixtures + splitter together.
  - role_profiles.py: U+2022 emitted laning bullets + U+2192 combo arrows (emitted text).
  - coaches/adaptation_hint_{champion,cli}.py: emitted U+2191 / U+2193 / U+00B7 direction
    glyphs that adaptation_hint_champion.py:341-342 rsplit on the U+00B7 separator.
  - tft/tft_pbe_{engine,data}.py notes + tft/tft_vision_reader.py Sonnet vision-prompt
    U+2550 banners (LLM prompt content - a byte change = a model-input change).
  - coach_integration/{_profiles,_sr_prompt}.py: SR-prompt mechanics text + the U+2192
    build-string join.
  - dashboard/builders_last_match.py + core/{defensive_picks,aftergame_summary}.py:
    user-facing dashboard/summary U+2212 / U+00D7 / U+2264 / U+2265 / U+00B7 text
    (snapshot-fixture-backed - touching it shifts tests/snapshot_panels/fixtures/*.json).
  - NEVER touch: tools/p3_ascii_sweep.py + ops/audit/p2w5_sweep_sliceA.py GLYPH_MAP keys.
Run order: A3b-2 last (judgement). web/ .js/.css glyphs are NOT python-tokenizable
-> handled in B3 (UI-audit-gated), not here.

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
