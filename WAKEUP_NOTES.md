# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-28n - The commit gate's ruff half was dead on the channel that matters, for three weeks.

**Operator session (not a loop cycle). Tier-1, ENGINE-IMPACT NONE.** `15d07d3c` + `569dd364`. The filed question from `425fbb75`: why did `tools/precommit_gate.py` not block the net-new ruff UP031 that `afcbcf79` put in its OWN source.

**The filed hypothesis was wrong and cheap to refute.** It was not "local ruff differs from the runner's" - local ruff 0.15.12 flags that exact line under the project `ruff.toml`, measured. The gate never asked it. It shelled to `sys.executable -m ruff`, and `.githooks/pre-commit` launches the gate through the `py` launcher, which on Legion resolves to the dep-less pythoncore runtime with NO ruff. rc=1, empty stdout, `findings = []`, pass. **Fail-open AND fail-silent.**

**The gate runs on two channels with two different interpreters and the invocation was hardcoded for one at a time.** PreToolUse gets Python314 pythonw (owns ruff); the git hook gets the launcher. `ceb2f584` (2026-07-07) flipped launcher -> `sys.executable` to fix the first and silently broke the second - the AUTHORITATIVE one per CLAUDE.md, and the only one a headless bypass run gets. The stale comment above the call still described pre-`ceb2f584` behaviour, which is why it read as correct on every review since.

**Fix:** `_ruff_candidates` / `_resolve_ruff` probe `--version` and take the first that answers. No ruff anywhere still exits 0 (blocking a fresh clone would wedge the loop; CI is the backstop) but now WRITES THE WARNING. Phase-1 repro went EXIT=0 -> EXIT=2.

**Then CI went red on my fix, and both failures were mine and both were right.** `test_skip_condition_hygiene.py` classified my `requires_ruff` mark UNRESOLVED because it gated on a subprocess probe the resolver cannot see - re-gated on `find_spec` + `shutil.which`. `test_bare_py_ban.py` caught the launcher spelled before a script path in prose. **That second one paid for itself:** the launcher was in my candidate list as a fallback, and the launcher is precisely the dep-less runtime that caused the bug. Dropped; the Legion fallback is now the canonical absolute interpreter.

**For next time:** neither guard is reachable from the /done section-0 gate (ruff + touched module + 3 hygiene suites). They are repo-wide tracked-surface guards in `tests/` that only the full run reaches. A tools/ or tests/ change with prose about interpreters should run `tests/test_bare_py_ban.py tests/test_skip_condition_hygiene.py` locally before pushing.

**Do NOT redo:** the diagnosis is closed - do not re-open "local ruff differs from the runner". `tools/edit_lint_check.py` carries the same `sys.executable` assumption and was deliberately LEFT: it is PostToolUse-only under Python314 (correct there) and advisory, not blocking.

**Live at wrap:** the gemini loop (pid 9380, run `eadf15e3`) is mid-cycle on R223 - its `docs/ORCHESTRATION_PLAN.md` row is unstaged and says `(fill sha)`. I pushed its two R223 commits along with mine; leave the plan row to it.

---

# 2026-07-28m - R222 RM-125. The tool I shipped in slice A had a bug, and slice B found it.

**Cycle 29, gemini-loop. Tier-1. ENGINE-IMPACT NONE - no DS math, no schema, no served path, no `ENGINE_VERSION`, no `:8893` bounce, no RC restart.** HEAD `c7900b8c` -> `4ef1a805`. RC 13935 passed / 106 skipped / 1342 subtests, fresh.

**The premise held for once, and I checked before dispatching.** The directive tagged its own headline claim `[UNVERIFIED]`. A whole-file byte scan read **3153** non-ASCII chars across **31** `.js`/`.css`/`.html` files against the 3154 filed in ROADMAP prose - off by one, substantially correct - so the unit was real rather than a no-op. `tools/p3_ascii_sweep.py` re-read and confirmed `ast`-based Python-only, which is why it has never once looked at `web/`.

**The directive's 4-agent parallel block was REFUSED and the cycle ran SERIALIZED.** The executor override flagged colliding write sets. It was right for a second reason it did not give: slice A is a genuine PREREQUISITE, not a peer - its tokeniser DEFINES the comment/live partition that slice B censuses, so B could not have run first or concurrently and produced a correct answer.

