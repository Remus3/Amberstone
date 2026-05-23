# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---
# 2026-05-23 - item 158 UI scale v2.1 page #2 User Builds + rune-page builder + spell chooser SHIPPED (2 commits `a82d8f3` `5452e9e`, pushed origin/main `dffea08..5452e9e`; non-engine; non-frozen; no DS restart; RC pid drifted 7356 -> 14464 mid-session via supervisor auto-relaunch picking up coaches/sr_user_builds.py edit - reload_ok=True)

Operator-driven continuation of item 157's 16-page UI scale v2.1 audit order. Page #2 (User Builds) shipped end-to-end + mid-round augmentation: form pane gained a tabbed 5-tree rune-page builder + 11-icon summoner-spell chooser.

**Commit `a82d8f3` (page #2 base, 4 files / +292 / -48):**
- `web/css/panels/header.css` `.ub-*` classes migrated to v2.1 tokens (--fs-xs/sm/md, --space-1..5, --panel-padding, --panel-radius, --panel-radius-sm, --hit-min). 30+ surgical replacements; per-class deltas tabulated in spec.
- `web/js/main.js::_userBuildsFetchAndRender` consults `body.dataset.uiMock`; loads `/data/ui_mock/user_builds.json` when live is empty + mock is on. Renders `(MOCK)` suffix on label + count + hint.
- `web/data/ui_mock/user_builds.json` NEW 5-build Tristana fixture (populated + role-variant + overflow + minimal edge cases).
- `web/js/main.js` boot restorePrefs adds `?ui_mock=1` URL-search override so headless captures hit mock state without touching interactive Chrome localStorage.
- `docs/UI_SCALE_SPEC_V2.md` per-component-class table for User Builds + mock fixture doc + audit ritual additions.
- Asset hash `e9dad0bf6b -> 87ddde541c`. 7/7 audit ritual checks GREEN via 2 headless Game-PC captures.

**Commit `5452e9e` (rune-builder + spell-chooser, 6 files / +629 / -29):**
- `web/index.html` form-pane: Keystone / Primary tree / Secondary tree inputs marked `readonly` with `(driven by builder)` em hint. Summoner-spell numeric inputs become hidden + driven by chooser. NEW `.ub-sp-chooser` + `.ub-rp-builder` blocks.
- `web/js/main.js` +355 LOC: `_UB_SPELLS` 11-spell catalog, `_RP_DDRAGON_BASE` constant, `_RP` + `_SP` state objects. Spell chooser: 2 slot buttons + 11-cell grid; click slot D/F to activate, click spell to assign, auto-flips active slot. Rune builder: lazy fetch `/api/dictionary/runes`, render 5 tabs (Domination/Inspiration/Precision/Resolve/Sorcery), PRIMARY pane shows keystone row + 3 minor rows (1 pick per row), SECONDARY pane shows pill row of 4 other trees + 3 minor rows (up to 2 picks total). `.ub-rp-summary` one-line preview of current picks. `_ubRpSyncTextFields` keeps readonly Keystone/Primary/Secondary text inputs aligned with builder state. `?ub_form=mock` URL flag auto-opens form with first mock build pre-loaded.
- `web/js/main.js::_ubReadForm` extended to write `runes.minor_primary[]` + `runes.minor_secondary[]` on save.
- `coaches/sr_user_builds.py::_normalize_record` extended additively to persist + sanitize minor_primary + minor_secondary (list[str], default empty). `format_for_display` unchanged - downstream chooser surface untouched. 22/22 phase8_smoke/test_sr_user_builds PASS post-edit; python smoke (minor runes round-trip through add->list) PASS. ruff PASS.
- `web/css/panels/header.css` +178 LOC: `.ub-sp-*` + `.ub-rp-*` classes, all token-driven, --hit-min on all interactive cells, --panel-radius-sm on icons.
- `web/data/ui_mock/user_builds.json` first build extended with minor_primary/secondary lists.
- `docs/UI_SCALE_SPEC_V2.md` "User Builds form-pane augmentation" section: component-class table + DDragon image base + schema extension + round-trip notes.
- Asset hash `87ddde541c -> fc4ff80c8b`.

**Verified:**
- RC dashboard https://127.0.0.1:8888/api/state HTTP 200; mode_key=client throughout.
- `/api/ui-version` shows `fc4ff80c8b` post-commit (ADR-008 auto-reload).
- RC health: pid drifted 7356 -> 14464 mid-session (RC-Supervisor auto-relaunch picked up the coaches/sr_user_builds.py edit). alive=True reload_ok=True post-relaunch.
- Backend persistence: Python smoke test asserts minor_primary/secondary round-trip through `add()` -> `list_for()` cleanly. format_for_display unchanged.
- Phase 8 smoke 75/75 PASS post-edit. ruff clean.
- Headless captures: empty state + populated mock list both render correctly at v2.1 sizing. Form-pane visual capture (showing builder tabs + spell grid) NOT captured this session - headless Chrome session isolation from non-interactive PowerShell hung repeatedly. Form HTML/CSS/JS is mechanical extension of working code; visual verification owed at operator's next interactive Chrome session.

**Don't-redo:**
- `?ub_form=mock` is the canonical dev URL flag for auto-opening the form with the first mock build pre-loaded; requires `?ui_mock=1` to be set. Don't add another flag for the same purpose.
- Rune-builder schema is `runes.minor_primary[]` + `runes.minor_secondary[]` (additive; empty lists when absent). Don't rename or restructure; downstream `format_for_display` ignores them today (champ-select chooser surface unchanged).
- `_RP` + `_SP` are module-level state singletons (one form open at a time). Don't refactor into per-instance state - the form pane is single-instance + single-mode.
- DDragon image base in JS is HARDCODED to `/data/ddragon/16.10.1/img/` (matches what `routes_dictionary.py` serves from `data/meta/ddragon_runes.json`). Both update in lockstep on the operator-triggered patch refresh; don't add a `/api/ddragon/current` indirection just to dynamically resolve.
- Rune-page minor-rune row enforcement is INTENTIONALLY soft: primary side restricts to 1 pick per row (single-select toggle), secondary side allows up to 2 picks total with no per-row check. Game rules enforce stricter constraints client-side at the Riot client; RC's user-builds store is operator-curated additive, NOT pushed to LCU.
- Headless Chrome screenshot of the form-pane via `mcp__gamepc__run_powershell` is FRAGILE: virtual-time-budget + setTimeout(_userBuildsOpenForm, 100) race + chrome lifecycle in non-interactive session hung 3 attempts. Form-pane visual verification owed at operator's next interactive session. Pattern for future: drive via the existing Chrome on Game-PC monitor 1 if SendKeys-from-service-session can be made to land (item 158 attempts failed at AppActivate / SetForegroundWindow due to session 0 vs interactive session isolation).

**Carries forward:**
(a) Item 157 carries (a)-(l) ALL unchanged EXCEPT (k)-relaxed: User Builds (page #2) is NO LONGER pending - SHIPPED this session.
(b) 14 remaining pages in the UI scale v2.1 audit order: Replay (#3) -> History (#4) -> Session (#5) -> Home (#6) -> Pre-Game Lobby (#7) -> Champ Select SR/ARAM/Arena (#8/9/10) -> Active Match SR/ARAM/Arena (#11/12/13) -> Post Game Review SR/ARAM/Arena (#14/15/16). Per-page mock fixture owed at `web/data/ui_mock/<page>.json`.
(c) Form-pane visual verification for the new rune builder + spell chooser owed at operator's next interactive Chrome session (headless capture race hung 3 attempts; backend + ruff + 75/75 smoke PASS).
(d) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session.
(e) DD Defy heal-on-takedown STILL deferred. Live ARAM/SR smoke STILL pending. Calibrations operator-gated. cc_conditional wave 12+ 2 deferred candidates. 542 residual U+2500 box-drawing chars operator-gated. Legion 1-PC consolidation operator-gated.

---
# 2026-05-23 - item 157 UI scale v2.1 - per-element ~44% bump (25% + 15%) + zoom feature retired - Settings worked example SHIPPED (1 commit `09eddeb`, pushed origin/main `1d5ef99..09eddeb`; non-engine; non-frozen; no DS restart; no RC restart - asset-hash auto-reload per ADR-008)

Operator triggered global UI density refactor across 16 pages (Settings -> User Builds -> Replay -> History -> Session -> Home -> Pre-Game Lobby -> Champ Select SR/ARAM/Arena -> Active Match SR/ARAM/Arena -> Post Game Review SR/ARAM/Arena). One framed AskUserQuestion 4-question scope fork pinned per [[feedback_scope_decision_cadence]]: (Q1) Spec doc + tokens.css draft + Settings rendered preview reviewed together (Recommended); (Q2) Density modes - single Comfortable/Broadcast target now, multi-mode primitive deferred (Recommended); (Q3) Page order - operator's verbatim list (Recommended); (Q4) Dummy data - dev-only Settings toggle default OFF.

**Shipped (7 files / +457 / -96):**
- `docs/UI_SCALE_SPEC_V2.md` NEW - typography matrix (v1 / v2 25% / v2.1 +15% columns) + 8-px spacing matrix + panel rules + interaction rules + dummy-data architecture + UI audit ritual v2 checklist + per-page execution order + per-component-class Settings targets + cleanup deltas.
- `web/css/tokens.css` extended additively. Font scale v1 11/13/15/20/27 -> v2.1 16/18/22/29/37 + NEW tiers --fs-stat 26 + --fs-display 46. Panel tokens: --panel-padding 20, --panel-padding-comp 14, --panel-padding-loose 28, --panel-gap 14, --panel-gap-tight 10, --panel-radius 18, --panel-radius-sm 10. Interact tokens: --hit-min 42, --hover-pad 8, --tooltip-offset 12, --tooltip-delay 250ms, --focus-ring. NEW --space-7 40 + --space-8 48. v1 --space-1..6 unchanged (audit-wave-1 contract preserved).
- `web/css/panels/header.css` settings-card / settings-card-head / settings-row / settings-row inputs token-driven; .view-section-head h2 -> --fs-lg 29px (affects all view-sections via single selector). Checkbox 14x14 -> 24x24, card padding 12-14 -> 20, card border-radius 8 -> 18, inter-card gap 14 -> 32.
- `web/css/panels/base.css` `body { zoom: 1.0 }` declaration REMOVED + comment block updated to document zoom feature retired.
- `web/index.html` Zen mode `<label class="settings-row">` row REMOVED + zoom slider row REMOVED + Dev UI mock data toggle ADDED in DISPLAY card.
- `web/js/panels/dev.js` zoom slider wiring removed; cb("set-ui-mock", "rc-ui-mock", v => body.dataset.uiMock = v ? "1" : "") added.
- `web/js/main.js` boot zoom-restore removed; Shift+R + prefs-chip-click no longer touch rc-zoom; tooltip place() function no longer divides by getComputedStyle(body).zoom; prefs-chip footer pill is ui-mock:on (was zoom).

**Verified:**
- RC dashboard https://127.0.0.1:8888/api/state HTTP 200, mode_key=client throughout (never restarted - ADR-008 unified asset-hash auto-reloaded CSS+JS edits, asset hash 8d3c7bcb7d -> 2579468dff between captures).
- Game-PC monitor 1 captured 2x (pre-bump baseline + post-+15% delta). Settings page reads at comfortable viewing distance; zoom slider gone, mock toggle wired + functional (UI-MOCK:ON pill visible when checked); checkboxes 24x24 read fingertip-scale; section heads 29px (was 17px) clearly prominent.
- RC health pid=7356 alive=True reload_ok=True throughout.
- No tests touched (pure UI refactor, no logic change).

**Don't-redo:**
- Zoom feature is FULLY RETIRED. Do NOT reintroduce `body { zoom: N }`, the `#set-zoom` slider, or the `localStorage.rc-zoom` key. The 4 lazy mechanisms (transform: scale, body zoom, browser zoom, root font-size hack) are documented in docs/UI_SCALE_SPEC_V2.md as OFF-LIMITS for this refactor.
- The +15% second-pass values (16/18/22/26/29/37/46) ARE the v2.1 baseline. If operator asks for "another 15%" treat that as v2.2 explicitly.
- The tooltip `place()` function in `main.js:6113` is now in plain viewport CSS pixels - the prior zoom-divisor was specific to the old 1.33 body-zoom era and is dead-weight removed.
- The `champ_select.js:268-274` popup workaround appends to `<html>` to bypass body-zoom; the workaround is HARMLESS now that body-zoom is gone but its reasoning is stale. Audit-ritual step 7 covers this when Champ Select pages (#8/9/10) hit the order.
- Settings is the WORKED EXAMPLE not the locked ship-state. Operator approved (issued /done) so v2.1 token values + Settings layout are LOCKED for subsequent pages.
- 27 panel CSS files + 27 panel JS files + 583 hardcoded font-size declarations across 29 CSS files - the page-by-page audit pass sweeps its OWN panels only. Do NOT do a bulk font-size sweep.

**Carries forward:**
(a) Item 156 carries ALL unchanged - this session was NON-engine, NON-frozen, NON-test (zoom feature retirement was the only "code-deletion" lever; everything else was additive token + selector tuning).
(b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session.
(c) DD Defy heal-on-takedown STILL deferred.
(d) Live ARAM/SR smoke STILL pending.
(e) Calibrations STILL operator-gated.
(f) UI/UX live-game audit owed.
(g) DS conditional arc operator-CLOSED (s232).
(h) Legion 1-PC consolidation STILL operator-gated.
(i) cc_conditional wave 12+ has 2 deferred candidates (Jayce E + Singed E) needing further schema lifts.
(j) 542 residual U+2500 box-drawing chars carry forward as operator-gated separate sweep.
(k) **NEW carry from item 157**: 15 remaining pages in the UI scale v2.1 audit order (User Builds -> Replay -> History -> Session -> Home -> Pre-Game Lobby -> Champ Select SR/ARAM/Arena -> Active Match SR/ARAM/Arena -> Post Game Review SR/ARAM/Arena). Each page consumes v2.1 tokens during its own audit pass per the UI audit ritual v2 checklist in `docs/UI_SCALE_SPEC_V2.md`. Per-page mock fixtures owed at `web/data/ui_mock/*.json` for the dev UI mock data toggle to render anything; no fixtures shipped this session.
(l) **NEW carry from item 157**: 583 hardcoded font-size declarations across 29 CSS files will be swept incrementally per page-audit pass; no bulk sweep authorized.

---
# 2026-05-23 - item 156 operator-gated decision-owed parallel drain #4: rc_supervisor FROZEN mojibake byte-repair + Variant B em-dash mojibake closure + cc_conditional wave 11 Sion R + Gnar W form 1 + housekeeping triple SHIPPED (4 commits + 3 merges + docs sync follow-up, pushed origin/main; ENGINE 1.47.0 -> 1.48.0; DS :8893 restarted serves 1.48.0; RC :8888 unchanged)

Operator triggered fourth consecutive "in parallel : start all open items in Operator-gated, decision owed" drain. AskUserQuestion 4-question scope fork pinned: (Q1) rc_supervisor.py 1368 mojibake byte-repair Grant + repair; (Q2) cc_conditional wave 11 Full pass (Recommended); (Q3) DD Defy Defer (Recommended); (Q4) Add housekeeping CLEAN slices explicitly. 3 worktree agents dispatched concurrent (orchestrator pattern items 134-155 extended to 21 consecutive runs).

**Slice A `8ab3822` (merge `3fe431b`) chore(frozen) rc_supervisor.py mojibake byte-repair + Variant B em-dash mojibake closure (8 files / +246 / -136):**
- Critical discovery: item 155's signature `c3 a2 e2 80 9d e2 82 ac` is actually U+2500 box-drawing mojibake (bytes e2 94 80 = UTF-8(U+2500) -> CP-1252 mis-decode -> re-encode UTF-8 `c3 a2 e2 80 9d e2 82 ac`). The canonical em-dash mojibake (Variant B) signature is `c3 a2 e2 82 ac e2 80 9d` (bytes e2 80 94 = UTF-8(U+2014) -> CP-1252 mis-decode -> re-encode UTF-8 `c3 a2 e2 82 ac e2 80 9d`).
- `tools/repair_mojibake.py` extended to detect both variants + add `--allow-frozen <comma-csv>` flag (mirrors item 155 strip_smart_quotes pattern) + empty `_HARD_SKIP_FROZEN: frozenset[str] = frozenset()` defense-in-depth constant.
- Per-file pre/post: ops/rc_supervisor.py Variant A 1368 -> 0 + Variant B 12 -> 0 (operator-granted frozen-file write); tft/tft_coach_engine.py Variant B 22 -> 0; ops/rc_self_monitor.py Variant B 5 -> 0; ops/rc_state_validator.py Variant B 3 -> 0.
- Smart-quote follow-through: 1410 U+2014 em-dashes normalized to ASCII ` - `.
- `tools/strip_smart_quotes.py` emptied `_HARD_SKIP_FROZEN` (was `{ops/rc_supervisor.py}`; post-repair the corruption-risk rationale no longer applies).
- Drift guards `tests/test_mojibake_hygiene.py` + `tests/test_smart_quote_hygiene.py` extended to cover both variants + remove rc_supervisor from frozen exclusion list.

**Slice B `5ec3d65` (merge `9c5cba1`) feat(ds) cc_conditional wave 11 - Sion R + Gnar W form 1 (35 files / +788 / -33):**
- Re-audit of REJECT carries from item 153 against item 154's `effects_descriptions` + sidecar registry produced 2 new entries / 2 net-new champs.
- **Sion R Unstoppable Onslaught** PRIMARY: stun 1.0s representative midpoint, COND_CHANNEL_COMPLETION 0.5; effects_descriptions evidence "stunned after a brief delay for 0.25 : 1.75 (based on channel time) seconds". Coexists with Sion Q unconditional 1.25-2.25s stun (different spell slot).
- **Gnar W form_index=1 Wallop** SIDECAR Mega-rage-form-gated: stun 1.25s flat, COND_FRENZY_STATE 0.4; THIRD consumer of COND_FRENZY_STATE after Renekton W wave 9 + Karma W form 1 wave 10. Coexists with Gnar R unconditional 0.75s terrain-collision stun (different spell slot).
- REJECT-confirmed (effects_descriptions evidence): Aatrox R minion-only fear / Volibear R turret-disable + slow only / Briar W self-buff frenzy no CC payload / Sion E minion-only stun / Lillia W damage only / Ekko R self-stasis + damage only / Smolder R damage + heal only / Karma E shield + MS both forms / Vladimir R damage amp + delayed burst + heal / Akshan Q+R damage + buffs only / Tristana E damage stacking only / Kayle E+R no CC / Nidalee R/Q/W/E transform + no champion CC.
- Deferred wave 12+: Jayce E (cast_time value missing from schema) + Singed E Mega-Adhesive overlap root (2-spell-overlap target-debuffed encoding not supported).
- ENGINE 1.47.0 -> 1.48.0 + 32 stale ENGINE pin syncs across DS test files.
- NEW `agents/daemon_slayer/tests/test_cc_conditional_wave11.py` 46 tests across 11 classes.
- REGISTRY_TOTAL_CHAMPIONS=38 -> 40 / REGISTRY_TOTAL_ENTRIES=44 -> 46 (43 primary + 3 sidecar). Default include_conditional=False math BYTE-IDENTICAL to 1.47.0.

**Slice C `bdb0043` + `60c8d37` (merge `c1a88b5`) housekeeping triple (6 files / +8 / -8):**
- Sub-task 1 stale-sweep wave 14: 3 flips (BACKLOG L13 cc_conditional ecosystem stale counts; ROADMAP L22 stale dashboard.js:5055 ref removed; ROADMAP L80 gamepc_lcu_agent.py:777 -> :1091).
- Sub-task 2 cost/latency CLEAN wave 17 no-commit: 17th consecutive CLEAN sweep since item 134. All 7 levers + cost-trace 11 wires intact.
- Sub-task 3 living docs sync: DAEMON_SLAYER.md/ARCHITECTURE.md/README.md/BRIEF.md test count 4130 -> 4132 (pre-Slice-B baseline; post-Slice-B sync via this item's follow-up commit).
- Sweep cycle decay: 1=2 / 2=3 / 3=3 / 4-12=1 / 13=0 / **14=3** (rebound from items 149-155 churn).

**Merge order:** A `3fe431b` -> B `9c5cba1` -> C `c1a88b5`. 0 merge conflicts (disjoint file sets). One mid-flight recovery: initial Slice A merge accidentally landed on Slice B's worktree branch due to persisted shell cwd; recovered via `git reset --hard 5ec3d65` on Slice B worktree + re-merging from C:\Riot Commander cwd.

**Verified:**
- DS suite `agents/daemon_slayer/tests/` = **4176 passed / 1 skipped / 1 xfailed / 1731 subtests in 67.88s** (+46 over 4130 baseline = exactly the wave 11 test file).
- RC suite `tests/` (excl phase8_smoke) = **3257 passed / 67 subtests in 56.17s** (unchanged from item 155 baseline).
- `tests/phase8_smoke/` = 75/75 PASS post-DS-restart.
- `py -m ruff check .` ALL CHECKS PASSED.
- DS :8893 killed pid 10516 + `schtasks /Run /TN RC-DaemonSlayer` (per [[reference_ds_server_not_supervisor_watched]]) -> serves engine_version=1.48.0 / patch=16.10.1 / 172 champs / 705 items.
- RC :8888 responsive throughout (mode_key=client; never restarted - DS engine + tools + tests + docs only; supervisor edits take effect on next supervisor restart which operator can choose).

**Don't-redo:**
- Mojibake Variant identification is now definitive: Variant A `c3 a2 e2 80 9d e2 82 ac` = U+2500 box-drawing mojibake (NOT em-dash as items 154+155 ledger claimed); Variant B `c3 a2 e2 82 ac e2 80 9d` = canonical em-dash mojibake. Both repaired across non-frozen + rc_supervisor.py.
- 542 residual U+2500 box-drawing chars (rc_supervisor 58 + rc_self_monitor 484) are INTENTIONAL docstring tree-drawing chars - operator-gated separate sweep needed if desired.
- cc_conditional wave 11 methodology (re-audit prior REJECT carries against LATEST schema-lift + sidecar registry) is durable for future waves; the 14 REJECT-confirmed verdicts with effects_descriptions evidence are CONFIRMED NEGATIVES.
- Shell-cwd persistence between Bash calls is a HAZARD: use `git -C "<path>"` for explicit-cwd or verify pwd before destructive ops.
- Orchestrator-merge pattern now 21 consecutive runs (items 134-156).

**Carries forward:** (a) Item 155 carries ALL unchanged EXCEPT (a)-relaxed: rc_supervisor.py mojibake byte-repair NO LONGER operator-gated (DONE this session). (b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15. (c) DD Defy heal-on-takedown STILL deferred. (d) Live ARAM/SR smoke STILL pending. (e) Calibrations STILL operator-gated. (f) UI/UX live-game audit owed. (g) DS conditional arc operator-CLOSED (s232). (h) Legion 1-PC consolidation STILL operator-gated. (i) cc_conditional wave 12+ has 2 deferred candidates (Jayce E + Singed E) needing further schema lifts. (j) 542 residual U+2500 box-drawing chars carry forward as operator-gated separate sweep. (k) Operator-gated decision-owed lane EXHAUSTED for actionable headless items at item 156 ship time. Frozen-file grant USED for ops/rc_supervisor.py; NOT used for any other frozen file.

---
# 2026-05-23 - item 155 operator-gated decision-owed parallel drain #3: mojibake byte-repair + frozen smart-quote sweep + L31 round 3 lcu/+coach_integration/+agents/ SHIPPED (3 commits + 3 merges, pushed origin/main `22a56bd`; non-engine; no DS restart; RC :8888 unchanged - non-frozen + frozen-grant scoped)

Operator triggered third consecutive "in parallel : start all open items in Operator-gated, decision owed" drain. AskUserQuestion 4-question scope fork pinned: (Q1) Mojibake UTF-8 byte-repair on 4 flagged files Repair (Recommended); (Q2) Frozen smart-quote sweep Grant + sweep 3 trivial only - rc_supervisor NOT granted (Recommended); (Q3) L31 round 3 All three surfaces lcu/+coach_integration/+agents/ (Recommended); (Q4) cc_conditional wave 11 Skip / defer (Recommended - no clear candidate). 3 worktree agents dispatched concurrent (orchestrator pattern items 134-154 extended to 20 consecutive runs).

**Slice A `4122d41` (merge `bd2d861`) tools mojibake UTF-8 byte-repair on 3 non-frozen files + drift guard (5 files / +430 / -21):**
- NEW `tools/repair_mojibake.py` reads bytes, detects 8-byte signature `c3 a2 e2 80 9d e2 82 ac` (latin-1-misdecoded UTF-8 em-dash), replaces with proper 3-byte UTF-8 em-dash `e2 80 94`. Atomic `tmp.write_bytes + os.replace`. Frozen-file hard-skip allowlist mirrors `strip_em_dashes.py` + `strip_smart_quotes.py`. `--dry-run` default + `--apply` flag.
- Per-file pre/post mojibake counts: `ops/rc_self_monitor.py` 534 -> 0; `ops/rc_state_validator.py` 256 -> 0; `tft/tft_coach_engine.py` 75 -> 0. (Carry-forward stated 539/259/97 = PRE-item-154 totals incl. clean U+201D; item 154 smart-quote sweep cleaned 5/3/22 clean-context bytes leaving 534/256/75 mojibake. Math reconciles.)
- `ops/rc_supervisor.py` 1368 hits UNTOUCHED (FROZEN-NO-GRANT this session; defense-in-depth hard-skip even if tool's argv accidentally targets it).
- Byte deltas (8B sig -> 3B em -> 3B ` - ` follow-through = -5B/sig): rc_self_monitor 52003 -> 49333 (-2670); rc_state_validator 10542 -> 9262 (-1280); tft_coach_engine 36356 -> 35981 (-375).
- Smart-quote sweep follow-through ran after byte-repair: 865 U+2014 -> ` - ` across the 3 files.
- NEW `tests/test_mojibake_hygiene.py` drift guard (3/3 PASS) walks repo with same exclusions + asserts no `c3 a2 e2 80 9d e2 82 ac` signature in tracked byte streams.

**Slice B `6024ccc` (merge `fd91117`) chore(frozen) smart-quote sweep on 3 trivial frozen-file hits via item 155 operator grant (4 files / +51 / -5):**
- Added `--allow-frozen <csv-paths>` argv flag to `tools/strip_smart_quotes.py` + `_HARD_SKIP_FROZEN={ops/rc_supervisor.py}` defense-in-depth constant. Rewrite-branch gates on `allow_override = (rel_posix in _allow_frozen) and not is_hard_skip`. Report prints overridden + hard-skipped-from-override lists.
- 3 grant-targeted single-codepoint hits swept: `ops/rc_dev_runtime.py` U+2026 1 -> 0 (DailyRotatingFileHandler backup-suffix docstring); `core/moon_proxy.py` U+2026 1 -> 0 (Moon vision dedupe debug); `core/log_setup.py` U+2026 1 -> 0 (Popen verify-window AUDIT docstring).
- `ops/rc_supervisor.py` UNTOUCHED confirmed via git status + file size 79885 unchanged + hard-skip listed in report. NOT in modified set.
- Drift guard `tests/test_smart_quote_hygiene.py` 3/3 PASS post-sweep. Combined `test_smart_quote_hygiene + test_frozen_files_sync` 6/6 PASS.

**Slice C `3fd9f4a` (merge `22a56bd`) chore(types) L31 round 3 - type annotations on lcu/+coach_integration/+agents/ public APIs (5 files / +23 / -23):**
- 19 surgical sites total: lcu 9 + coach_integration 9 + agents 1 (+2 stub return types) + 1 import.
- Files: `lcu/lcu_postgame_collector.py` + `coach_integration/_coach.py` + `coach_integration/_sr_prompt.py` + `coach_integration/_profiles.py` + `agents/agent7_context/warm_session.py`.
- 0 ruff violations / 0 reverts / 0 frozen-file touches (`lcu/lcu_client.py` hard-skipped per CLAUDE.md).
- Surface saturation: `lcu/lcu_pregame.py` + `lcu/lcu_rune_writer.py` + `coach_integration/{enemy_stats,archetype_dispatch}.py` + `agents/{_supervisor_*, supervisor, agent6_auditor/*, agent7_context/{input_parser,ui_feedback}}.py` ALREADY FULLY ANNOTATED (use `__future__ annotations` or pre-typed). Branch name `worktree-slice-c-l31-r3` (agent self-named; non-standard but functional).

**Merge order:** A `bd2d861` -> B `fd91117` -> C `22a56bd`. All 3 ort merges 0 conflicts (disjoint file sets across all 3 slices).

**Verified:**
- RC suite `tests/` (excluding phase8_smoke) = **3257 passed / 67 subtests passed in 56.17s** (+3 over 3254 baseline = exactly new test_mojibake_hygiene.py tests).
- `tests/phase8_smoke/` = 75/75 PASS (no engine change; DS :8893 untouched serves 1.47.0 from item 154 restart).
- `py -m ruff check .` ALL CHECKS PASSED.
- `py -m py_compile` clean on all 13 touched files (5 mojibake + 4 smart-quote + 5 L31, 1 overlap on tft_coach_engine.py).
- RC :8888 responsive throughout (rc.pid=7356 alive=True mode=client; never restarted - non-frozen byte-edits + frozen-grant scoped to 3 trivial files + no coach prompt changes).
- DS :8893 untouched (non-engine session); /health still serves engine_version=1.47.0 from item 154.
- Pushed main as `22a56bd` to origin/main.

**Don't-redo:** The mojibake signature `c3 a2 e2 80 9d e2 82 ac` (8 bytes = U+00E2 U+20AC U+009D U+20AC followed by U+20AC; result of latin-1 misinterpretation of UTF-8 em-dash `e2 80 94` re-encoded UTF-8) is the canonical fingerprint - the `tools/repair_mojibake.py` is the durable tool for any future drift. The drift guard `tests/test_mojibake_hygiene.py` LOCKS the invariant going forward; any future commit that introduces this byte sequence fails CI. The `--allow-frozen` flag on `tools/strip_smart_quotes.py` is the durable mechanism for operator-granted frozen-file sweeps; `_HARD_SKIP_FROZEN={ops/rc_supervisor.py}` is the defense-in-depth constant that prevents accidental sweep of rc_supervisor even if a future grant targets it - bump that constant only with explicit operator authorization. The L31 extension is now CLOSED for lcu/+coach_integration/+agents/ public APIs; the remaining surfaces (`ops/` + `tools/` + `app/` + `tft/` ALREADY DONE in item 154) have nothing significant to annotate. The orchestrator-merge pattern (3-4 worktree agents on disjoint slices + tests gate + RC unchanged + docs sync follow-up commit) is now 20 consecutive runs (items 134-155).

**Carries forward:** (a) Item 154 carries ALL unchanged EXCEPT (a)-relaxed: mojibake byte-repair on 3 non-frozen files NO LONGER operator-gated (DONE this session); 3 trivial frozen-file smart-quote sweeps NO LONGER operator-gated (DONE); L31 extension to lcu/+coach_integration/+agents/ NO LONGER operator-gated (DONE). (b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session. (c) DD Defy heal-on-takedown STILL deferred. (d) Live ARAM/SR smoke STILL pending. (e) Calibrations STILL operator-gated. (f) UI/UX live-game audit ritual owed once operator plays a real game. (g) DS conditional arc operator-CLOSED (s232). (h) Legion 1-PC consolidation (s169 option B) STILL operator-gated. (i) **STILL CARRY**: `ops/rc_supervisor.py` 1368 mojibake U+201D byte-repair pass (FROZEN - needs explicit grant for that specific file beyond this session's grant). (j) cc_conditional wave 11+ should consume sidecar registry shape directly - skipped this session per no-clear-candidate verdict. (k) Operator-gated decision-owed lane EXHAUSTED for actionable headless items at item 155 ship time (remaining carries are all live-gated, hardware-migration, or frozen-rc_supervisor-only). Frozen-file grant USED this session for 3 trivial files; NOT used for rc_supervisor.

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

