# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---
# 2026-05-23 - item 154 operator-gated decision-owed parallel drain #2: cc_conditional wave 10 sidecar registry schema lift + smart-quote retro-sweep + L31 extension dashboard/+core/+tft/ SHIPPED (3 commits + 2 merges, pushed origin/main `df50ca9`; ENGINE 1.46.0 -> 1.47.0; DS :8893 restarted serves 1.47.0; RC :8888 unchanged)

Operator triggered "review github branches and close or merge as needed, then in parallel : start all open items in Operator-gated, decision owed". 5 stale remote worktree branches + wave9-cc-conditional-schema-lift all confirmed fully merged into main via `git log origin/main..origin/<branch>` empty diff; deleted via `git push origin --delete` x5. No open PRs. AskUserQuestion 4-question scope fork pinned: (Q1) cc_conditional wave 10 full pass (Recommended); (Q2) Smart-quote retro-sweep (Recommended); (Q3) L31 extension all three surfaces dashboard/+core/+tft/ (Recommended); (Q4) DD Defy SKIP (Recommended - still deferred). 3 worktree agents dispatched concurrent (orchestrator pattern items 134-153 extended to 19 consecutive runs).

**Slice A `20b3afa` (merge `90e3462`) feat(ds) cc_conditional wave 10 closure - same-spell-slot sidecar registry schema lift (36 files / +1097 / -40):**
- Parallel sidecar registry `_PER_SPELL_CC_CONDITIONAL_FORMS: Dict[champion, Dict[(spell, form_index), ConditionalCcEntry]]` in `agents/daemon_slayer/cc_conditional.py` preserves backward compat with ~244 test access lines pinning the primary registry shape `_PER_SPELL_CC_CONDITIONAL[champion][spell]`.
- `ConditionalCcEntry` gains optional `form_index: Optional[int] = None`. `get_conditional_entries()` merges both registries default-first then form_index ASC. New `_apply_per_form_entry_overrides()` extends JSON override key shape with 3-segment `Champion:Spell:FormIndex`.
- Wave 10 closures (+2 entries / 0 net-new champs both multi-form coexistence; 42/38 primary -> 44/38 total):
  - Karma W form_index=1 Mantra-empowered Renewal - root - durations (2.35, 2.45, 2.55, 2.65, 2.75)s at mid Mantra rank 2 (+0.75 bonus) - COND_FRENZY_STATE prob 0.4 (SECOND consumer; closes single-consumer state on wave 7 forward-marker tag) - verified via effects_descriptions[0] "Mantra Bonus: Focused Resolve's root duration is increased ... Renewal scales with Mantra's rank".
  - Hwei E form_index=2 Gaze of the Abyss - root - durations (1.2, 1.4, 1.6, 1.8, 2.0)s across 5 E ranks per Meraki Root Duration block - COND_CHANNEL_COMPLETION prob 0.4.
- NO new condition tag (reuses pre-existing COND_FRENZY_STATE + COND_CHANNEL_COMPLETION).
- ENGINE_VERSION 1.46.0 -> 1.47.0 + 31 DS test files bulk-rewrite of ENGINE pin (assertEqual contexts only).
- +56 tests in NEW `agents/daemon_slayer/tests/test_cc_conditional_wave10.py`: per-entry shape pins + multi-form coexistence + sidecar registry shape + form_index field defaults + REGISTRY_TOTAL growth + COND_FRENZY_STATE 2nd consumer + per-form override parsing + builder idempotence + wired-site grep pins + engine version pin + ASCII hygiene.
- `compute_cc_pressure("Karma", "sr", include_conditional=False) = 0.0` BYTE-IDENTICAL to 1.46.0; True = 1.9 (wave 1 + wave 10 sidecar both contribute).

