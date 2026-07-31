# P3 PRUNE SWEEPS - work-map

DEEP-AUDIT phase P3. Slicer = `tools/p3_ascii_census.py` (bucketed non-ASCII
census + BOM/.ps1-mojibake-risk report). Mirrors the cycle-16/17 partition
harness. Newest-first.

P3 charter scope (DEEP_AUDIT_CHARTER line 52): vanguard/CV/capture caveats out;
2-PC/gamepc out; BOM/smart-quote/encoding retro-sweep; em-dash drift check.

---

## DONE - cycle 31 (item 428): A3b-2 sub-slice - role/SR-profile prompt-substrate raw glyphs -> ASCII (3 files, Tier-1)

- The role-profile + SR/champion-profile Haiku prompt-substrate raw non-ASCII BYTES.
  `role_profiles.py` (5 U+2192 combo arrows in role prose -> `->`; 39 U+2022 leading
  laning/ARAM list bullets in VAYNE_TOP_PROFILE + ARAM_ITEM_RULES -> `- `),
  `coach_integration/_profiles.py` (2 U+2192 in CHAMPION_PROFILES mechanics prose),
  `coach_integration/_sr_prompt.py` (1 U+2192 in the SR `full_build` `" -> ".join(fb)`).
  commit `fcd05f3d`.
- Per-hit override (NOT GLYPH_MAP `*` = multiply): the U+2022 are LEADING LIST markers
  -> `- ` (a `re.sub(r'(?m)^-(?=\S)','- ')` restored the bullet space the raw
  `"• "`->`"-"` replace dropped).
- Split-on proof (per-hit, NOT a sed): the ONLY repo U+2192 `re.split` consumers are
  `aram_coach.py:147` (Haiku item_build wire) + `audit_ddragon_items.py:86` (golden
  fixtures) - NEITHER reads these 3 files (`aram_item_context`/`ARAM_ITEM_RULES` are
  imported ONLY by `_profiles.py`, never `coaches/`); the SR `full_build` `" -> ".join`
  is producer-only (never split back). ZERO test asserts these glyphs.
- SCOPE = SOURCE BYTES only (the P3 byte-purge invariant). DEFERRED new sub-slice:
  `_sr_prompt` (the whole SR + ARAM Haiku system prompt) + `role_profiles.aram_item_context`
  still carry `\uXXXX` ESCAPES emitting U+2014 EM-DASHES / U+2550 banners / U+2192 -
  7-bit-ASCII SOURCE, OUT of P3 byte-scope (cycle-22 precedent: ASCII-escapes are a
  separate runtime-output concern), so this slice asserts source bytes NOT emitted output.
  The escaped-glyph emitted normalization (esp. the em-dashes in a live Haiku prompt) is an
  LLM-prompt-INPUT change (a byte change = a model-input change) -> its own validated gate.
- Gate (Tier-1, prompt-substrate local logic, no engine/schema/Share/ENGINE/DS-restart/
  live-RC-restart): py_compile 3/3; all 3 files ZERO raw non-ASCII; ruff clean; owning
  suite (test_role_profiles_ascii_item428 + test_coach_prompt_format_safe +
  test_sr_coach_choices_emit + test_coach_choices_alt_hotkey + test_cc_conditional_impact_context
  + test_enemy_cc_threat_context + test_cc_blended_ehp_context + test_ds_pick_consumption_p1l11
  + test_p2w1_app_b) = 226 passed / 31 subtests; NEW guard
  `tests/test_role_profiles_ascii_item428.py` (3) green.

---

## DONE - cycle 30 (item 427): A3b-2 sub-slice - dashboard/summary cluster glyphs -> ASCII (3 files, Tier-1)

- The user-facing last-match / defensive-picks / aftergame-summary readable-math +
  middot-separator glyphs. `dashboard/builders_last_match.py` (8 lines: U+2212 minus ->
  `-`, U+00D7 mult -> `x`, U+2264/U+2265 -> `<=`/`>=`, U+00B1 -> `+/-`), `core/defensive_picks.py`
  (L118 clause middot -> ` - `, L237 `" * ".join` separator -> `" | "`), `core/aftergame_summary.py`
  (L326 + L343 `" * ".join` separators -> `" | "`, L343 `{n}x {w}` mult -> `x`).
