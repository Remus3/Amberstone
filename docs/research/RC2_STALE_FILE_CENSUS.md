# RC 2.0 - Phase 7.2 Stale-File Census

DELIVERABLE for RC2 stage 7.2 ("Stale-file census: .md/scripts unused >1 week
of iterations"). READ-ONLY inventory. No file is deleted, moved, or edited here;
removal/quarantine is stage 7.3. ASCII only.

Probed 2026-06-20. "Stale" = tracked AND no git commit since 2026-06-13 (>1 week).

---

## METHODOLOGY + DENOMINATORS

Census target classes: `.md .py .ps1 .bat .sh .ahk`, excluding the immutable
`docs/_archive/**` quarantine.

```
git ls-files '*.md' '*.py' '*.ps1' '*.bat' '*.sh' '*.ahk' | grep -v '^docs/_archive/'   -> 2179 tracked
git log --since=2026-06-13 --name-only ... (touched in last week)                        -> 1181 touched
comm -23 (stale = tracked - touched)                                                     ->  998 stale
```

Stale set bucketed by top dir:
`tests 300 | agents 246 | Share 172 | tools 105 | docs 36 | core 35 | ops 27 | _archive 14 | lib 13 | scripts 7 | docs io RC peer 6 | dashboard 6 | coaches 6 | vision_server 2 | (root + misc) ~23`

Two populations:

- **LIVE-CODE (out of removal scope, ~744 files):** `tests/`, `agents/**/*.py`,
  `Share/`, `core/`, `lib/`, `dashboard/`, `coaches/`, `vision_server/`,
  `modes/ modules/ tft/`. "Not committed in a week" here means stable, not stale -
  a passing test or a settled engine module is KEEP. Per-file dead-code detection
  is explicitly **deferred to stage 7.3** (dead-code / unused-asset removal).
- **REMOVABLE-CLASS (examined per-file, 254 unique files):** docs `.md`, the dated
  `agents/agent*/reports|proposals/*.md` artifacts, `tools/`, `ops/`, `scripts/`,
  and repo-root scripts. Three read-only census agents classified these on disjoint
  slices (A=docs/dated-artifacts 129, B=tools 105, C=ops/scripts/root 49; A/B and
  A/C overlap on 29 shared rows -> 254 unique).

Per-file: last-commit date, reference/orphan status (repo grep), class, and a
recommendation of KEEP / ARCHIVE-CANDIDATE / REMOVE-CANDIDATE with evidence.

---

## HEADLINE VERDICT

- **0 REMOVE-CANDIDATE** across all 254 examined files. Nothing is safe to `git rm`.
- Every stale file is either **live-referenced (KEEP)** or a **recoverable
  dated-artifact / one-shot / superseded-plan / skill-duplicate (ARCHIVE-CANDIDATE)**.
- This matches the standing repo rule: dated artifacts go to an `_archive/`
  quarantine, they are **never deleted** (memory `reference_archive_dir`,
  feedback `feedback_no_history_rewrite`).
- ~96 ARCHIVE-CANDIDATEs (union, dedup pending 7.3 verification); the rest KEEP.

So 7.3's removable surface is **quarantine moves + a handful of true-orphan
deletions to verify**, not a deletion sweep. The cross-reference breakers below
are the real work.

---

## 7.3 ACTION WORKLIST (archive-candidates, grouped)

### A. Dated agent-framework artifacts (bulk; ~50 files) -> quarantine under `agents/_archive/` (new) or `docs/_archive/agents/`
- `agents/agent2_backend/reports/2026*.md` (9 apply-reports, all 2026-04/05 dated)
- `agents/agent5_ui/reports/20260422-142602-*.md` (1)
- `agents/agent6_auditor/proposals/2026*/**/*.md` (~12 dated proposals + .result/.decision)
- `agents/agent6_auditor/reports/2026*.md` (~29 dated audit + weekly-cron + test-round-22)
- KEEP (NOT artifacts): every `agents/agent*/charter.md`, `agents/agent6_auditor/safeguards/startup_checks.md`,
  `agents/daemon_slayer/CC_CONDITIONAL_NOTES.md` - live Phase-3 framework, loaded by
  `agents/_supervisor_common.py` + `agents/agent7_context/warm_session.py`.

### B. Superseded docs plans/scaffolds/probes (~8) -> `docs/_archive/` (UPDATE back-refs same slice)
- `docs/API_SURFACE_AUDIT.md`, `docs/AUTO_ACTION_LANES_GATE_PROBE.md`,
  `docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md`, `docs/COMPETITOR_LIFT_2026-06-08.md`
- `docs/DS_ABILITY_RATIO_RESOURCE_PLAN.md`, `docs/DS_GAP_COMPLETION_PLAN.md`,
  `docs/DS_SOURCE_ADOPTION_PLAN.md`, `docs/DS_V2_PLAN.md` (all 4 shipped+CLOSED, cited in BACKLOG/ROADMAP_HISTORY)

### C. One-shot tools scripts already applied (~25) -> `docs/_archive/` or `tools/_archive/`
- Hotfixes (7): `tools/hotfix_*_item{167,263,269,273,275,276,277}.py`
- Migrations (3): `tools/migrate_abilities_units_2026_05_30.py`,
  `tools/migrate_carry_summoners_flash_barrier.py`, `tools/caveman_default.py`
- Loadout one-shots (6): `tools/champion_loadout_{backfill_item208_carry,collapse_to_paths,handcurate,handcurate_merge,sweep_item_s8}.py` (+ `invariants.py`, `validate_meta.py` VERIFY: re-runnable validators, no live caller)
- Probes/toggles (3): `tools/probe_101qq_hero_rank_double.py`, `tools/bridge_dispatch_enable_lanes.py`, `tools/lessons_send_dryrun.py` (superseded by `lessons_send.py --dry-run`)
- Misc tools-docs: `tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md`, `tools/BRIDGE_WATCHER_INSTALL_PS1_LANES_DIFF.md`, `tools/DISTRIBUTION_LAYOUT.md`, `tools/LAUNCH_STRATEGY.md`, `tools/PYTHON_BUNDLING_STRATEGY.md` (distribution deferred)
- VERIFY-then-archive: `tools/claude_send.ahk` (gemini-headless uses its own bridge), `tools/legion_on.ps1`/`legion_off.ps1`, `tools/install_headless_launcher_shortcut.ps1`, `tools/daemon_slayer_build_orders_generate.py`

### D. Skill-command duplicates of `.claude/commands/*.md` (5) -> archive the `tools/` copy
- `tools/{done,headless-upgrade,ship-batch,sync-all-md,test-first-autopilot}.md`
- CONFIRMED: same-named live skills exist in `.claude/commands/`. The `tools/` copies are stale mirrors.
- NOT dups / KEEP: `tools/done-peer.md`, `tools/done-gamepc.md`, `tools/process-bridge-tasks-peer.md`, `tools/wrap-gamepc.md` are allowlist-pinned (see caveat 1).

### E. ops/ dated audit scaffold (~6) -> archive, but TIMING-GATED
- `ops/audit/{P0_INVENTORY,P0_WORKMAP,P1_INVENTORY}.md`, `ops/audit/p0_inventory.py`,
  `ops/loop/CDRAGON_FLIP_FINDINGS.md`, `ops/phase3_file_audit_proposals.py` (orphan sibling; the live `RC-Phase3-PeriodicAudit` task runs `-m ops.phase3_file_audit`, which does NOT import proposals)
- HOLD the `ops/audit/P0_*/P1_*` set until Phase 7 closes (see caveat 4).

---

## CRITICAL 7.3 CAVEATS (cross-reference breakers - do NOT blind-move)

1. **`dashboard/routes_static.py` `_AGENT_ALLOWED` (line 130) is a live runtime
   allowlist** for the dashboard bridge/redeploy endpoint. VERIFIED it pins, among
   others: `BRIDGE_WATCHER_PLAN.md`, `PEER_ROADMAP_SUGGESTIONS.md`, `done-peer.md`,
   `done-gamepc.md`, `process-bridge-tasks-peer.md`, `gamepc_boot.ps1`,
   `gamepc_phase_watcher_install.ps1`, `start_gamepc_claude.ps1`, all `bridge_*` tools,
   `GAMEPC_CLAUDE.md`. **Archiving any allowlisted path breaks the endpoint** -
   exclude them, or update `_AGENT_ALLOWED` in the SAME 7.3 slice. These are KEEP.
2. **DS `*_PLAN.md` + `COMPETITOR_LIFT` are cited in `BACKLOG.md` / `ROADMAP_HISTORY` /
   `docs/LEDGER.md`.** Archiving must rewrite those pointers to the `_archive/` path
   in the same slice or the cross-refs dangle.
3. **No-history-rewrite rule:** the dated `agents/agent6_auditor/**` + `agent2_backend/reports/**`
   artifacts are immutable history -> `git mv` to quarantine, never `git rm`.
4. **`ops/audit/P0_*/P1_INVENTORY.md` are THIS audit's live baseline** (cited by
   `docs/LEDGER.md`; the RC2 deep-audit diffs against them). KEEP until Phase 7
   closes, THEN flip to archive. Premature archive blinds the in-flight audit.