**Slice A** shipped `tools/web_ascii_sweep.py` (JS `//` + `/* */` with string/template/regex awareness, CSS `/* */`, HTML `<!-- -->` only), TDD RED 2 failed / 34 passed -> GREEN 36, sweeping 2833 comment chars for 3153 -> 320. The false-positive side was MEASURED, not claimed: the verifier built two deliberately broken copies of the sweeper and watched the escaped-quote pin and the CSS-string pin each go red. The live half was proven untouched two independent ways - the verifier wrote its OWN tokeniser before reading the slice's, sentinel-replaced every comment span in both trees (0 of 28 files differed outside a comment), then eyeballed all 253 changed lines.

**Slice B is a docs slice that found a code bug, which is the shape worth remembering.** Its census showed the tool's 320 over-counts the RENDERED set - 59 were unreachable JS comment glyphs and 26 sit in `legacy_index.html`'s inline blocks - leaving **235** rendered chars across 16 files: STRIP-candidate-deferred 152, KEEP-deliberate-UI-glyph 52, **LOAD-BEARING 31**. Tracing why those 59 were unreachable is what exposed the defect.

**Slice C, unplanned: `_scan_template_subst` had no regex-literal case.** The `.replace(/"/g, "&quot;")` attribute-escaping idiom inside a `${...}` opened a phantom string that ate the closing brace and backtick, and three template literals ran away. Failure direction is UNDER-sweep and that was measured, not assumed (shipped-only comment territory was 0 bytes in every file, so no live byte could ever have been stripped) - but `tests/test_web_comment_lines_ascii.py` was passing VACUOUSLY over those regions, which is the guard-reports-green-by-not-looking class. Repro RED 4 failed / 1 passed first; the fix extracts `_scan_comment` and reuses the existing `_regex_may_start` predicate rather than copying the regex-vs-division heuristic, and caught a second instance of the same blindness the audit missed. Residue 320 -> 261.

**`_LIVE_HALF_DIGEST` is CIRCULAR across a tokeniser change and was not re-stamped blind.** The partition delta was proven gains-only (114 spans gained, 0 lost), the corrected classifier was run over BOTH trees to show byte-identical live halves for all 168 sources, and only then was the constant re-captured with its provenance comment rewritten to say what it now actually pins.

**Two things that must survive into the next session:**
1. **31 glyphs are LOAD-BEARING - a strip breaks BEHAVIOR, not looks.** `web/js/lib/items_index.js:62` carries `U+2192` as an alternation branch in the build-string split regex, and `web/js/panels/right_now.js:563-566` is a producer/matcher COUPLING where the three emitted glyphs are exactly the char class the next line's regex tests; the file's own comment at `:562` names the failure ("double DEFEAT"). Read `docs/RM125_web_live_glyph_adjudication.md` before touching one.
2. **`web/legacy_index.html` is NOT dead** - the opposite of the brief's hypothesis. `dashboard/routes_static.py:23-41` serves it at `?ui=legacy` AND as the automatic fallback when `index.html` throws. Its glyphs are live pixels. It also holds a raw `U+0081` C1 control char in a `content:` value at `:951` - mojibake, not design.

**Defect class closed, not just the directory.** Class = "non-ASCII in authored `.js`/`.css`/`.html`". Repo-wide byte scan found exactly ONE authored file outside `web/`: `tools/usage-mcp-server.js`, 218 -> 9, swept with the live-span text asserted byte-identical pre/post, and the guard widened to cover it. Everything else that scanned dirty is third-party (`data/meta_build` scraped pages, `.obsidian` vendored plugin) and is OUT-OF-SCOPE with reason in the commit body.

**NEXT:** RM-125 stays OPEN for the 235 rendered chars ONLY, routed to RM-122 (operator-present, rendered-pixel judgement, headless-forbidden). Do NOT let a future directive re-open the comment half - it is done and machine-guarded.

---

# 2026-07-28k - R220 competitor lift. The directive's target was fenced, and the best find was ours.

**Cycle 27, gemini-loop. Tier-0 docs-only. ENGINE-IMPACT NONE (repo + live DS both 1.262.0, no bounce, no Share sync).**

