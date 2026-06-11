# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 (2026-06-11 prunes) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-11 - DEEP-AUDIT cycle 3: P1b tracked-snapshot retention (gemini-ruled) [item 397]

- Gemini ruled current+prev retention for tracked patch snapshots; pin-check found data/daemon_slayer/16.9.1+16.10.1 are DS-suite golden fixtures (~7k tests would break) -> deviation proposed, gemini CONFIRMED ("Tests trump cache cleanup"). Fixture dirs exempt; P2 item: consolidate DS pins onto one frozen fixture patch.
- git rm data/meta_build/ddragon/16.8.1+16.10.1 (cache archives, zero exec refs); fetch_all in lib/ddragon/fetch.py now auto-prunes beyond current+prev (reuses junction-safe prune_stale_versions; fail-soft). +2 tests.
- _scratch: 25 unreferenced >14d files deleted (doc-grep gated).
- NEXT: P1c = python-embed consumer eval + log-proliferation root-cause + CLAUDE.md budget trim; then P2 CODE AUDIT.

---

# 2026-06-11 - DEEP-AUDIT cycle 2: P1a mirror retention + dynamic ddragon patch pins [item 396]

Loop controller stalled post-cycle-1 (operator nudged "continue"); reoriented inline per charter.

- web/data/ddragon held 5 patch dirs (~1.7 GB): 16.12.1 current, 16.11.1, 16.10.1 (561 MB, LOAD-BEARING via active_match.js map pin), 16.8.1 + 16.9.1 (junction alias -> 16.8.1).
- JS fix: every versioned /data/ddragon/<patch>/ literal made dynamic off ITEMS.version - active_match.js _AM_MAP_IMG -> _AM_MAP_FILE + _amMapImg(), main.js :1154 spell img + :2003 _RP_DDRAGON_BASE, pgr_loadout.js _RUNE_LOCAL_BASE -> _runeLocalBase(); items_index.js pre-hydration seeds 16.10.1 -> 16.12.1. NEW drift guard tests/test_ddragon_path_version_drift.py (PATH literals banned; bare version fallbacks allowed - unreachable since ITEMS.version always truthy).
- tools/ddragon_mirror_refresh.py: NEW prune_stale_versions (retain = current + 1 prev, --retain/--no-prune, junction-safe os.rmdir vs rmtree, only semver dirs under web mirror; meta_build git archives out of scope) wired post-clean-run; docstring "never auto-deletes" updated. 6 tests tests/test_ddragon_mirror_prune.py incl the junction case (live mirror really had one - rmtree refused it mid-prune).
- Executed: 16.8.1/16.9.1/16.10.1 deleted, 16.11.1+16.12.1 kept. Logs: 18 gamepc-ui jpgs + 99 logs >30d deleted. Tree delta vs P0: -8621 files / -581 MB (ops/audit/P1_INVENTORY.md; P0 baseline file restored untouched).
- Live verify (chrome-devtools on :8888): map11/12/30 200 on 16.12.1, pruned path 404s into the onerror chain, active_match.js module imports, zero unexpected 4xx resources.
- Gate round A REFUSED correctly: item-392 pin test_arena_base_is_static_asset_with_crop_fallback still split on the _AM_MAP_IMG literal -> updated to _AM_MAP_FILE + builder, same intent (arena static + crop fallback).
- P1 remaining (next cycles): tracked old-patch data decision (daemon_slayer 16.9/16.10/16.11 scenarios.json + laning 16.11.1 LFS + meta_build archives - gemini consult), _scratch/_archive triage, python-embed consumer eval, log-proliferation root-cause (1691 files/7d), CLAUDE.md budget trim.

---

# 2026-06-11 - DEEP-AUDIT cycle 1: P0 BASELINE re-derived + verified [item 395]

Charter cycle (docs/DEEP_AUDIT_CHARTER.md). Gemini's prior "P0 done" synopsis was unstamped + wrong (42209 files / 7451 tests claimed; live = 30398 files / 15167 tests) -> ruled STALE, re-derived everything from live probes.

- Baseline shipped to ops/audit/: P0_INVENTORY.md (30398 files / 4350.5 MB; tracked 2896 / 409.3 MB), p0_pytest_baseline.txt, p0_dashboard_reference.jpeg, P0_WORKMAP.md (P1-P8 seeds, cited).
- Model: claude-fable-5[1m] probe ACCEPTED headless -> set in .claude/settings.json (untracked).
- truth_gate LIVE CATCH: default `py -m pytest` hit the pytest-less pythoncore-3.14-64 interpreter -> suite zeroed -> blanket REFUSE. Fixed (canonical Programs/Python314 pin + sys.executable fallback, RED->GREEN regression test, 19/19). Gate re-run PROCEED 15168p/0f exit 0 + CI success.
- INTERPRETER DUALITY is now a P2 seed: sweep every bare-`py` suite invocation (hooks, skills, docs, scheduled tasks); decide fleet pin (py.ini vs absolute).
- RC-VisionServer schtask exits 1 but vision serves in-process fine -> vestigial task, P2 reconcile seed.
- Desktop synopsis rewritten ASCII/BOM-free, handoff log now sha-stamped (was BOM'd + unstamped).
- NEXT CYCLE: P1 STRUCTURE per synopsis (relocations, _scratch/.bak scrap triage, web/ PNG mirror + logs retention + python-embed consumer eval, CLAUDE.md context-budget trim).

---
