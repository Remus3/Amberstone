# P3 PRUNE SWEEPS - work-map

DEEP-AUDIT phase P3. Slicer = `tools/p3_ascii_census.py` (bucketed non-ASCII
census + BOM/.ps1-mojibake-risk report). Mirrors the cycle-16/17 partition
harness. Newest-first.

P3 charter scope (DEEP_AUDIT_CHARTER line 52): vanguard/CV/capture caveats out;
2-PC/gamepc out; BOM/smart-quote/encoding retro-sweep; em-dash drift check.

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
Dominant class = U+2500 box-draw dividers in `#`/`//`/`/*` comments + decorative
U+00D7/U+2248/U+00B7/U+2192 in comments. Trees (non-test, non-DS-engine, non-web-render):
core/ dashboard/ lcu/ ops/ tools/ agents/(non-test) app/ scripts/ tft/ vision_server/
coach_integration/ game_reader/ modes/ modules/ config/ root .py (composition_advisor,
role_profiles, item_advisor, web_dashboard, performance_tracker). ~per-file balanced
ASCII swap; gate = py_compile + full dual suite (these are runtime modules, Tier-1/2).
Slice with tools/p3_ascii_census.py output; verify each U+2500 is comment-context
(not a print-banner string a test asserts on) before swap.

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
