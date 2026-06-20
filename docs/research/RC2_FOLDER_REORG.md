# RC2 P7.4 - Repo Folder Reorg (verified census + execution)

Stage 7.4 of the RC 2.0 hygiene phase. Pairs with 7.2 (stale-file census) and
7.3 (dead-code removal). Goal per operator directive: "project-folder cleanup."

ASCII only. No em-dashes or smart quotes.

## Method

Three disjoint read-only census agents swept (a) the 10 loose root `.py`
modules, (b) the 18 loose root non-python files, (c) all top-level directories.
Every load-bearing claim was then re-verified independently against ground truth
(grep file:line, `.gitignore`, the frozen list, `tools/build_portable.py`,
`git log`) before any move - the Verification Discipline rule, since census
agents have mislabeled coupled files before (and did here: one agent called
`start_claude.ps1` a dead artifact; it is a live session launcher - see below).

## FINDING: the repo structure is already canonical

Like 7.2 (0 REMOVE) and 7.3 (only 8 of ~96 archive-candidates were truly
movable), 7.4 confirms RC is tightly coupled. After verification, the
safe-to-move set is a single matched pair of spent audit artifacts. Every other
candidate touches a live reference, a frozen file, or the `.gitignore`
secret-file safety net. This settles the "should we reorg the tree" question:
no, beyond the one archive below.

## EXECUTED (this stage)

| Action | Files | Why safe |
|---|---|---|
| `git mv` to `docs/_archive/2026-06-17-repo-audit/` | `repo-audit.md`, `repo-audit-prompt.md` | Matched one-shot audit prompt+output (2026-06-17, audit already implemented item 490). Dated artifact pair -> canonical `_archive` home (precedent: `2026-05-16-doc-sync/`). History preserved (rename). Only live ref = one ROADMAP line, updated to the new path. Internal sibling cross-ref resolves by basename (both moved to the same dir). LEDGER/history_notes refs left as-is (append-only, reference path-at-time). |

Root file count 35 -> 33. Tracked-under-ignored-`_archive` confirmed via
`git ls-files` post-move.

## VERIFIED KEEP-AT-ROOT (with evidence) - do NOT re-litigate

| Candidate | Verdict | Blocking evidence |
|---|---|---|
| Root `.py` advisor cluster: `composition_advisor.py`, `item_advisor.py`, `performance_tracker.py` | KEEP | Eager top-level imports from FROZEN boot files: `app/__init__.py:59/65/68`, `app/_game_lifecycle.py:44/47`. Moving = editing frozen boot path on a live system for cosmetic gain. |
| `champion_profiles.py`, `role_profiles.py` | KEEP | Part of the same coherent root advisor cluster; a half-move (split siblings across root + a package) is uglier than leaving the cluster intact. Callers exist (`composition_advisor.py:14`, `coach_integration/_coach.py:241`, `coach_integration/_profiles.py:5`). |
| `main.py`, `app.py`, `overlay.py`, `web_dashboard.py`, `moon_vision_server.py` | KEEP | `main.py` FROZEN + launched by 5 `.bat` + RC-Supervisor.xml by bare name. `app.py` = ARCH-001 backwards-compat shim. `overlay.py` imported bare by frozen `main.py:189`. `web_dashboard.py` eager-imported by `main.py:165`. `moon_vision_server.py` launched by `dashboard/server.py` subprocess by filename. |
| `docs io RC peer/` (space in dir name) | KEEP | Rename would touch FROZEN `CLAUDE.md`, 5 core bridge docstrings, and - critically - 10 `.gitignore` globs (`docs io RC peer/*SECRET*`, `*KEY*`, `*TOKEN*`, `*HANDSHAKE*`, ...) that keep untracked sensitive bridge files out of git. Renaming un-ignores them (commit-leak hazard). Core refs are all docstrings (verified non-runtime), so no functional break - but the gitignore + frozen + secret-leak risk outweighs cosmetic value. Defer to an operator-gated pass. |
| `start_claude.ps1` | KEEP (LIVE, agent was wrong) | Live Legion session launcher: preflights RC-DaemonSlayer / RC-Phase3-Supervisor / RC-BridgeWatcher, probes :8893 + :8890, then launches `claude --name "Legion"` (history_notes.md:11931). Not an artifact. |
| `bootstrap_riot_commander_dev.cmd/.ps1` | KEEP | Self-contained fresh-machine provisioning pair (.cmd calls .ps1 via `%~dp0`); allowlisted in `tests/test_bare_py_ban.py:53`; referenced in audit docs. Dormant but coupled; low value to move. |
| `.bat` launcher set (`start/install/kill/restart/restart_clean/start_debug`) | KEEP | Portable-bundle `_ROOT_BAT_FILES` in `tools/build_portable.py:82`; documented ops procedures (CLAUDE.md hard-fallback). |
| `pytest.ini`, `ruff.toml`, `mypy.ini`, `requirements.txt`, `requirements.lock`, `riot-commander.spec`, `.gitignore`, `.gitattributes` | KEEP | Tooling auto-discovery / PyInstaller / pip / CI conventions are root-anchored; moving breaks discovery. |
| `GEMINI.md` | KEEP | Root context file for the Gemini CLI (analogue of `CLAUDE.md`), loaded by `tools/gemini_ask.ps1`. |
| Dirs `lib/` `modes/` `modules/` `scripts/` `coaches/` `coach_integration/` | KEEP | Distinct purposes; `modes.shared_vision` imported by 6 files, `lib.*` by 17, `coaches.*`/`coach_integration.*` by ~80/~50. Heavy import footprint; reorg = mass import churn for no clarity gain. `modules/cache_engine.py` 0-ref is a dead-code question (7.3 scope), not a placement one. |

## Tier

Tier-0 (doc-only: 2 `.md` moves + 1 census doc + 1 ROADMAP line). No `.py`
touched, no schema/engine/Share, no restart. Full-suite green is verified
separately in stage 7.5.
