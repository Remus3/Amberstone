# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-31 - Share review-gist + auto-sync + champ-select SR UI redesign (2 audited rounds) + DS-completion plan (commit e7bca41; pushed e5b4fc9..e7bca41; CI green run 26730539253; non-engine; non-frozen; no DS/RC restart - web assets auto-serve)

Operator: (1) put `Share/` on ONE shareable gist, auto-update on any Share/ change; (2) Q/A-decide the item-239 NEXT items into a plan; (3) apply a champ-select UI redesign; then /done. The gist is the lolmath/a peer maintainer handoff link (operator sends it AFTER next session).

Shipped (e7bca41):
- SECRET gist https://gist.github.com/<redacted-gist-id> (public=false, link-shareable no-account): Share.zip (248 files, 2.3MB, __pycache__ excluded, DETERMINISTIC zip) + daemon_slayer_wiki_stats_extract.py + daemon_slayer_wiki_ability_extract.py inline + generated README. `tools/gist_share_sync.py` regenerates+pushes; clone OUT of repo at `C:\Users\Administrator\.rc-share-gist` (its git remote holds the gist id - nothing hardcoded). `.git/hooks/post-commit` (LF, Legion-local) fires the sync ONLY when a commit touches `Share/` (verified gate; Share/ unchanged this session so no spurious push). gist shape decided via Discord context (a peer maintainer wanted the extraction script readable + a tldr; operator wanted the whole package).
- `docs/DS_GAP_COMPLETION_PLAN.md` = NEXT-SESSION plan. Q/A decisions: LIVE session (operator plays to validate); fix the stale docstrings clean; ALL 3 refactors (__init__ changelog reloc + ability_dps 3-way split + cc_conditional->data); leave the `lolmath` data key + README-flag it; Sion Q + Hwei Q f2 block-index amps (defer AurelionSol W); AA-empower seam default-OFF; author all 8 exotic passives default-OFF. Phases A refactors -> B stale-doc fix -> C amp/passive default-OFF -> D live flag-flips -> E Share re-sync.
- `docs/CHAMP_SELECT_UI_SPEC.md` + champ-select SR redesign, 2 audited rounds (0 MUST-FIX each): R1 = ban un-stretch / DS-build horizontal+no-collapse / enemy win% leading + drop YOUR RECORD / allies restyle. R2 (operator marked up 8 fixes) = conf% pill removed / win% leading-LEFT of portrait / names un-truncated / no-double chip+save-push button removed / short enemy roles JG/ADC/SUP / ban cells centered (no CTR, no %) / DS item names 2-line + BO_SLOTS 6->7 / CC CHAIN+CONDITIONAL CC moved to My Pick center + Assessment divider tightened. 188 tests green (panel-DOM tests updated for moved mounts + removed button).

Dont-redo: the gist clone at `.rc-share-gist` MUST persist (sync logs an error + exits if gone); the post-commit hook is Legion-local (`.git/hooks` not committed); the gist auto-updates on the NEXT Share/-touching commit. UI **part-3** (SR build chooser rune nested panel + 3-category LCU push + per-champion persistence) is DEFERRED to next session's LIVE slice (the push needs a real champ-select to verify; operator was mode=client) - spec is final in CHAMP_SELECT_UI_SPEC.md.

Flags (operator sign-off, not blockers): #7 `BO_SLOTS=7` requests a 7th item but the engine returned 6 for the Jinx mock plan (live games fill more); #8 the CC cards sit in the packed My-Pick column so they scroll to reach (operator may prefer tightening other center content).

NEXT: work `docs/DS_GAP_COMPLETION_PLAN.md` in a LIVE session + UI part-3 + the #7/#8 sign-off. Then operator sends the gist link to a peer maintainer.

---

# 2026-05-31 - docs beautify: DAEMON_SLAYER + ARCHITECTURE changelogs reflowed into per-version lines + one-line-per-bump rule (commit 7fa3058; CI green run 26726300182; docs-only; no ENGINE bump; no DS/RC restart; non-frozen)

Operator: the two DS docs had unreadable single physical lines (DAEMON_SLAYER.md line 5 = 24745 chars from ~38 ENGINE-bump appends; ARCHITECTURE.md line 161 = 8364 chars). Docs-only, no engine/test/data.

