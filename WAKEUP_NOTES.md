# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s123 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s128 wrap — 2026-05-08 (Phase 5 — CI gate + smoke harness COMPLETE)

## What shipped
- **`tests/snapshot_regressions/test_app_authority.py`** fixed: 52 → 0 failures. Root cause: `app` was refactored to use `StateAuthority` + `GameLifecycleManager`; headless stub didn't initialize them. Fix: `_HeadlessApp` subclass with `_current_envelope` property proxying `app.state.envelope`. Test count: 289 → 343 passing.
- **Arena/Brawl golden fixtures** added: `ARENA_STATE` + `BRAWL_STATE` in `state_dicts.py`, two golden JSON files, 10 new snapshot tests.
- **`tests/phase2_smoke/test_coach_state_parsing.py`** (new, 31 tests): smoke harness for all 5 coach modes — SR (`_build_user_prompt`), ARAM/Arena/Brawl (`_parse_state`), TFT (`_coach_board_to_placement`). No API calls.
- **CI** (`.github/workflows/ci.yml`): added `ruff` install + `ruff check .` step; added `phase8_smoke`; removed `--ignore=test_app_authority.py`. 380 tests pass in CI shape.
- **`ruff.toml`**: 101 → 0 violations. Added ignores for RC patterns (B904/B007/B027/E731/UP037); frozen-file per-file ignores (app/ F821, bridge tools UP/E/B); auto-fixed 51 mechanical issues.
- **Bug fix**: `tft/tft_live_analysis.py:274` — `_j.loads` → `_pj.loads` (would NameError if manual_level path hit).
- **Commit `d21f533`** pushed → origin/main.

## Key decisions
- `_HeadlessApp` subclass pattern (not monkey-patching OverlayApp) keeps production code clean.
- Coach smoke tests test the state-parsing layer (raw Riot API format), not the processed game_reader output. Phase 4.3 schema validation deferred.
- ruff frozen-file per-file-ignores prevent accidental `--fix` to `bridge_pull_tasks.py` etc.
- Branch protection on GitHub (`require CI "check" green`) left as manual UI action — chip created for next session.

## Do NOT redo
- Don't re-fix test_app_authority.py — all 54 tests now pass.
- Don't re-run ruff --fix — 0 violations, nothing to fix.
- Don't re-add arena/brawl golden files — already checked in.

## What's next
1. **TFT 17.3** — due ~2026-05-12 (highest time priority). Same process as 17.2.
2. **Phase 4** — Contracts/schemas: pydantic `api_schema.py` + coaching payload. Next in futureproofing order.
3. **Branch protection** — enable in GitHub UI: Settings → Branches → require status check "check".

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