- Per-hit separator overrides (NOT the GLYPH_MAP default `*` = multiply): the three `.join()`
  middots are LIST separators, not products -> ` | ` (L237 bits carry `/` + `()`; L326 bullets
  carry their own ` - `, so `|` stays unambiguous); the L118 two-word clause -> ` - ` (house style).
- DEFERRED to P8 (by design, cycle-22 precedent): `aftergame_summary.py:406` keeps the win/loss
  status pair U+2713 `ok`-check + U+26A0 warn (the warn glyph is unmapped in GLYPH_MAP). A matched
  status-emoji pair = a P8 readability decision, not a mechanical glyph swap. So builders/defensive
  go 100% ASCII; aftergame retains exactly those 2 markers (guard-pinned).
- Blast radius proof (per-hit, NOT a sed): repo-wide the ONLY split/regex consumers of any of these
  glyph classes are `aram_coach.py:147` + `audit_ddragon_items.py:86`, both on U+2192 `->` (the B2
  wire-arrow, a SEPARATE slice) - neither touches this cluster. The cluster middots/math are
  `.join()`-only / display-only. The workmap "snapshot-fixture-backed" flag was a conservative
  over-flag: grep found the cluster's strings in ZERO test asserts, and the glyph-bearing snapshot
  fixtures (`tests/snapshot_panels/fixtures/sr.json`) carry only INPUT coaching glyphs (wave/map),
  not cluster output - snapshot suite passes unchanged, no fixture regen.
- Gate (Tier-1, local-logic, no engine/schema/Share/ENGINE/DS-restart/live-RC-restart): py_compile
  3/3; builders+defensive 0 non-ASCII, aftergame residual == exactly [U+26A0, U+2713]; ruff clean;
  owning suite (test_last_match_by_ts + test_p2w1_core_d + test_p2w1_dash_e + snapshot_panels
  last_match/active_match/panel_snapshots) 55 passed / 15 subtests; NEW guard
  `tests/test_last_match_ascii_item427.py` 3 green.

---

## DONE - cycle 29 (item 426): A3b-2 sub-slice - adaptation_hint coach-emit glyphs -> ASCII (18 lines / 2 files, Tier-1)

- First A3b-2 (non-DS load-bearing code-string) sub-slice. `coaches/adaptation_hint_{champion,cli}.py`:
  U+2191/U+2193 trend arrows -> `^`/`v`, U+2192 HOT/COLD -> `->`, the flat/unknown marker
  U+00B7 -> `-` (repo no-data sentinel), and the U+00B7 SEPARATOR -> `" | "` (the `" | ".join`,
  the line-342 `insight_card` `rsplit` trim boundary, and the 4 cli table separators, all in lockstep).
  commit `04dbc6a4`.
- Per-hit override (NOT the GLYPH_MAP default `*`): `insight_card` is a clipboard/Discord-paste card
  where `*text*` renders italic, so the separator is `" | "` not `*`. Also fixed a pre-existing doc/code
  drift (the docstring already said a `*` boundary while the code rsplit on the middot - both now `" | "`).
- Blast radius = exactly 2 files (repo-wide grep: the sole glyph-splitting consumer is
  `adaptation_hint_champion.py:342`; no test asserts the glyphs; `_supervisor_http` serves the card as
  opaque text). The pre-existing `str | None` type-hint + `today|24h` help pipes left untouched.
- Gate (Tier-1, coach-emit local logic, no engine/schema/Share/ENGINE): py_compile 2/2; both modules
  ZERO non-ASCII; ruff clean; owning suite (`test_p2w1_coach_b` format_hint_line + `test_round18`
  insight_card max_chars-trim + `test_coach_prompt_format_safe`) 30 passed; NEW guard
  `tests/test_adaptation_hint_ascii_item426.py` (2) green. No DS suite/restart/Share; no live RC restart.

