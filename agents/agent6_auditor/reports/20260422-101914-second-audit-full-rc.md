# Agent 6 - Second Audit (Full RC) + Correction Implementation

- **Date:** 2026-04-22
- **Auditor:** Agent 6 (Opus 4.7, in-session)
- **Scope:** Whole Riot Commander codebase (~41.5k lines, 135 files) excluding
  already-audited Phase 3 subtree (`agents/`, `lib/`, `web/`).
- **Follows:** `20260422-095110-first-audit.md` - all 7 proposals from that
  pass now completed ✅.

## What shipped in this pass

### Phase 3 (first-audit follow-ups - implemented + tested)

| id | sev | fix | tests |
|----|-----|-----|-------|
| H3 | high | `supervisor.spawn_ephemeral_llm` now raises `EphemeralStubNotWired`; dispatcher routes to `Scheduler.fail()` instead of silently completing. | `test_supervisor_stub.py` × 2 |
| H2 | high | `Scheduler._append_log` takes a cross-process lock (msvcrt / fcntl) with 5s retry budget. | `test_scheduler_lock.py` - 2×120-writer contention |
| H1 | high | `Evaluator._has_traversal` rejects `..`, `%2e%2e`, mixed `/\` separators. Runs before target/payload checks. `_subdir_ok` tightened to prefix-match. | `test_agent0.py` - 5 traversal variants + substring attack |
| M1 | med  | `test_smb_push` now exercises the backup-on-overwrite branch. | + 1 roundtrip test |
| M2 | med  | `migration_rewind` skips rows with null `tracked_team_id` (verified 0/2846 in current rewind data; fixes latent red-side corruption). | - |
| M4 | med  | `Scheduler.file_task` drops unknown `blocked_by` ids with WARN instead of silently stalling. | `test_agent1.py` - new case |
| M5 | med  | `WSServer.start` passes explicit `max_size=2**20` (1 MiB). | - |
| L1 | low  | `acquire_lock` uses `O_CREAT\|O_EXCL` sentinel; stale-pid reclaim is explicit. | - |
| L2 | low  | `Supervisor.start` preflights both ports with a friendly error message. | `test_quality_pass.py` - bound-port detection |
| L3 | low  | SMB push `label` is sanitised (Windows-unsafe chars → `-`). | 3 cases |
| L4 | low  | Web handler denies dotfiles (`.env`, `.git`, `.htpasswd`) + common secret filenames. | - |

**Test count: 24 → 40 (all green, 9.3s runtime).**

### Full-RC audit (this pass) - criticals implemented

| id | sev | file | fix |
|----|-----|------|-----|
| C1 | critical | `tft/comp_control.py:206` | PowerShell clipboard now takes payload via stdin (`$input \| Set-Clipboard`) instead of string-interpolating into `-Command`. Closes command-injection surface. |
| C2 | critical | `lan_bridge.py:70-98` | PUT endpoint was unauthed + `BASE / self.path.lstrip("/")` path-concat (arbitrary filesystem write via `..`). Now: `_safe_put_path` allowlists writable prefixes (`moon_sync_inbox/`, `data/ocr_debug/`) + extensions (`.json .txt .png .jpg .webp`) + resolves + verifies containment + caps at 64 MiB. Traversal paths return 403. |
| C4 | critical | `performance_tracker.py:218,246` | Violated CLAUDE.md atomic-write rule on 2 hot writers (match-end). Now routes through new `_atomic_write_json` helper. Dashboard polls mid-write are safe. |
| - | - | `coaches/_base_coach.py:372` | **Disputed** - on re-read, the lock acquire/release is on the calling thread; the spawned thread doesn't touch the lock. Subagent misread. Not a bug. |

### Full-RC audit - highs implemented

| file | fix |
|------|-----|
| `moon_vision_server.py:119-128` | Bare `except: pass` in `_parse_json` → specific `json.JSONDecodeError`. |
| `moon_vision_server.py:344-365` | Bare excepts in `handle_ocr` (3×) → tuple `(RuntimeError, OSError, ValueError, AttributeError)`. SystemExit/KeyboardInterrupt now propagate. |
| `modes/shared_vision.py:_capture_screen` | Added failure streak counter - escalates from DEBUG to WARNING after 3 consecutive fetch failures (invisibility to "Game-PC agent died" was a real ops concern). |
| `tft/tft_vision_reader.py:_capture_game` | Replaced local `PIL.ImageGrab` (broken post-2026-04-19: RC has no League window) with the same `/latest-frame` relay used by ARAM/Arena/Brawl. Full frame is fetched then cropped client-side with the existing `_CROP_REGIONS` bboxes. TFT vision is now fixed. |

### Full-RC audit - findings that turned out to be false positives

- `game_reader.py:83, 252` - subagent claimed missing `with` context manager;
  both sites already use `with urllib.request.urlopen(...)`. Disputed.
- `game_reader.py:_enemy_last_seen/_enemy_death_time` - claimed unlocked
  cross-thread access; in practice the dicts live on a GameReader instance
  driven by a single worker thread, with overlay reads going through the
  disk-backed atomic-write JSON files (not shared memory). Not a live race.
- `web_dashboard.py:3745` field param - not exploitable, `crop_png_b64`
  does a dict lookup and returns None for unknowns; handler sends 404.
  Low-priority polish only.
- `moon_vision_server.py:303, 322` `raise` after `_record` - claimed to
  crash the server; verified the HTTP handler at `:485` wraps all
  dispatch in `try: ... except Exception` and returns `{"error": ...}`.
  Not a crash vector.

### Full-RC audit - FROZEN files, proposals filed

Per CLAUDE.md §Hard rules, 5 findings went to the queue as propose-and-
queue instead of direct edit:

| proposal | severity | target |
|----------|----------|--------|
| `P-rc-frozen-lcu-urlopen` | high | `lcu/lcu_client.py:71` - missing `with` on urlopen |
| `P-rc-frozen-moon_proxy-except-breadth` | medium | `core/moon_proxy.py:64` - too-broad `Exception` |
| `P-rc-frozen-app-init-swallow` | medium | `app/__init__.py:115,410,421` - init/shutdown swallowing |
| `P-rc-frozen-overlay-mgr-swallow` | medium | `app/_overlay_manager.py` - 8× `except: pass` in visibility toggles |
| `P-rc-frozen-claude-md-path-typo` | low | `CLAUDE.md` lists `core/rc_dev_runtime.py` but actual location is `ops/rc_dev_runtime.py` |

## Live-system verification

- RC main restarted via `restart_trigger.txt`: pid 6464 → 13920 in 3s.
- `last_reload_ok: true`, `last_reload_error: null`, UI loop + game-poll
  worker alive, 0 ERROR/CRITICAL in new log lines.
- Vision server (`:8889`) uptime preserved - not restarted (separate
  process; its edits are in-place and take effect on next service cycle,
  not immediately).
- Phase 3 supervisor (`:8890`/`:8891`) heartbeating normally.
- iPad Chrome kiosk still polling `/api/sim-state` at ~500ms cadence -
  user's live session was uninterrupted beyond the 3s RC restart gap.

## Queue state after this pass

- 8 completed (task 0 audit + 7 first-audit proposals)
- 5 ready (frozen-file proposals; held pending user approval)
- 13 total tasks logged in `task_queue.jsonl`
- All proposals have full payload (fix_snippet, severity, source_report,
  filed_by=agent6)

## Deferred (not in this pass)

- **Hardcoded vision token** (`8e8f131e212b329438218eca27372dde` in 5
  files). Token flows across LAN between Legion and Game-PC for the
  relay. Proper fix: load from env var or gitignored config. Not
  exploitable on trusted LAN, deferred as hygiene.
- **Moon-PC dead-code sweep** - several scripts in `tools/`, `scripts/`,
  and `lan_bridge.py` itself still mention Moon-PC (`192.168.8.231`).
  `lan_bridge.py` was hardened rather than removed. A full dead-code
  audit belongs in a separate pass.
- **Ephemeral `claude` subprocess wiring** - still stubbed (H3 made it
  fail loudly). Follow-up session needs to write per-agent charters and
  implement the real `subprocess.Popen([...])` flow.
- **Agent 4/5/6 body code** - `safeguards/` gets a seed file in this
  pass but the learning loop, UI, and full auditor logic remain for
  future sessions.