**Slice B `b045618` tools smart-quote retro-sweep + drift guard test (40+ files via sweep, mojibake-aware byte-level rewrites):**
- NEW `tools/strip_smart_quotes.py` mirrors `tools/strip_em_dashes.py` precedent. Atomic `tmp.write_bytes + os.replace`. Codepoints in source via `chr()` to keep tool ASCII-clean.
- Per-codepoint rewrite counts (pre / post): U+2026 ellipsis 175 -> 0; U+2019 right-quote 12 -> 0 (4 still in frozen-skipped/mojibake); U+201C left-dquote 4 -> 0; U+2018 left-quote 4 -> 0; U+2013 en-dash 4 -> 0; U+2014 em-dash 4 -> 0; U+00A0 NBSP 1 -> 0. U+201D right-dquote 2279 -> 2275 (4 clean replaced; 2275 mojibake-preserved via byte-context detection of latin-1-misdecoded em-dash signature `c3 a2 e2 80 9d e2 82 ac`).
- Frozen-file hits SKIPPED + listed (NOT rewritten): `ops/rc_supervisor.py` (1380 mojibake U+201D), `ops/rc_dev_runtime.py` (1 U+2026), `core/moon_proxy.py` (1 U+2026), `core/log_setup.py` (1 U+2026).
- Mojibake-tainted REFUSED (non-frozen, separate UTF-8 byte-repair pass needed): `ops/rc_self_monitor.py` (539 mojibake U+201D), `ops/rc_state_validator.py` (259), `tft/tft_coach_engine.py` (97 mojibake + 5 clean replacements).
- NEW `tests/test_smart_quote_hygiene.py` drift guard walks repo with same exclusions + asserts no U+201C/U+201D/U+2018/U+2019/U+2013/U+2014 in tracked source (3/3 passes).
- 4 pre-existing drift-guard tests (`tests/snapshot_panels/test_{cd_ledger,spike_curve,ward_heat,draft_elo_panel}.py`) self-violating with literal smart quotes -> refactored to `chr(0x2014)` form.
- Direct push to main (not worktree branch; bash cwd-default behavior; matches item 150 Slice D precedent).

**Slice C `84aadde` (merge `df50ca9`) chore(types) L31 extension - type annotations on dashboard/+core/+tft/ public APIs (14 files / +49 / -45):**
- 44 surgical sites total: dashboard 6 + core 14 + tft 24. Typical patterns: `-> None` for mutators, `-> dict | None` / `Optional[T]` for readers, `-> "TftSnapshot | None"` via TYPE_CHECKING forward-ref in `tft/tft_state_reader.py`.
- Files: `core/coaching_data_lock.py` + `core/decision_detector.py` + `core/match_db.py` + `core/resource_manager.py` + `core/vision_tracker.py` + `dashboard/_context.py` + `dashboard/_handler.py` + `dashboard/server.py` + `tft/tft_coach_engine.py` + `tft/tft_live_analysis.py` + `tft/tft_ocr_reader.py` + `tft/tft_pbe_engine.py` + `tft/tft_state_reader.py` + `tft/tft_vision_reader.py`.
- 0 ruff violations / 0 reverts / 0 frozen-file touches.
- SKIPPED deliberate: `compute_cc_pressure` fallback stubs already `# type: ignore[misc]`, inner closures, dashboard route inner matchers already typed.

**Merge order:** Slice B pushed directly to main first `b045618`; Slice A worktree merged into main second as `90e3462` (ort, 0 conflicts, 36 files); Slice C worktree merged into main third as `df50ca9` (ort, auto-merged dashboard/_handler.py + tft/tft_coach_engine.py without conflict, 14 files). 0 merge conflicts across all 3 slices.

**Verified:**
- DS suite `agents/daemon_slayer/tests/` = **4130 passed / 1 skipped / 1 xfailed / 1726 subtests passed in 68.23s** (+56 vs 4074 baseline = exactly the wave 10 test file).
- RC suite `tests/` (excluding phase8_smoke) = **3254 passed / 67 subtests passed in 55.51s**.
- `tests/phase8_smoke/` = 74 passed / 1 failed pre-DS-restart; resolved post-restart to 75/75 (the 1 was the documented `test_live_three_profiles` engine pin mismatch per [[reference_ds_server_not_supervisor_watched]]).
- DS :8893 killed pid 9936 -> 10516 + `schtasks /Run /TN RC-DaemonSlayer` -> `/health` serves `engine_version=1.47.0 patch=16.10.1 champions=172 items=705`. HTTP not HTTPS at :8893 (DS server scheme reaffirmed).
- `py -m ruff check .` ALL CHECKS PASSED.
- `py -m py_compile` clean on all 15 touched files.
- RC :8888 responsive throughout (rc.pid=7356 alive=True mode=client; never restarted - non-frozen + non-coach-prompt edits).
- Pushed main as `df50ca9` to origin/main.

