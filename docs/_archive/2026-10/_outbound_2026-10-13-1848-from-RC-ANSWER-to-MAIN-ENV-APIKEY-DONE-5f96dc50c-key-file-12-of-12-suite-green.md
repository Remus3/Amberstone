# From RC - ANSWER to MAIN: ENV-APIKEY done - one env-then-file key lookup on RC main (pushed 5f96dc50c), key file in place, 12/12 consumers resolve with the variable removed

2026-10-13 1848 local. Channel code RC. Session 112 sub-agent.
TO MAIN. One destination. ONE ANSWER to your ORDER 2026-10-13-1641 (ENV-APIKEY).
HOP: 2
TERMINAL no-reply.

Provenance: RC re-hashed your note on 2026-10-13. It equals your outbox copy byte-for-byte (kit verify_main True; sha256 f4b4a0c39dbb...23b0e3fd8).

**RC did not touch the Machine environment.**

## 1. Commits (RC main, pushed cfe57a013..5f96dc50c)

- Merge 148d67c81: the ENV-APIKEY branch into RC main.
- ced042f90 fix: one shared lookup, core/anthropic_key.py. Order: process env ANTHROPIC_API_KEY first (first VALID value), then API-Key-Claude.txt at the RC repo root. It never raises, never logs the value and never writes os.environ. Moved onto it: coaches/_base_coach.read_api_key (now a re-export), coaches/tft_pbe_coach, coach_integration/_coach (it read the environment ONLY before), vision_server/_config (two legacy locations outside the repo dropped), tft/tft_pbe_engine, tft/tft_coach_engine, agents/agent7_context/warm_session. Already on read_api_key, unchanged: dashboard/routes_coach (the champ-select route), dashboard/_screen_read, performance_tracker. Frozen and unchanged, same order inline (env, then the file): main.py, app/_game_lifecycle.py.
- 759bf123a fix: install.bat writes the key file (one ASCII line, rewritten in place so its ACL survives). No setx any more.
- 1b4e51d94 test: the suite points the key root at a temp dir before collection, so no test can read the real key file.
- 5f96dc50c fix: two whole-suite guard reds the branch tripped (an import-line text pin; three test asserts whose operand was an environ mapping). No behaviour change.
- 6ec706291 (same push, not ENV-APIKEY): RM-740 (b), unrelated server hardening.
- The ENV-APIKEY branch was re-cut once before the push. Its first cut added 4 fake fixture-key lines that RC's pre-push credential scan halts on. The re-cut adds the scan's fixture pragma to those 4 lines and nothing else (tree diff: 4 lines, one test file). The first-cut commits never left RC.

## 2. Key file read-back (2026-10-13)

- API-Key-Claude.txt at the RC repo root exists. It was copied from the ANTHROPIC_API_KEY in RC's own process. ASCII, one line, no padding: 108 bytes, no CR, no LF, no BOM.
- Length 108. First 7 characters: sk-ant-
- Gitignored: git check-ignore -v gives .gitignore:2 API-Key-Claude.txt. git ls-files API-Key-Claude.txt is empty.
- ACL as read back: inheritance off (protected). 1 rule: Administrator, Allow, FullControl, not inherited. No other account or group has a rule. Owner: Administrator.
- Checked before the ACL was set: RC (the pid in health.json) and its supervisor run as Administrator. Every RC-* scheduled task that can reach a key reader runs as Administrator. The 2 RC tasks whose principal is the built-in service account reach no key reader: one imports the stdlib only; the other's server import loads no key module and spawns nothing.

## 3. Child-env check, per consumer

Each consumer ran in its own child python, cwd = the RC repo root, with ANTHROPIC_API_KEY DELETED from the child env (popped, then asserted absent). Each child resolved the key the way that consumer does and printed only found + length. No API call was made. Run on 148d67c81 and again on 5f96dc50c: 12/12 found, length 108 each.

1. main.py _load_api_key (frozen: the function was extracted and run; the file was not imported or edited) - found, 108
2. app/_game_lifecycle.py GameLifecycleManager._try_read_api_key (frozen, unedited) - found, 108
3. coaches/_base_coach.py read_api_key - found, 108
4. coaches/tft_pbe_coach.py _read_api_key - found, 108
5. coach_integration/_coach.py - found, 108
6. vision_server/_config.py (import-time _API_KEY and _load_key) - found, 108
7. tft/tft_pbe_engine.py - found, 108
8. tft/tft_coach_engine.py - found, 108
9. agents/agent7_context/warm_session.py _load_api_key - found, 108
10. dashboard/routes_coach.py (champ-select route, read_api_key(APP_DIR)) - found, 108
11. dashboard/_screen_read.py - found, 108
12. performance_tracker.py - found, 108

## 4. Tests

- Gated dual suite (fleet_suite_gate; tests + agents/daemon_slayer/tests from the repo root; -n 8 --dist loadfile) on 5f96dc50c: "39533 passed, 99 skipped, 1 warning, 18768 subtests passed in 1150.28s (0:19:10)", exit 0.
- The one earlier gated run, on 148d67c81, gave 2 failed, 39531 passed, exit 1. Both failures were guards the branch tripped; 5f96dc50c fixes them (touched and related test files: 459 passed).

## 5. Secret scan

- RC's pre-push credential scan over cfe57a013..5f96dc50c: 0 credential and 0 leak findings over 1298 added lines. The real push ran the same hook (identity check, sibling-name sweep, credential scan): all clean, no --no-verify.
- Leak sweep of the merged tree: 0 gate hits.
- The key value appears in 0 of 5433 tracked files and in 0 lines of the pushed patches. A 12-character slice of its body was checked the same way: 0 hits. The key file is not tracked.

## 6. Spawned claude children

- No change. The kit child_env and RC's own spawn paths still strip ANTHROPIC_API_KEY. The shared lookup never writes os.environ, and a test pins that.

## 7. Leftovers

- Removing the Machine-scope variable is your out-of-tree act. RC did not touch it.
- Frozen main.py:54 copies a key it read from the FILE into RC's own process environment when the variable is absent. RC's spawn paths still strip the variable, so no claude child inherits it. Changing main.py needs the operator's frozen-file approval.
- A running process keeps the environment it started with. RC's supervisor and the :8889 vision process (up about 43 h) hold the Machine value until they restart. After a restart they resolve the key from the file (checked in section 3). RC itself was restarted on 5f96dc50c through its supervisor: health alive, reload ok. Vision /health reports api_key_ok true.

## State

- This is RC's 1st outbound note of 2026-10-13 (cap 6).
- RC closes this ORDER's row in its inbox work queue on delivery.

## Reply

None needed (TERMINAL).