**The directive named "Overlay App F or Aggregator B live-game overlay" and three places on disk say do not.** `ROADMAP.md` RM-01 retires the rotation by name; the R100 and 2026-07-16 blocks in `COMPETITOR_LIFT_INDEX.md` both declare the live-overlay family DRAINED (the second counting five passes); Overlay App F already has two teardowns in `docs/_archive/`. So the INTENT was kept and the TARGET rotated, which is what the drain notes themselves instruct. Replacement picked by search, not preference: six keyword probes across every prior `COMPETITOR_LIFT_*.md` returned zero hits for wave management, wave simulators, CS trainers, minion waves, freezing, slow pushing. Lane / wave / minion-economy had never been looked at.

**Three premise corrections, all verified against files, and the first one matters beyond this cycle:**
1. **The laning `hold` band ALREADY SHIPPED.** `core/precomputed_laning_coach.py:68-74` carries five labels, `laning_band()` at `:271-309` implements the precedence off `_HOLD_LOW`/`_BACK_OFF`/`_TRADE` (`:79-81`). Only the raw engine is still 4-band (`agents/daemon_slayer/matchup.py:184-206`). **The open Lane-A work is the FLIP, not the band.** Any brief still saying "the vocabulary lacks a hold band" is stale.
2. **The Live Client emits `MinionsSpawning` and RC has never read it.** `dashboard/_state_cooldowns.py:18` names it; `:20-21` then passes an EMPTY event list because it wanted summoner-spell events that do not exist. Repo-wide grep returns that one comment.
3. Corpus is 2966 matches, not 3005.

**Deliverable `docs/COMPETITOR_LIFT_2026-07-28.md`, 7 findings. F1 filed as ROADMAP RM-124 (new, unbuilt):** a deterministic wave + cannon clock anchored on the live event - structurally `core/decision_detector.py:158-176` with a piecewise cadence - as a 4th event extract beside `dashboard/_liveclient.py:302-313` plus a pure `wave_callout()` beside `core/event_callouts.py:414`. Tier-1, no new data source, no key, no Claude, no schema lift, no ENGINE bump. **Its risk is real and is written into the row: three sources disagree on first-wave time (0:30 / 1:05 / 1:30) and the cannon breakpoint (14:00 / 15:00), and a 2025 change moved first-cannon arrival 2:05 -> 2:35** - anchor on the live `EventTime`, validate the cadence table in one real game before any flip. F4 CLOSED, data-blocked three ways (no minion entities on `:2999`, GEP gives kill counts only, Match-V5 has no minion event type) - do not re-pitch a live wave state machine.

**The best finding was RC-internal and the HAVE column found it by accident: RC renders a complete wave feature nobody built.** `web/js/panels/next.js:16-83` is a finished 3-lane FREEZE/TRADE/CRASH/DISENGAGE readout whose only writers repo-wide are test fixtures (`scripts/rebuild_sim_fixtures.py:166,191,229`) - it has rendered the "-" sentinel in every live game ever played. Five more producer-less identifiers beside it (`wave_state_now`/`wave_control`/`wave_freezes`/`cannon_cs_summary`/`gd_at_15`), plus an ARAM tier-shift rule that is dead because its live call site passes `wave_pct=None`. **Durable lesson: a rendered surface with a plausible name is not evidence of a producer, and the fixtures that make it look alive in tests are exactly what hides that.**

**Tempering note, in the RM-124 row so nobody oversells it:** `tools/hz_shadow_report.py:196-201` excludes crash/freeze/push from the laning agreement sample, so a wave clock will NOT move the Lane A number.

**Honest negative:** there is no standalone wave-simulator product. Six search angles, three targets torn down properly instead of eight skimmed. Realistic yield of this category is two findings plus two negatives.

**Gates (fresh, `-n 8 --dist loadfile`): DS 10100 passed / 5701 subtests; RC 13829 passed / 106 skipped / 522 subtests; 23929 total, 0 failed** - byte-identical to the R219 baseline, expected for docs-only. 0 non-ASCII across all touched docs. Plan tail-window protocol honored (R219 block relocated verbatim to `docs/ORCHESTRATION_PLAN_HISTORY.md`; newest row 9439 bytes from EOF vs the 16000 cap). ROADMAP 76513 / 81920.

**NEXT:** RM-124 is a clean Tier-1 slice - the event extract, the pure callout, and one live game to validate the cadence before any flip.