---

## DONE - cycle 24 (item 420): DS-engine ASCII sweep slice B1b - string-token + JSON _meta glyphs (750 subs / 13 files + Share re-sync)

- Completes the DS-engine ASCII retro-sweep B1a began. B1a swept comment+docstring
  tokens; B1b sweeps the residual STRING-token glyphs: 76 across 9 .py (emit-notes /
  f-string display text / server HTML help) + 674 across the 4 registry JSONs' _meta
  description/rationale fields (champion_block_index 651 / form_index 11 /
  archetype_weights 9 / max_priority 3; verified glyph-free outside _meta - no key or
  data-value glyph, no test asserts on _meta content). DS tree now 100% ASCII except
  CHANGELOG.md (.md, 246, Share-excluded -> P8). commit `d8f7f93c`.
- Per-hit judgement (NOT a sed): sole structural consumer tree-wide =
  tests/test_effects_expansion.py:3892 (re.search on the "armor X -> Y" emit-note),
  regex + stale comment updated in lockstep. Mappings = the cycle 19-23 GLYPH_MAP
  (-> x / <= alpha beta *) with ONE override: beam.py:142 item-name separator
  U+00B7 -> " / " (separator, not multiply "*"); server.py's 2 U+00B7 ARE multiply
  (alpha*dps + beta*ehp) so stay "*".
- NEW durable ops/audit/p3c24_b1b_sweep.py (transform, LF-atomic) +
  p3c24_token_equiv.py (proof).
- Gate (Tier-2, DS tree + Share): token-equiv PROOF 9/9 (every NON-string token
  byte-identical to HEAD = engine logic untouched; every changed string token ==
  transform(HEAD-token)); py_compile 9/9; JSON parse 4/4; DS-dir 7095p/1s/1942sub
  exit 0 (byte-identical count to B1a); tests/ 7887p/2s/109sub exit 0; ds_share_sync
  rewrote Share/src (336 files) + --check in-sync. NO ENGINE bump (computed output
  byte-identical, proven). An accidental operator reboot mid-slice restarted
  RC-DaemonSlayer -> live :8893 already serves ASCII notes (1.121.0, 172 champs,
  healthy). NO live RC restart.

---

## DONE - cycle 23 (item 419): DS-engine ASCII sweep slice B1a - comment+docstring-token-only (1714 subs / 19 .py + Share re-sync)