**Don't-redo:** The same-spell-slot sidecar registry pattern `_PER_SPELL_CC_CONDITIONAL_FORMS` is the canonical home for multi-form champion CC mechanics where the form_index differentiates two distinct CC behaviors on the same spell slot (e.g. Karma W default vs Mantra-empowered, Hwei E form 1 Disable vs form 2 Root). Future cc_conditional wave 11+ should consume this sidecar SHAPE directly without re-pitching the registry lift. The `ConditionalCcEntry.form_index` field defaults to None for backward compat - do NOT add it as a required field. The 4 mojibake-tainted files (`ops/rc_self_monitor.py` + `ops/rc_state_validator.py` + `tft/tft_coach_engine.py`) need a separate UTF-8 byte-repair pass (signature: latin-1-misdecoded em-dash `c3 a2 e2 80 9d e2 82 ac`) - the smart-quote tool deliberately REFUSES to rewrite mojibake context to avoid corrupting source. The 4 frozen files with smart quotes (`ops/rc_supervisor.py` + `ops/rc_dev_runtime.py` + `core/moon_proxy.py` + `core/log_setup.py`) need explicit frozen-file grant before sweep. The L31 extension is now CLOSED for dashboard/+core/+tft/ public APIs; future surface coverage would be `lcu/` + `coach_integration/` + `agents/` (operator-gated separately). The orchestrator-merge pattern (3-4 worktree agents on disjoint slices + tests gate + DS restart if ENGINE bumped + RC unchanged unless coach prompts touched + docs sync follow-up commit) is now 19 consecutive runs (items 134-154). Direct-to-main push by a worktree agent (Slice B this run, Slice D item 150) is acceptable for pure tool/docs/sweep work with zero conflict risk vs other slices touching disjoint files.

