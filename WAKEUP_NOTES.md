# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-01 - DS gap-completion plan Phase A refactors (A1+A2) + Phase B cleanup + Share re-sync (item 241; commits 205a9b2 A1 / 5d24191 A2 / 8eb901a B / 3775c75 Share; no ENGINE bump - structural+docs only, 1.75.0 unchanged; no DS/RC restart)

Worked `docs/DS_GAP_COMPLETION_PLAN.md` (the item-240 NEXT). Landed the 2 lower-risk refactors + all the cleanup + the Share re-sync. DEFERRED A3 (cc_conditional->JSON; de-risked, approach below) + Phase C/D (features + live flag-flips) to the LIVE session, where the plan already frames them. DS suite 5663 green throughout.

Shipped:
- A1 (205a9b2): `agents/daemon_slayer/__init__.py` 4627 -> 19 lines. The 1322-line module docstring + 3302-line comment changelog relocated VERBATIM (alnum-token verifier: 0/38725 dropped) to `agents/daemon_slayer/CHANGELOG.md` (lean __init__ = docstring + ENGINE_VERSION + pointer). `ds_share_sync._build_expected` excludes the engine CHANGELOG.md from the mirror (Share has its own authored CHANGELOG.md + a stubbed __init__). Repo guard `tests/test_ds_changelog_relocation_item241.py` (8). `--check` stayed clean (A1 alone = zero Share drift, no gist push).
- A2 (5d24191): `ability_dps.py` 2792 -> 1270. The 3 audit seams -> `_per_spell_cc.py` (814 = CC-duration registry + 2 helpers) / `_registries.py` (403 = max_priority + form_index + block_index loaders) / `_rank_mage.py` (404 = /rank-mage ranker + 2 result dataclasses). All 27+ moved symbols RE-EXPORTED from ability_dps so every consumer import path + the cache-reset / cc-monkeypatch test seams keep working. `_rank_mage` breaks the import cycle via a FUNCTION-LEVEL `from .ability_dps import compute_ability_dps, _resolve_max_priority, _resolve_form_index_overrides, _resolve_block_index_overrides`. token verifier 0/11259 dropped. 9 CC-registry ASCII-hygiene tests repointed ability_dps.py -> _per_spell_cc.py.
- B (8eb901a): 4 stale docstrings (ability_hps "nothing consumes it yet" -> compute_hps folds compute_ability_hps; fight_report "5 substrate modules" x3 -> 7; cc_pressure "53/44" -> live 108/89 + trust-the-import; ehp "44 of 172" -> 89) + removed dead `cli.py _cmd_not_implemented` (zero callers). cc_conditional head-docstring wave counts DEFERRED to A3 (touched there anyway).
- Share (3775c75): `tools/ds_share_sync.py` re-sync 239 -> 242 files (+3 A2 modules); `--check` clean; gist auto-pushed via .git/hooks/post-commit (logs/gist_share_sync.log "gist synced ... 250 files").

Dont-redo: A1 CHANGELOG.md is a VERBATIM move (0 token loss) - never re-reflow; future ENGINE bumps PREPEND to its changelog section. A2 re-export is load-safe (caches reset via co-located fns; the `_PER_SPELL_CC_DURATIONS` monkeypatch targets `cc_pressure`'s own binding, not ability_dps; the forward-marker test checks import-DIRECTION not file-location) and `_rank_mage`'s deferred import IS the cycle-break - do NOT make it module-level. The A1 repo guard lives in `tests/` (RC suite) NOT the DS suite (it imports `tools.ds_share_sync`, which is not in Share/src). The 3 new A2 modules ARE mirrored to Share; the engine CHANGELOG.md is NOT.

A3 DE-RISKED (do this FIRST next session): `data/cc_conditional_calibration.json` is ABSENT + `_PER_ENTRY_PROBABILITY_OVERRIDES == {}`, so `_p(champ, spell, midpoint)` returns the midpoint -> the LIVE registry probabilities EQUAL the source midpoints -> A3 can serialize the 72 primary + 8 forms entries FROM the live registry (`dataclasses.asdict`) byte-identically, and the loader reconstructs via `ConditionalCcEntry(probability=_p(champ, spell, rec_prob), durations_s=tuple(...), ...)` preserving the calibration layer. The hard part = AST-extract the 72+8 `ConditionalCcEntry(...)` literal spans from `_build_per_spell_cc_conditional` (cc_conditional.py:545+) while PRESERVING the interspersed REJECT-rationale comments (keep them in the .py or a parallel notes file). Byte-identical verify = snapshot every entry repr + `compute_cc_pressure(include_conditional=True)` for all 172 champs before/after. No ENGINE bump (structural).

NEXT (LIVE session per the plan): (1) A3 above. (2) Phase C: C1 Sion Q + Hwei Q f2 block-index routing + missing-HP coeff (the `_STAGED_AMP_CANDIDATES` in `_ability_amp_overrides.py` - each form's "Maximum ..." block ALREADY models full charge, so route the block-index, do NOT add a double-counting amp) / C2 AA-empower seam in `compute_dps` (the 5 base="aa" entries already in `_ability_amp_overrides.py`, inert in ability_dps) / C3 author 8 exotic passives default-OFF in `_passive_damage_overrides.py` (needs schema ext for %HP / crit-chance / per-stack / conditional / dot). (3) Phase D live flag-flips. (4) Phase E re-sync. Plus item-240 UI part-3 + the #7/#8 sign-off.

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