5. **`overlay.py` is LIVE, not deadcode.** VERIFIED `main.py:189 import overlay as _ov`
   (frozen entrypoint). Likewise `app.py` (re-exports `OverlayApp`), `champion_profiles.py`
   (imported by `composition_advisor.py`), `moon_vision_server.py` (vision-server shim) - all KEEP.

---

## KEEP-OUT-OF-SCOPE (live-code population, ~744 files)

`tests/ (300) | agents/**/*.py (~196 after pulling the ~50 dated .md) | Share/ (172)
| core/ (35) | lib/ (13) | dashboard/ (6) | coaches/ (6) | vision_server/ (2) |
modes/ modules/ tft/ (3)`. Stable engine/test/mirror code. Untouched-in-a-week =
settled, not stale. Per-file dead-code detection is stage 7.3's job, not 7.2's;
the slice-C probe already confirmed the root-level entrypoints (overlay/app/
champion_profiles/moon_vision_server) are import-live, so no obvious deadcode at
the root. `Share/` is the force-synced DS mirror - never hand-edit (KEEP whole).

---

## DISAGREEMENT + VERIFY LOG

Slice A and B overlapped on 22 `tools/*.md`; resolved with ground-truth grep:
- `tools/{done,headless-upgrade,ship-batch,sync-all-md,test-first-autopilot}.md`:
  A=KEEP(frozen-command), B=ARCHIVE(dup). **Resolved ARCHIVE** - confirmed dups of
  `.claude/commands/*.md`, NOT in `_AGENT_ALLOWED`.