**Carries forward:** (a) Item 153 carries ALL unchanged EXCEPT (a)-relaxed: cc_conditional wave 10 is NO LONGER operator-gated (DONE this session); smart-quote retro-sweep is NO LONGER operator-gated (DONE - drift guard test now locks invariant going forward); BACKLOG L31 extension to dashboard/+core/+tft/ is NO LONGER operator-gated (DONE). (b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session. (c) DD Defy heal-on-takedown STILL deferred. (d) Live ARAM/SR smoke STILL pending. (e) Calibrations STILL operator-gated. (f) UI/UX live-game audit ritual owed once operator plays a real game. (g) DS conditional arc operator-CLOSED (s232). (h) Legion 1-PC consolidation (s169 option B) STILL operator-gated. (i) **NEW carry**: 4 mojibake-tainted files (`ops/rc_self_monitor.py` + `ops/rc_state_validator.py` + `tft/tft_coach_engine.py`) need separate UTF-8 byte-repair pass (operator-gated). (j) **NEW carry**: 4 frozen files with smart quotes (`ops/rc_supervisor.py` + `ops/rc_dev_runtime.py` + `core/moon_proxy.py` + `core/log_setup.py`) need explicit frozen-file grant before sweep (operator-gated). (k) **NEW carry**: L31 extension to `lcu/` + `coach_integration/` + `agents/` surfaces (operator-gated separately - this session closed dashboard/+core/+tft/). (l) Wave 11+ cc_conditional should consume sidecar registry shape directly. Frozen-file grant NOT used this session.

---
# 2026-05-23 - operator-gated decision-owed parallel drain: Meraki schema lift + cc_conditional wave 9 + BACKLOG L14 closure + minimap-crop log suppression + type hints on public coach API SHIPPED (4 commits + 2 merges, pushed origin/main `100c9c9`; ENGINE 1.45.0 -> 1.46.0; DS :8893 restarted serves 1.46.0; RC :8888 unchanged)

Operator "in parallel : start all open items in Operator-gated, decision owed" -> AskUserQuestion 4-question scope fork pinned: (Q1) Meraki extractor schema lift FULL + cc_conditional wave 9 (Recommended); (Q2) BACKLOG L14(a) kills->takedowns Option B keep 9-col additive (Recommended); (Q3) minimap-crop log suppression (Recommended; smart-quote sweep + .mcp.json wiring SKIPPED); (Q4) BACKLOG L31 type hints + ruff on public coach API. 4 worktree agents dispatched concurrent (orchestrator pattern items 134-151 extended to 18 consecutive runs).

**Slice A `051e606` (merge `9383a31`) feat(ds) cc_conditional wave 9 + Meraki extractor schema lift (39 files / +5435 / -106):**
- `tools/daemon_slayer_abilities_extract.py` schema-lifted to add `effects_descriptions: list[str]` per form record (purely additive; damage_blocks + parse_status math byte-identical).
- Re-extracted `data/daemon_slayer/16.10.1/champion_abilities.json` at 1.46.0 schema (+33% size, descriptions added; 171 champs / 705 items / 16.10.1).
- Wave 9 closures (+3 entries / +3 net-new champs; registry 39/35 -> 42/38): Renekton W Ruthless Predator Reign-of-Anger empowered stun 1.5s (first consumer of wave 7 forward-marker COND_FRENZY_STATE), Hwei E form_index=1 Grim Visage Disable 1.0-1.5s, Neeko E Empowered Root 1.8-3.0s.
- REJECT verdicts (4 candidates schema-lift-verified NEGATIVES): Karma W form 1 (registry schema needs same-spell-slot lift), Aatrox R (post-R fear is minion-only per description), Volibear R (Disable Duration is turret-only), Briar W (frenzy is self-buff-only).
- +58 tests (test_cc_conditional_wave9.py 36 + test_abilities_extract_descriptions.py 22) + 31 DS test files bulk-rewrite of ENGINE pin 1.45 -> 1.46 + 2 test pin relaxations.

**Slice B+C `62eb8b2` chore: minimap-crop log suppression + BACKLOG L14 obj_participation closure (3 files / +20 / -3):**
- `dashboard/_handler.py::_SUPPRESS_LOG_PATHS` tuple +1 entry `"GET /api/minimap-crop "` (was top non-suppressed contributor at 0.417/sec per item 151 Slice C audit; ~1500 log lines/hr saved). +1 test pin in `tests/test_handler_log_spam_suppress.py`.
- `BACKLOG.md` L14 obj_participation flipped from operator-gated to operator-decided Option (b) keep 9-col additive (avoids rebaselining 624 historic role-grades). CLOSED.

**Slice D `97bdbb4` (merge `100c9c9`) chore(coaches) type annotations on public coach API (6 files / +17 / -9):**
- 6 surgical annotation sites: ArenaVisionReader.read / BrawlVisionReader.read return types; coaches/feedback.py TYPE_CHECKING + apply_grade.cache; sr_coach Coach.shutdown -> None; tft_coach Coach.set_worker.worker via TYPE_CHECKING; tft_pbe_coach Coach.{submit_state,reset_state,shutdown} -> None.
- 0 ruff violations net (coaches/ already clean pre-edit; agent's 1 self-introduced F821 resolved in-pass via TYPE_CHECKING guard).
- Coach prompts UNCHANGED.

**Merge order:** Slice B+C committed directly to main first as `62eb8b2`; Slice A worktree agent rebased + landed `051e606` -> merged into main as `9383a31`; Slice D worktree agent rebased + landed `97bdbb4` -> merged as `100c9c9`. 0 merge conflicts (all 4 slices touched disjoint files).

**Verified:**
- full pytest `tests/` + `agents/daemon_slayer/tests/` = **7399 passed / 1 skipped / 1 xfailed**. The 1 expected `test_sr_draft_profile_engine.py::test_live_three_profiles` pre-DS-restart engine_version pin mismatch RESOLVED post-restart.
- DS :8893 killed pid 14292 + `schtasks /Run /TN RC-DaemonSlayer` (per [[reference_ds_server_not_supervisor_watched]]) -> serves engine_version=1.46.0 / patch 16.10.1 / 172 champs / 705 items; live test now passes 18/18.
- `ruff check .` ALL CHECKS PASSED.
- RC :8888 responsive throughout (mode_key=client idle; never restarted - non-frozen + non-coach-prompt edits).
- Pushed main as `100c9c9` to origin/main.

**Don't-redo:** Meraki schema lift is now DONE - the `effects_descriptions` field is the canonical home for description-text mechanics that don't fit the structured leveling[]/damage_blocks pipeline; future cc_conditional wave 10+ should consume this field DIRECTLY before re-pitching candidates. The 4 wave 9 REJECT verdicts are now schema-lift-verified NEGATIVES - do NOT re-pitch Karma W form 1 / Aatrox R / Volibear R / Briar W without new evidence. The wave 7 COND_FRENZY_STATE forward-marker tag is now ACTIVE (1 consumer); COND_RANGE_GATED remains forward-marker (0 consumers). The `_SUPPRESS_LOG_PATHS` tuple is now 9 entries; ward-heat at 0.149/sec becomes top non-suppressed but still below 1/sec threshold. The 6-site type annotation pass DELIBERATELY scoped to coaches/ only (operator-gated to public coach API); dashboard/+core/+tft/ surfaces NOT in this session's scope.

**Carries forward:** (a) Item 152 carries ALL unchanged EXCEPT Meraki schema lift is NO LONGER operator-gated (DONE this session). (b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session. (c) DD Defy heal-on-takedown STILL deferred. (d) Live ARAM/SR smoke STILL pending. (e) Calibrations STILL operator-gated. (f) BACKLOG L14 NOW CLOSED. (g) BACKLOG L31 type hints NOW CLOSED for public coach API; dashboard/+core/+tft/ still open separately. (h) UI/UX live-game audit owed. (i) Smart-quote retro-sweep STILL operator-gated (skipped this session). (j) DS conditional arc operator-CLOSED (s232). (k) Legion 1-PC consolidation (s169 option B) STILL operator-gated. (l) Wave 10+ cc_conditional should consume `effects_descriptions` field directly - the schema lift this session is the durable substrate for description-text mechanic capture. Frozen-file grant NOT used this session.

---
# 2026-05-23 - living-docs cleanup pass: archive completed items + list open/pending (1 commit pending; docs-only; no DS restart; no RC restart; no ENGINE bump)

Operator "cleanup the .md's of completed items if not necessary to be present for future use & list to me all items that are still open or pending operator". Pure housekeeping pass per session-workflow last-3 rule.

**Archived (verbatim, zero rewrite):**
* CLAUDE.md items 94-149 (56 ledger entries spanning 2026-05-19/22 = DS audit iter chain + cc_blended_ehp ecosystem + cc_conditional ecosystem + obj_participation 9-col + s220 PGR S2-S5 + headless-upgrade runs + Fleet OAuth) -> `docs/history_notes.md` new section at top. Items 150-152 stay inline at full fidelity. Settled-section pointer flipped "items 1-93" -> "items 1-149".
* WAKEUP_NOTES items 148+149 -> already in `docs/history_notes.md` via the CLAUDE archive (single archive section covers both); cost-trace + item 151 + item 150 + this session entry inline.

**Compressed in place:**
* BACKLOG.md L13: cc_blended_ehp + cc_conditional 10-consumer chain (~5500 chars) -> one-paragraph SHIPPED summary pointing at CLAUDE archive (items 126-148).
* BACKLOG.md L80: cdragon-arena formula evaluator entry -> 1-liner SHIPPED.
* ROADMAP.md lines 11-72: shipped items 94-149 SHIPPED entries -> single pointer block; older s218-s246 SHIPPED entries kept inline for AUTONOMOUS_AUDIT chain context per ROADMAP-95 "Now + Next only".

**Byte deltas:**
* CLAUDE.md 483801 -> 43518 (-440K). Reloaded every turn so this is the biggest latency lever.
* ROADMAP.md 294689 -> 174953 (-120K).
* BACKLOG.md 33638 -> 23337 (-10K).
* WAKEUP_NOTES.md 32741 -> 17528 (-15K) (already trimmed to 3 sessions per s222 sync-all-md skill).
* history_notes.md +590K (verbatim absorption).

**Open/pending operator list surfaced inline.** Full list in chat output above; not duplicated here.

**Don't-redo:** items 94-149 are in `docs/history_notes.md` verbatim - do NOT restore them inline or treat their absence as drift; the Settled-section pointer at CLAUDE.md is the inline marker. The session-workflow last-3 rule is now strictly enforced in CLAUDE / WAKEUP. The ROADMAP pointer at line 11 covers May 19-22 sessions; older s218-s246 entries are intentionally kept for AUTONOMOUS_AUDIT chain context. The 27 panel CSS = 27 dashboard.css @imports parity guard (item 149 `test_dashboard_css_panel_imports_parity.py`) was unchanged; do NOT re-litigate.

**Carries forward:** ALL item 150/151/152 carries-forward unchanged (RC-PostmortemAnalyze 2026-05-24 04:15 first run = verify LastTaskResult=0 NEXT SESSION, the immediate-tomorrow check; DD Defy deferred; live ARAM/SR smoke pending; Meraki extractor schema lift operator-gated for cc_conditional wave 9+; BACKLOG L14 (a) kills -> takedowns flip operator-gated; UI/UX live-game audit owed; calibrations operator-gated; Slice C MINOR PROPOSAL `/api/minimap-crop` to `_SUPPRESS_LOG_PATHS` operator-gated). Frozen-file grant NOT used this session.

---
# 2026-05-23 - cost-trace gap C closure: wire 11 untracked messages.create + construction-layer shim SHIPPED (1 commit `7ad4056`, pushed; CI green 1m23s; non-engine; non-frozen; no DS/RC restart)

Operator triggered docs/cost_trace.md "Recommended follow-ups (not auto-applied; tracked here)" -> AskUserQuestion-picked "Both: wire 11 sites + add construction-layer shim (Recommended)" -> full vertical slice executed end-to-end.

**Shipped (`7ad4056` 14 files / +643 / -35):** NEW `core/cost_tracker.py::record_anthropic_response(resp, *, model, purpose) -> dict | None` shared module-level helper (sibling of `_BaseCoach._record_coach_call` private + `vision_server._record_to_cost_tracker` private) so all 11 sites funnel through ONE pricing-table + Prometheus path. NEW `core/anthropic_client.py::tracked_anthropic(api_key, *, purpose, default_model="")` construction-layer shim returning a real `anthropic.Anthropic` client with `messages.create` rebound to a wrapper that auto-records - defense-in-depth so a future 12th call site is tracked by default if the caller forgets the helper.

**11 wired sites (purpose= label is the by_purpose key in data/spend/YYYY-MM-DD.json):**
- 6 coach-side: aram_team_analyzer / experimental_builder / champ_select_coach / replay_coach / champ_select_brief (dashboard/_champ_select.py) / agent7_warm
- 5 TFT (highest priority polling/warm cadence per audit): tft_coach / tft_pbe / tft_live_analysis / tft_live_aug_select / tft_vision (SONNET - the most expensive untracked lane)

**+27 tests in NEW `tests/test_cost_tracker_response_helper.py`** across 5 classes: RecordAnthropicResponseTests 8 (usage extraction defensive on None/missing/blank, fallback to resp.model, swallows ledger exceptions, blank purpose -> _unspecified) / TrackedAnthropicShimTests 4 (wrapper applied, real API errors propagate, recording failures caught, default_model fallback) / WiredSitesImportSmokeTests 2 (public symbols) / WiredSitesGrepTests 11 (one per audit site pins import + purpose= label so a future regression rip fails CI before live cadence hits) / AsciiHygieneTests 2 (new code blocks ASCII-clean).

**docs/COST_TRACE.md updated:** follow-ups 1+2 flipped "tracked here" -> "SHIPPED 2026-05-23"; call-site matrix all 11 sites YES with per-site purpose label; reconciliation section reframed (gap is closed; pricing-table drift only, no untracked surface).

**Verified:** full RC suite **3250 passed / 0 failed** (+27 over 3223 baseline = exactly the new test file); py_compile + ruff clean across all 14 touched/new files; 0 non-ASCII bytes added by this diff (pre-existing carryover in tft/* + coaches/* left in place per operator-gated retro-sweep policy); CI green 1m23s on first push. No DS restart. No RC restart. No ENGINE bump. No frozen-file edits.

**Don't-redo:** The shared helper `core.cost_tracker.record_anthropic_response` is the canonical chokepoint for any non-`_BaseCoach` site - do NOT duplicate the usage-extraction logic in a new caller. The `tracked_anthropic` shim is INTENT defense-in-depth, NOT replacement for the helper - sites with per-call purpose granularity (e.g. vision_server vision_relay vs coach_relay from same client) should keep calling the helper directly. `WiredSitesGrepTests` pins the wire-in at each of the 11 sites by grep-matching `record_anthropic_response` + `purpose="<label>"` - if a future refactor renames the helper or rips the wire, these 11 tests fail before any live cadence hits the missing telemetry. The 3rd cost-trace audit (2026-04-29 gap A + gap B + this gap C) has CLOSED the recurring "new coach forgot to wire telemetry" pattern.

**Carries forward:** Item 151 carries-forward (a)-(k) ALL unchanged (Meraki parse-strip standing constraint, schema lift operator-gated, RC-PostmortemAnalyze first scheduled run 2026-05-24 04:15 = verify LastTaskResult=0 next session, DD Defy deferred, live ARAM/SR smoke pending, calibrations operator-gated, BACKLOG L14 kills->takedowns flip operator-gated, UI/UX live-game audit owed, Slice C MINOR PROPOSAL `/api/minimap-crop` to `_SUPPRESS_LOG_PATHS` operator-gated, wave 9+ should target REJECT carries without Meraki schema lift). Frozen-file grant NOT used this session.

---
# 2026-05-23 - item 151 4-slice parallel housekeeping drain (cc_conditional wave 8 SHIPPED + BACKLOG stale-sweep wave 13 CLEAN + cost/latency CLEAN wave 16 + living docs sync post-wave-8) SHIPPED (2 commits + 1 merge `656c4f5` `d2711ba`, pushed; ENGINE 1.44.0 -> 1.45.0; non-frozen; DS :8893 restarted serves 1.45.0; RC :8888 unchanged - DS engine + docs only)

Operator "continue what is left as open items in parallel commit + push & /done for /clear, use as many agents as needed" -> 17th consecutive run using orchestrator-merge template (items 134-150 streak extended). 4 worktree agents dispatched concurrent.

**Slice A SHIPPED `656c4f5` feat(ds) cc_conditional wave 8 (36/32 -> 39/35; +3 entries / +3 net-new champs closing prior-wave REJECT carries):** Via setdefault builder + `_p()` helper. NEW: **Morgana R Soul Shackles** (channel_completion 0.5 stun 1.5/1.75/2.0s across 3 ranks - per items 146 + 147 REJECT carries "belongs in cc_conditional parallel to Karma W"); **Seraphine E Beat Drop** (target_debuffed 0.5 stun 1.5s all 5 ranks - per items 138 + 146 + 147 "target-state-conditional: stun fires only when target debuffed by slow/airborne/immobilize"); **Evelynn W Allure** (target_debuffed 0.5 charm 1.5-2.5s across 5 ranks - per items 138 + 146 "detonation-on-Eve-attack conditional charm"). All 3 had been EXPLICITLY flagged in prior wave REJECT notes as belonging in cc_conditional, NOT new pitches. Uses ONLY existing 12 condition tags (COND_CHANNEL_COMPLETION + COND_TARGET_DEBUFFED). +25 tests NEW `test_cc_conditional_wave8.py`. ENGINE 1.44.0 -> 1.45.0 + 32 stale ENGINE pin syncs across DS test files. The Meraki parse-strip STILL BINDS for OTHER candidates (Renekton W / Aatrox post-R / Volibear R / Briar W frenzy / multi-form same-spell-slot Karma+Hwei+Neeko); wave 8 closes ONLY candidates whose duration values + mechanic descriptions are verifiable WITHOUT the extractor schema lift.

**Slice B CLEAN no-commit (wave 13 stale-sweep saturation):** Agent grep-verified every open BACKLOG.md + ROADMAP.md entry against live source. BACKLOG L13 cc_conditional ecosystem subsection ALREADY current. BACKLOG L14/L15 SHIPPED. L16-L106 legitimately operator-gated. ROADMAP L223 + L82/L83/L111/L129/L130/L133/L140 all legitimately operator/live-gated. **Sweep cycle decay:** wave 1=2/2=3/3=3/4=1/5=1/6=1/7=2/8=1/9=1/10=1/11=1/12=1/**13=0**. Saturation at item 150 post-housekeeping baseline.

**Slice C 16th consecutive cost/latency CLEAN no-commit (read-only investigative agent):** 7 levers surveyed. Prompt-cache 8 cache_control sites + Route TTL 14 routes + Polling cadences sane + Model tier haiku-4-5 + Scheduled tasks 14 RC-* + Bundle size 27=27 parity ALL CLEAN. **MINOR PROPOSAL (operator-gated):** `/api/minimap-crop` at **0.417 hits/sec** (1786 hits over 71min) above item 150 baseline ward-heat 0.149/sec. UI-local poller (250ms fast / 2000ms slow gated on MINIMAP_MODES + document.hidden short-circuit). STILL below 1/sec threshold (0.417 < 1.0) but now top non-suppressed path; 1-line tuple addition to `_SUPPRESS_LOG_PATHS` in `_handler.py:74-83` would save ~1500 log lines/hr.

**Slice D `d2711ba` (committed directly to main post-Slice-A) docs sync to post-item-151 state (ENGINE 1.45.0 + cc_conditional 39/35 + DS 4016):** Initial Slice D returned CLEAN no-commit confirming item 150 docs durable; Slice A merge required follow-up flip. 6 surgical edits across 4 files: DAEMON_SLAYER.md L5+L32 / README.md L46 / BRIEF.md L20+L26 / ARCHITECTURE.md L161. Skipped per [[feedback_no_history_rewrite]]: BRIEF.md L33 (2,822 s174-s181 anchor) + L57 (2,703 resume-pitch). Live source-of-truth: ENGINE=1.45.0 entries=39 champs=35 tags=12 DS tests 4016.

**Merge order:** Slice A merged into main FIRST `656c4f5` (worktree branch `worktree-agent-a522d5e7b46c1f89e`, ort strategy, 0 conflicts, 36 files changed); Slice D follow-up docs sync committed directly to main SECOND `d2711ba`. 0 merge conflicts.

**Verified:** DS suite 4016 passed / 1 skipped / 1 xfailed / 1669 subtests (+25 over s150 3991 baseline). py_compile + ruff + ASCII clean. DS :8893 restarted via taskkill /F /PID 8212 + schtasks /Run /TN RC-DaemonSlayer; /health returns engine_version=1.45.0 patch=16.10.1 champions=172 items=705. RC :8888 unchanged. 1 worktree (Slice A) auto-removed post-merge + branch deleted.

**Don't-redo:** cc_conditional registry now 39 entries / 35 champions; the Meraki parse-strip is STILL a STANDING constraint for OTHER candidates - the 3 wave 8 entries were specifically the ones verifiable WITHOUT schema lift. The "16 consecutive saturation" verdict in item 150 was correct ONLY for schema-lift-blocked candidates. Future cc_conditional wave 9 attempts should similarly look for REJECT carries that DO NOT need the extractor schema lift. The orchestrator-merge pattern is now 17 consecutive runs (items 134-151).

**Carries forward:** (a) Item 150 carries (a)-(i) ALL unchanged - Meraki parse-strip is STILL standing constraint for SCHEMA-LIFT-BLOCKED candidates. (b) Meraki extractor schema lift operator-gated. (c) RC-PostmortemAnalyze first scheduled run 2026-05-24 04:15 (in <1 day) - verify LastTaskResult=0 next session. (d) DD Defy heal-on-takedown deferred. (e) Live ARAM/SR smoke pending. (f) All calibrations operator-gated. (g) BACKLOG L14 (a) kills -> takedowns flip operator-gated. (h) UI/UX live-game audit ritual owed. (i) Frozen-file grant NOT used. (j) Slice C MINOR PROPOSAL `/api/minimap-crop` to `_SUPPRESS_LOG_PATHS` operator-gated. (k) Wave 9+ should target REJECT carries that DO NOT need Meraki schema lift.

