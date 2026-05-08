# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s122 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s125 wrap — 2026-05-08 (Phase 1.1 — knowledge architecture)

## What shipped
- **docs/_archive/** created (gitignored); 23 dated artifacts moved there — all `AUDIT_*`, `PHASE_*`, `HANDOFF_*`, `SESSION_HANDOFF_*`, `*_RESEARCH_2026-*`, `BUILD_REFRESH_STRATEGY_*`, `RC_ARCHITECTURE_INFOGRAPH.*`, `OPS_QUICK_REFERENCE.md`, `ARCH-001-decomposition-plan.md`, `ARCHITECTURE_REVIEW.md`, `tft_overhaul_design.md`, `PROJECT_STATE.md`, handoff TXTs.
- **docs/ARCHITECTURE.md** (136 lines) — machine topology + data flows table + module map (orchestration/vision/coaching/dashboard/frontend) + god-module table + 7 key gotchas.
- **docs/OPERATIONS.md** (153 lines) — health check commands + restart workflow + all RC-* scheduled tasks + bridge ops + file location map.
- **docs/BRIDGE.md** (136 lines) — wire format + Legion endpoints table + watcher daemon architecture + lessons sync + per-node config files.
- **BACKLOG.md** (51 lines) — aspirational/future items extracted from ROADMAP.md.
- **ROADMAP.md** trimmed to 64 lines (Now+Next only); past history in `docs/_archive/CHANGELOG.md`.
- **CLAUDE.md** trimmed from ~150 → 139 lines; pointers to living docs; active priorities pruned to open items only.
- Commit **9234d0f** pushed → origin/main (29 files: 537 insertions, 5050 deletions).

## Key decisions
- `_archive/` is already in `.gitignore` — archived files preserved on disk only (not in git). Intentional; keeps repo clean while allowing local reference.
- Bootstrap reading: **492 lines total** (CLAUDE.md 139 + ARCHITECTURE.md 136 + OPERATIONS.md 153 + ROADMAP.md 64). Phase 1 exit criteria met (was 2000+).

## Do NOT redo
- Don't re-archive docs/ — 23 files already in `_archive/`, gitignored, intentional.
- `docs/ui_audit/` left in place (already isolated). `docs io RC peer/` left in place.
- `docs/_archive/CHANGELOG.md` exists on disk but not in git (expected, gitignored).

## What's next
1. **Phase 1.2** — `tools/gen_archmap.py`: walk package tree, read `# arch: <role> | <tier> | <frozen?>` headers, regenerate module-map section of ARCHITECTURE.md + frozen-file list in CLAUDE.md between sentinel comments. Wire to pre-commit hook.
2. **Phase 1.3** — `docs/adr/` + 5 historical ADRs (tkinter removal, DS-before-Haiku, in-process vision, bridge watcher daemon, MagicDNS migration).
3. TFT 17.3 due ~2026-05-12 — may take priority over Phase 1.2 if patch drops first.
4. Recommend `/done` → `/clear` → fresh session for Phase 1.2+1.3.

---

# s124 wrap — 2026-05-08 (RC future-proofing plan — Opus 4.7 1M deep analysis)

## What shipped
- **`C:\Users\Administrator\Desktop\RC_FUTUREPROOFING_PLAN.md`** — robust phased plan to make RC easier to document/build. 7 phases ordered by leverage: (1) knowledge architecture (doc split + auto-archmap + ADRs), (2) god-module decomp (champion_profiles → game_reader → coach_integration → moon_vision_server), (3) frontend ESM modularity, (4) pydantic schemas (HTTP + bridge envelope + coaching payload), (5) CI + smoke harness, (6) bridge consolidation [needs frozen-file approval], (7) ergonomics.
- Plan includes §0 session-budget cheat sheet (`/done` vs `/wrap` vs `/clear` vs continue decision matrix) so future sessions know when to checkpoint vs continue.
- Plan is Desktop-resident on purpose: checkboxable, append findings, move closed phases to §5 DONE archive.

## What's next
- **Switch to Sonnet 4.6 high effort.** Pick up Phase 1.1 (living-vs-dated docs split) in next session.
- Bootstrap pattern for next session: `/clear` → read plan on Desktop → say "Pick up Phase 1.1".
- Phase 1 alone is highest leverage (zero runtime code change, makes every future session start from ground truth).

## No code changes this session
- No commits, no push. Plan artifact lives outside the repo on purpose (operator-facing checklist, not project deliverable).

---

# s123 wrap — 2026-05-08 (rc_facts bridge probe + DS exit 1 investigation)

## What shipped
- **rc_facts.py bridge probe rewrite** (commit 04a305b): replaced stale `bridge_log.jsonl` age-based anomaly ("auto-flow loop may be dead") with `/api/health/all` peer probe. Now shows `gamepc bridge daemon: watcher=alive queue=0 age=Xs` and `peer bridge daemon: ...` — fires real anomaly only if `watcher_alive=false`, peer stale, or queue > 10.
- **DS server health line** added to Legion section in rc_facts: `DS server :8893: ok patch=16.9.1 alive=True`.
- **RC-DaemonSlayer false anomaly suppressed**: result=1 is silenced in the task list when `daemon_slayer.alive=True` from health/all (the server IS running; the task's stale exit code was a red herring).

## Findings (no code change needed)
- **Bridge auto-flow `/loop` is obsolete**: `RC-BridgeDaemon` + `RC-BridgeWatcher-GamePC` on Game-PC handle it as scheduled tasks. Confirmed both Running. Memory `reference_bridge_autoflow.md` was already accurate.
- **RC-DaemonSlayer exit 1 root cause**: DS server alive and healthy (PID 19268 pythonw.exe, `/health` returns OK). The exit 1 on 5/5 was a one-off manual `schtasks /Run` that failed — task runs as SYSTEM which silently can't write to `logs/` (`_log_startup` swallows the OSError). BootTrigger run at 5/1 boot started the server successfully and it's been running ever since.

## Do NOT redo
- Don't re-investigate the bridge auto-flow loop — it's daemon-managed, not `/loop`-managed. The old `/loop` is dead and gone.
- Don't re-investigate DS exit 1 as a live failure — it's resolved (false alarm). If DS ever goes down, rc_facts will flag it via the `DS server :8893:` line, not the task result.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **TFT 17.3** — due ~2026-05-12 (4 days). Same process as 17.2.
4. **Bridge Watcher acceptance-criteria** — need 50+ auto-action samples; currently 0.
5. **Auto-ops verb expansion** — after 95% success rate.
6. **RC-DaemonSlayer task context** — runs as SYSTEM; `_log_startup` writes silently fail. Low-risk (server alive), but consider changing to LogonTrigger + Administrator context if traceability matters after next boot.

---