- `tools/{ATX_ROADMAP_SUGGESTIONS,BRIDGE_WATCHER_PLAN}.md`: A=ARCHIVE, B=KEEP(allowlist).
  **Resolved KEEP** - confirmed allowlist-pinned.
- `ops/audit/P0_*/P1_*`: A=KEEP(active baseline), C=ARCHIVE(dated). **Resolved KEEP-til-phase-close** (caveat 4).

Open VERIFY flags for 7.3 (re-confirm orphan before archiving):
`tools/champion_loadout_invariants.py`, `tools/champion_loadout_validate_meta.py`
(re-runnable validators, no live caller found), `tools/claude_send.ahk`,
`tools/legion_on.ps1`/`legion_off.ps1`, `tools/install_headless_launcher_shortcut.ps1`,
`tools/daemon_slayer_build_orders_generate.py`, `tools/wrap-gamepc.md`.

---

## APPENDIX - full per-slice classification tables

The three census-agent tables are the authoritative per-file record (path |
last_commit | class | refs | rec | reason). They are reproduced in the agent
transcript for this session; per-file rows feed 7.3 directly. Slice totals:

| Slice | scope | files | KEEP | ARCHIVE-CANDIDATE | REMOVE-CANDIDATE |
|-------|-------|------:|-----:|------------------:|----------------:|
| A | docs `.md` + dated agent artifacts | 129 | 79 | 50 | 0 |
| B | `tools/` | 105 | 65 | 40 | 0 |
| C | `ops/` + `scripts/` + root | 49 | 41 | 6 | 0 |
| (overlap dedup) | A&B 22, A&C 7 | -29 | | | |
| **unique** | | **254** | | **~96** | **0** |

NEXT: stage 7.3 (dead-code / unused-asset removal, safety-verified) consumes this
worklist; honor every caveat above (allowlist, back-refs, no-rm, P0/P1 hold).