Shipped (7fa3058): DAEMON_SLAYER.md line-5 megastring reflowed -> short status header + "## Engine substrate & registries" + "## Changelog" (one bullet per ENGINE version, newest-first: V2 substrate 1.64.0-1.74.0 then cc_conditional waves 0-23). VERBATIM reflow via deterministic slicing + content-token verifier: 0 tokens dropped, all 33 ENGINE versions + waves 0-23 preserved (also cleaned the pre-existing malformed bold on the fused wave 6/8 chunk). ARCHITECTURE.md line-161 condensed -> summary sentence + 4 structural bullets (scorers / override registries / cc_conditional ecosystem / CS picker UI) + see-DAEMON_SLAYER-changelog pointer (per-version narrative dropped, allowed). Added the one-line-per-bump rule to the new Changelog header + .claude/commands/done.md step 6b (gitignored = Legion-local).

ALSO closes item 239 (shipped LAST session, /done was not finished): 89cd204 engine + 4bc484e Share + 7fd6d65 docs-sync; ENGINE 1.74.0->1.75.0 = phantom residual (DrMundo E + Twitch R) + opt-in Gap1 _ability_amp_overrides.py + opt-in Gap2 _passive_damage_overrides.py; DS suite 5663; DS :8893 already 1.75.0. CLAUDE.md item 239 + Share/ already synced last session.

Dont-redo: the reflow is VERBATIM (verifier = 0 content loss) - do NOT re-reflow. Future ENGINE bumps PREPEND a new Changelog bullet, never extend a prior version's line (rule now in done.md 6b + the DAEMON_SLAYER Changelog header). Temp slicing scripts tools/_beautify_*.py deleted, never committed. tools/_c3.txt/_done_out.txt/_lessons.txt/_lp.txt/_probe.txt are PRE-EXISTING untracked junk (not this session).

NEXT: nothing owed by the beautify. Item-239 NEXT carries unchanged (all operator-gated; Share/docs/04_GAPS_AND_ROADMAP.md + CLAUDE item 239): live-game flag-flip validation, Gap2 on_hit->AA cadence, 3 staged amps, AA-empower seam, exotic passives, refactor recs.

---

# 2026-05-31 - insights pass 2: built the horizon items the pass-1 entry deferred (commit e151e95; CI green; no ENGINE bump; no DS/RC restart; non-frozen)

Operator ran /insights then "apply ALL of features-to-try + on-the-horizon; fold CLAUDE.md additions in; explain why already-present skills get re-suggested." This closes the pass-1 NEXT (self-healing checkpoint+resume + verifier gate were explicitly NOT built last session).

Shipped (tracked, in e151e95): CLAUDE.md +5 convention sections after ## Verification (Verification Discipline / UI Fixture Ritual / Python Conventions / Data Fixes / Engine-Build Conventions, each grounded in a real item: 238 stale-replay / page-8 audit miss / 216 dataclass-41-break / 211 backfill / 208->213 marksman). NEW tools/slice_orchestrator.py + tests/test_slice_orchestrator.py (16 green) = resumable run manifest (init/add/set/next/resume/summary, atomic, ops/runtime/slice_manifest.json). NEW tools/headless_run.ps1 = crash-retry + manifest-resume wrapper.

Shipped (LOCAL/gitignored .claude/, active now): NEW .claude/agents/verifier.md (read-only ground-truth verifier subagent, no Edit/Write). NEW .claude/commands/root-cause-fix.md skill. headless-upgrade.md +manifest-init pre-flight +verifier-gate-before-merge +per-slice checkpoint +root-cause-fix ref. done.md +ground-truth re-verify bullet.

Why insights re-suggested skills/hooks already present: /insights reads session TRANSCRIPTS not the .claude/ filesystem; it cannot see that done/headless/TDD skills exist or that pytest_guard+edit_lint_check+precommit_gate already run on every edit/commit. The lever to stop re-suggestion = changing observable BEHAVIOR (verifier dispatch, manifest checkpoints, audit-before-commit), now codified. Hooks left AS-IS - did NOT add the literal pytest-per-edit suggestion (would slow the loop; the existing layering is better).

Dont-redo: hooks already satisfy the report (do NOT add redundant pytest-per-edit to settings.json). .claude/* is gitignored (line 65) so verifier+root-cause-fix+skill-edits are Legion-local, never in git history - same as every other skill here. slice_orchestrator manifest path defaults to ops/runtime/slice_manifest.json, overridable via --manifest (tests inject tmp).

NEXT: nothing owed. Next /insights pass should not re-surface these themes if the verifier/manifest/audit behavior shows up in transcripts; insights is a transcript heuristic so no hard guarantee.