- First P3 touch of the DS-engine tree (agents/daemon_slayer/*.py) - the last tree
  the cycle 19-22 safe-sweep excluded as B1 LOAD-BEARING-COORDINATED. Carved the
  provable-safe comment+docstring subset off the load-bearing emit-arrow remainder
  by reusing the EXISTING tools/p3_ascii_sweep.py --apply (COMMENT) + --doc-apply
  (DOCSTRING) over agents/daemon_slayer/*.py (top-level engine via bash non-recursive
  glob - NOT the c17-swept tests/ subdir). commit `3b468861`.
- 1649 comment + 65 docstring glyph subs / 19 .py, 0 unmapped (U+2500 box-draw
  `# --- ... ---` section dividers dominate; arrows/math/greek all in GLYPH_MAP).
  String-token glyphs untouched BY CONSTRUCTION -> every emitted/regex-matched arrow
  preserved (dps.py "armor X -> Y" note + test_effects_expansion.py:3892 regex intact).
  DS-engine residual non-ASCII 2036 -> 322 (all string-token: U+2192 124 + U+00D7 169
  + greek/middot; -> B1b). stats.py latent-CRLF -> LF (reference_repo_eol_crlf_guard,
  git status hid it via .gitattributes eol=lf).
- Share mirror re-synced (tools/ds_share_sync.py rewrote 19 Share/src mirror files +
  restamped MANIFEST; --check in-sync).
- Gate (Tier-2, DS tree + Share): NEW durable ops/audit/p3c23_token_equiv.py PROOF
  PASS 19/19 (for each file every token that is NOT comment + NOT docstring, incl every
  NON-docstring STRING literal = the emit-arrows, byte-identical (type,string) to
  `git show HEAD:f`); py_compile 19/19; DS-dir suite 7095p/1s/1942sub exit 0
  BYTE-IDENTICAL pre/post (p3c23_ds_{baseline,postedit}.txt). NO ENGINE bump
  (committed + live :8893 both 1.121.0 - synopsis P0 1.120.0 was STALE, re-probed
  live over HTTP), NO DS restart, NO live RC restart. CI run 27523209366 GREEN.

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
  - role_profiles.py: DONE cycle 31 (item 428) - 39 U+2022 leading bullets -> `- ` + 5
    U+2192 combo arrows -> `->` (raw bytes). The aram_item_context `->` ESCAPES remain
    (ASCII source, emitted-glyph deferred sub-slice). See above.
  - coaches/adaptation_hint_{champion,cli}.py: DONE cycle 29 (item 426) - arrows/marker -> ^/v/-,
    separator + the line-342 rsplit boundary -> " | " (Discord-safe, not GLYPH_MAP "*"). See above.
  - tft/tft_pbe_{engine,data}.py notes + tft/tft_vision_reader.py Sonnet vision-prompt
    U+2550 banners (LLM prompt content - a byte change = a model-input change).
  - coach_integration/{_profiles,_sr_prompt}.py: DONE cycle 31 (item 428) - the RAW BYTES
    (2 U+2192 CHAMPION_PROFILES prose + the 1 U+2192 SR `full_build` join) -> `->`. DEFERRED
    escaped-glyph sub-slice: `_sr_prompt`'s whole SR + ARAM Haiku system prompt is authored
    in `\uXXXX` ESCAPES emitting U+2014 EM-DASHES + U+2550/U+2500 banners + U+2192/U+2022
    (ASCII source, out of P3 byte-scope) - an LLM-prompt-INPUT change, own validated gate.
  - dashboard/builders_last_match.py + core/{defensive_picks,aftergame_summary}.py:
    DONE cycle 30 (item 427) - readable-math (U+2212/U+00D7/U+2264/U+2265/U+00B1) + the 3 middot
    `.join` separators -> ASCII (` | ` / ` - `, per-hit not GLYPH_MAP `*`). builders+defensive 100%
    ASCII; aftergame keeps the U+2713/U+26A0 win/loss status pair -> P8. The "snapshot-fixture-backed"
    flag was an over-flag (cluster strings in 0 test asserts; sr.json glyphs are input not output). See above.
  - NEVER touch: tools/p3_ascii_sweep.py + ops/audit/p2w5_sweep_sliceA.py GLYPH_MAP keys.
Run order: A3b-2 last (judgement). web/ .js/.css glyphs are NOT python-tokenizable
-> handled in B3 (UI-audit-gated), not here.

### B. LOAD-BEARING-COORDINATED (DEFER - engine+test+resync together, NOT a sed)
1. DS-engine agents/daemon_slayer/*.py + Share/src mirror.
   - B1a DONE cycle 23 (item 419): the comment+docstring-token subset (provable-safe,
     reused p3_ascii_sweep --apply/--doc-apply). 1649 comment + 65 docstring subs / 19
     .py + Share re-sync; token-equiv PROOF 19/19 + DS suite byte-identical. DS-engine
     non-ASCII 2036 -> 322 (all string-token). See above.
   - B1b DONE cycle 24 (item 420): the residual STRING-token glyphs - 76 across 9 .py
     (emit-notes / f-string display / server HTML) + 674 in the 4 registry JSON _meta
     fields. The c17-flagged U+2192 arrow (test_effects_expansion.py:3892 <- dps.py
     "armor X -> Y" note) converted with its regex in lockstep; token-equiv PROOF 9/9
     (non-string tokens byte-identical) + dual suite byte-identical + Share re-sync.
     NO ENGINE bump (computed output byte-identical). DS tree now ASCII-COMPLETE except
     CHANGELOG.md (.md -> P8). See above.
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
