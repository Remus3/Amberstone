# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s123 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s127 wrap — 2026-05-08 (Phase 2.1 — champion_profiles.py split COMPLETE)

## What shipped
- **`champion_profiles.py`** shrunk from 902 → 29 LOC. Now a thin JSON loader.
- **`data/champion_profiles/*.json`** — 168 champion files, each a flat dict with `dmg/role/mana/sustain/mechanic/aram` fields. All checked in.
- **`scripts/extract_champion_profiles.py`** — one-shot migration helper left in tree as migration doc.
- **`docs/ARCHITECTURE.md`** — god-module table updated; archmap regenerated via pre-commit.
- **`ROADMAP.md`** — Phase 2.1 ✅ Done.
- Commit **8fa11f4** pushed → origin/main (172 files changed: 1399 insertions, 906 deletions).

## Key decisions
- Thin loader stays at **root `champion_profiles.py`** (not `core/`). `ops/rc_dev_runtime.py` (frozen) watches `"champion_profiles"` as a module-name string — moving it would require a frozen-file edit. Zero caller changes.
- Import surface preserved exactly: 12 module-level exports (`CHAMPIONS, TANKS, FIGHTERS, MAGES, ASSASSINS, MARKSMEN, SUPPORTS, AD_CHAMPS, AP_CHAMPS, HYBRID_CHAMPS, SUSTAIN_CHAMPS, MANA_CHAMPS`).
- Pre-existing test failure in `tests/snapshot_regressions/test_app_authority.py` is unrelated — confirmed via git stash; 289 other tests all pass.

## Do NOT redo
- Don't re-run the extractor — 168 JSONs already committed. It's idempotent but unnecessary.
- Don't re-backfill `# arch:` header on `champion_profiles.py` — already updated to "thin loader".

## What's next
1. **Phase 5** — CI + smoke harness (cheapest regression insurance; recommended before Phase 2.2+).
2. **TFT 17.3** — due ~2026-05-12 (higher time priority).
3. **Phase 4** — Contracts/schemas (pydantic `api_schema.py` + coaching payload).

---

# s126 wrap — 2026-05-08 (Phase 1.2 + 1.3 — archmap + ADRs — Phase 1 COMPLETE)

## What shipped
- **`tools/gen_archmap.py`** — walks package tree, reads `# arch: <role> | section=<section> | frozen=yes|no` headers from `.py` files, regenerates module-map section of `docs/ARCHITECTURE.md` between `<!-- archmap:start/end -->` sentinels. `--check` mode wired to `.githooks/pre-commit`.
- **`# arch:` headers backfilled** in 33 key Python files (all files in the ARCHITECTURE.md module map). BOM stripped from `game_reader.py` + `coaches/aram_coach.py`. Frozen file changes = comment-only additions at line 1.
- **`docs/adr/`** — 30-line template + 5 historical ADRs: ADR-001 tkinter removal, ADR-002 DS-before-Haiku, ADR-003 in-process vision server, ADR-004 bridge watcher daemon, ADR-005 Tailscale MagicDNS.
- **CLAUDE.md** — ADR pointer added; active priorities updated.
- **ROADMAP.md** — Phase 1 flipped ✅.
- Commits **fc1361b + 2be87a8** merged to main.

## Key decisions
- Frozen-file list in CLAUDE.md stays manually maintained — it includes non-Python files (.ps1, .json, .xml, .md) that can't carry `# arch:` headers.
- Bootstrap reading: **500 lines total** (CLAUDE.md 140 + ARCHITECTURE.md 143 + OPERATIONS.md 153 + ROADMAP.md 64). Phase 1 exit criteria fully met.

## Do NOT redo
- Don't re-backfill `# arch:` headers — already in all 33 key files.
- `tools/_backfill_arch_headers.py` was deleted (one-shot helper, served its purpose).
- `gen_archmap.py` is idempotent — second run says "archmap up to date."

## What's next
1. **Phase 2.1** — `champion_profiles.py` (902 LOC) split: audit dict literals, build extractor script, emit `data/champion_profiles/*.json`, replace with ≤80 LOC thin loader. Lowest-risk decomp.
2. **TFT 17.3** — due ~2026-05-12. May take priority if patch drops.

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

---

# s124 wrap — 2026-05-08 (RC future-proofing plan — Opus 4.7 1M deep analysis)

## What shipped
- **`C:\Users\Administrator\Desktop\RC_FUTUREPROOFING_PLAN.md`** — robust phased plan to make RC easier to document/build. 7 phases ordered by leverage.
- Plan includes §0 session-budget cheat sheet (`/done` vs `/wrap` vs `/clear` vs continue decision matrix).

## No code changes this session
- No commits, no push. Plan artifact lives outside the repo on purpose.

---

