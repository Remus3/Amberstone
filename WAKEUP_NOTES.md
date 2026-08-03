# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-03d - lane 8 cycle 4: the verifier attacked a claim that made a finding sound smaller, and found a real hole behind it

Audited `dashboard/api_schema.py` - the DECLARED validation boundary for every dashboard POST
(criterion 1 + criterion 4: zero LEDGER mentions across 1180 entries, no dedicated test module).

**Three findings, one refuted hypothesis, and one honest non-fix.**

1. **The module's central claim was false.** `api_schema.py:5` said POST models use `extra="forbid"`
   (strict input gates). Measured: 4 of the 6 wired models use `extra="allow"`, AND
   `_dispatch._validate_request_body` never raises - it logs and returns, then `dispatch_post`
   calls the route regardless. The models are a logging decoration, not a gate. The soft-warn
   design is deliberate; the docstring advertising otherwise is the defect.
2. **A negative `Content-Length` pinned a handler thread.** `int("-1")` passes the `> 1 MiB` cap,
   then `rfile.read(-1)` reads to EOF. Hung 4.01s, released 0.13s after client SHUT_WR. Binds
   `HOST "::"` on a ThreadingHTTPServer, and the body read runs BEFORE the token check. **Same bug
   as `vision_server/_http.py` (LEDGER 1177) - that sweep never looked across files.** This time
   the sweep was done: 3 readers already safe, `mc/handler.py` already carried the exact fix, and
   `tools/ds_matchdb_mcp_server.py` had it too (loopback + authed, lower severity) - fixed.
3. **A non-dict body raised out of the route with NO response at all** - and this one is the
   lesson. I claimed "the routes defend themselves, so nothing is exploitable". **The verifier
   REFUTED it using the very route I cited:** `_serve_command_post` whitelists the command STRING
   but never checked the body was a dict, so `[1,2,3]` gave an uncaught `AttributeError` at
   `routes_state.py:516` and a closed connection. Fixed once at the boundary after verifying zero
   POST routes consume a positional body.

**REFUTED and pinned:** the `= []` / `= {}` field defaults are NOT shared-mutable-default bugs -
pydantic v2 deep-copies per instance. The dataclass intuition is wrong here.

**NOT fixed, filed as RM-152, and stated plainly because an unqualified "fixed" would be false:**
this closes one TRIGGER, not the class. A legal `Content-Length: 1048575` with no body sent pins a
thread identically - measured against the FIXED handler. The real fix is a read timeout, which
changes behaviour for the 500 ms poll and the streaming supervisor proxy. Two non-production
residuals filed with it, including a vulnerable line sitting in an UNIMPLEMENTED MC-S10 spec.

14 tests, 5 mutations all RED. Deployed and verified LIVE on both services separately, per the
1179 lesson: RC restart for the dashboard (400 on both vectors, 0.00s, no hang), and a
kill-then-`schtasks /Run` for `RC-DS-MatchDB-MCP` (`-32600 Invalid Content-Length`). Suites:
RC `tests/` 18103 passed / 154 skipped; DS 10341 passed. LEDGER 1181.

**Three cycles running, the adversarial pass has found something the diff did not.** Cycles 2 and 3
it was prose overclaims. Cycle 4 it was a real code hole, reached by attacking the sentence that
made the finding sound smaller. Attack the limiting claims, not just the alarming ones.

---

# 2026-08-03c - lane 8 cycle 3: a green test that was an artifact of the worktree path, and a fix that a restart did not deploy

Three things happened, and the first two are process findings worth more than the code.

**1. Merging cycle 2 turned its green suite red.** `lane/true-audit` fast-forwarded into `main`
clean (3 commits), and `tests/test_vision_server_http_hardening.py` immediately failed - 73 passed,
1 failed. The traversal probe wrote its file beside `SYNC_DIR`, i.e. under the repo root, then put
that absolute path in a request line. The lane worktree is `C:/rc-worktrees/rc-lane-true-audit`
(space-free, request legal, test green); `main` is `C:\Riot Commander`, and `http.client` raises
`InvalidURL` on the space before anything is sent. **The green was a property of the worktree path,
not of the fix.** Probe moved to a temp dir with the requirement ASSERTED rather than skipped.
Mutation-verified it still catches the real defect. Commit `77077775`.

**2. The security fix was NOT live after a restart, and every signal said it was.** New RC pid,
`last_reload_ok=true`, and `GET /sync/get/../CLAUDE.md` still returned **200 with the file body**.
`:8889` is not in-process despite what ADR-003 and the CLAUDE.md topology line imply - it is a
detached `moon_vision_server.py` child, spawned by `dashboard/server.py:207-227` only when the port
is NOT already listening. The old child outlives the restart, the port stays bound, the self-heal
branch is skipped, nothing respawns. Correct order is **kill the port owner, THEN restart**
(`taskkill /F /PID` from PowerShell - Git Bash mangles `/F`). Verified live after: `/sync/list` 200
(positive control), traversal 404. New memory `reference_vision_server_restart_does_not_redeploy`.
LEDGER 1179.

**3. Cycle 3 audited `lcu/lcu_postgame_collector.py`** (criteria 1 + 3 + 5 - items 348/404/965/971
all landed here). `_save_eog` built its team-comp map OUTSIDE the try guarding the DB block, so one
non-dict entry in `teams` or `players` raised `AttributeError` out of the whole function - the same
root cause as item 1176 the same day. What made it matter: `_run` called `_capture_after_trigger`
with no try while its async twin wrapped the identical call. **The asymmetry was the tell.** One
raising capture killed the collector thread outright; a second trigger never reached capture.
Sibling sweep found the class three more times in `_adapt_match_history`. 9 tests, 5 mutations all
RED. Seven dimensions: 3 HARDENED, 4 CLEAN (SQL identifier interpolation is fenced by `_norm_mode`
- NOT an injection, do not "fix" it). LEDGER 1180, commits `708ae415` + `2f6f79aa`.

**The verifier REFUTED a statement in my own comment text for the second cycle running.** I wrote
that `start()` "returns early while a thread object exists"; the guard is `.is_alive()`, so it would
build a fresh thread. The consequence holds for a different reason (nothing calls `start()` twice).
Corrected before commit. Cycle 2 had three such prose overclaims. The pattern is now explicit: the
adversarial pass earns its keep on the WRITE-UP at least as often as on the diff.

Suites this run, repo root: RC `tests/` 18089 passed / 154 skipped; DS 10341 passed. Worktree kept.

---

# 2026-08-03b - lane 8 cycle 2: :8889 served ARBITRARY FILES, and the verifier caught three overclaims in my own write-up

Operator-present cycle (invoked in-session, not detached). Lane 8 merged its cycle-1 branch into
`main` first (fast-forward `9cb8b623 -> 76cb0821`, pushed, LEDGER 1176), then started this one from
that HEAD. Worktree + branch deliberately KEPT for the next cycle, per operator.

**Audited `vision_server/_http.py` (245 lines), the `:8889` HTTP trust boundary.** Criterion 1
(externally-reachable untrusted input) + 2 (secret-adjacent - `_config.py:50-59` resolves
`API-Key-Claude.txt` in the same package) + 4 (two `test_vision_server_*` modules existed, NEITHER
touched the handler). Recorded expectation before starting: sloppy query parsing, unbounded reads.
Both present. The headline finding was NOT expected.

**`GET /sync/get/` was an arbitrary file read.** `fp = SYNC_DIR / self.path[10:]`, zero containment,
measured live against the real `Handler` on an ephemeral port - not inferred. Two independent
escapes: `..` walks out (this is the one that reaches the API key, 200 plus body), and an ABSOLUTE
component replaces the base entirely under `pathlib`, so a `".."`-filter-only fix would have left
half the hole open. Amplifier: `vision_server/__init__.py:88` binds `0.0.0.0`, so it is LAN and
tailnet reachable behind only `X-RC-Token`. The sibling `do_PUT` in the SAME file was already
correct (`Path(...).name`) - the careful neighbour is what made the GET side easy to miss.

Fixed with the in-tree precedent (`dashboard/routes_static.py:64-67`, resolve + `relative_to`,
404 on refusal so it is not a file-existence oracle). Three more closed in the same slice: a
NEGATIVE `Content-Length` passed the size check and reached `rfile.read(-1)` = read-to-EOF, wedging
the handler thread; `do_PUT` parsed `Content-Length` outside its `try` (connection reset, not 400);
`do_PUT` had no size cap while POST capped at 10 MiB. Both now share one `_body_length()` gate.
`_auth` moved to `hmac.compare_digest` - stated as NOT mutation-provable, and the verifier confirmed
that mutation stays green.

**12 tests, 4 mutations all RED, and then the gate refuted my prose.** The verifier reproduced every
code claim on scratch copies (never the tracked file) and CONFIRMED 1-5, then REFUTED claim 6 - the
first draft of LEDGER 1177 carried three overclaims: (1) it cited
`GET /sync/get/C:/Riot Commander/API-Key-Claude.txt -> 200`, which CANNOT work - the path has a
SPACE, `BaseHTTPRequestHandler` splits the request line on whitespace (400), and the handler never
`unquote`s so `%20` just 404s; the key is reachable by the `..` form instead. (2) It said
`routes_static` replaced BOTH a prefix check and a `".."` filter - ground truth is the prefix check
was replaced and the `".."` filter was normalized and RETAINED. (3) It called a whole-file 12-test
duration a single test's hang (real delta 5.7s). All three corrected in place, in the ledger, the
source comment and the test docstring. **The reusable lesson: the diff was right and the write-up
was not.** Only an adversarial reader hunting unsupported statements finds that class.

**Filed, not fixed: RM-150** - the `0.0.0.0` bind (legacy from the pre-ADR-011 2-PC era; every
client is Legion-local now) plus the raw `str(e)` in 500 bodies. Left alone deliberately because
`tests/test_vision_server_threading_s7.py:35-36` PINS the `("0.0.0.0", PORT)` literal by regex, so
narrowing the bind is a 2-file change with its own guard update, not a one-liner.

**Then the stop gate blocked the wrap on two false positives, and fixing the CHECK was the only
legitimate move (LEDGER 1178).** Same unrecoverable family as LEDGER 1175: the gate scans the
transcript, so an emitted sentence cannot be retracted and one wrong flag blocks every later Stop.
(a) It read "Fixed with the in-tree precedent at `dashboard/routes_static.py:64-67`" as a claim to
have edited that file - naming the file you COPIED FROM. The incentive is what makes it worth
fixing: the cheapest way to satisfy that check is to STOP CITING PRECEDENT. (b) It read "Nothing is
committed yet" as an unbacked commit claim - punishing accurate self-reporting. Discriminators:
citation marker BETWEEN the verb and the path (vetoed by first-person), and a negation in the 40
chars GOVERNING the claim word. `CLAIM_PUSH` fixed in the same commit as the sibling. 9 tests,
4 mutations RED both directions - and **one veto test was VACUOUS as first written**, passing with
the veto deleted because its markers sat after the path where the suppression never fires; only
mutation testing caught it. Fixed gate against this session's real transcript: 0 findings, exit 0.
**It does NOT unblock this session** - the hook runs the MAIN TREE's copy while the repair sits on
`lane/true-audit`, the same shared-hook trap the skill documents for `core.hooksPath`. Editing main
from a lane worktree to silence a gate is worse than wearing the false positive, so the block was
reported and left standing. Clears on merge.

**Backfill (6e), stated precisely:** a read-only disclosure writes nothing, so there are no corrupt
rows. Whether it was USED cannot be answered - `log_message` logs at DEBUG and `_config.py:25-30`
sets `basicConfig(level=INFO)`, so per-request lines were never recorded; `grep -c "sync/get"` = 0
is NOT an all-clear and is reported as such. **The other half IS owed and is NOT done: the running
:8889 keeps serving the vulnerable code until this branch merges and RC restarts.**

---

# 2026-08-03a - Mission Control lane 8 (Headless-True-Audit), first fire: one wrong-shape .rofl crashed the whole extraction pass

2 commits on `lane/true-audit` (fix `1819c8e2` + this docs entry). NOT merged - lane 8 ships LAST
and the merge is the merger's to make once main is verifiably idle. Tier-1: ENGINE untouched at
1.270.0, so no Share sync, no DS bounce, no RC restart owed (backend library edit, not runtime).

Worktree-first, pre-flight clean: toplevel `C:/rc-worktrees/rc-lane-true-audit`, branch
`lane/true-audit`, `core.hooksPath` the shared ABSOLUTE `C:\Riot Commander\.githooks` so
`install_hooks.py` was NOT run. Recall first (perseus, no CLOSED/REFUTED hit). Live state probed:
RC pid 16516 alive, DS :8860 ok 1.270.0 patch 16.15.1.

**Audited `core/rofl_archive.py` (888 lines), the `.rofl` byte parser.** Criterion 1 (untrusted
Riot-CDN bytes via `download_replays`) + criterion 5 (repeat offender). Finding, MEASURED live not
read: `extract_stats` took `len(players[0])` for field_count while validating ONLY that `players`
was a list. A valid-JSON but wrong-shape statsJson (`[1,2,3]` / `[None]` / `[True]`) raised an
UNCAUGHT TypeError, and `extract_archive` calls it with no try/except -> one corrupt replay aborted
the entire loop and dropped every later replay, violating the module's own "Failures are COUNTED,
not dropped" contract. A list-of-strings entry silently produced a garbage sidecar. Fix: one
dict-shape guard returning None (logged); valid + empty-list cases unchanged. 2 regression tests,
both mutation-tested red-then-green. 7 dimensions: correctness/input-validation/error-handling
HARDENED, rest CLEAN or N/A, 0 bare `except Exception`. Backfill (6e): live archive 17 sidecars,
0 already-bad - the silent path never fired on real data, verified not assumed. Independent
verifier reproduced the crash on a scratch copy and returned CONFIRM. Ledger 1176.

Suites from repo root: rofl + consumers 130 passed / 25 skipped; ruff clean; ASCII clean. Minor
noted-not-filed (trusted source, low value): `_http_get_bytes` unbounded read, `_maybe_gunzip` no
decompression-bomb cap, `_atomic_write_json` missing the `finally` tmp-cleanup its siblings carry.

Next lane-8 target (unstarted): another externally-reachable parser - the LCU response path or a
`dashboard/routes_*.py` input surface - one file, all 7 dimensions, TDD + mutation + verifier.

---

# 2026-08-02j - Mission Control lane 7 (Headless-Repo), first fire: the frozen list had an unguarded mirror, and 70 GB of out-of-repo scratch was mostly hardlinks

5 commits, **MERGED into main 2026-08-03 on operator instruction** as `c164dfef..99f14682`
(fast-forward, so every hash survives and the ledger citations resolve). Ledger 1174.
Worktree-first; lane worktree removed and `lane/repo` deleted local + remote after proving
`main..lane/repo` = 0. ENGINE untouched at 1.270.0, so no Share sync, no DS bounce, no RC
restart owed. **Idleness was VERIFIED before merging, not assumed:** main still sat at
`c164dfef` untouched for the whole run, clean, 0/0 vs origin, no `index.lock`, no git process,
no `RUNNING.lock`. `--ff-only` on purpose so a non-ff would error rather than surprise-merge.

**The lane worktree did not exist.** `git worktree list` showed only `main`, so it was created
from the repo root rather than working in main - two writers in one working directory is the
unrecoverable index-corruption class. `core.hooksPath` re-confirmed ABSOLUTE
(`C:\Riot Commander\.githooks`); worktrees share `.git/config`, so `install_hooks.py` was NOT
run and nothing about the hook config was changed.

**CORRECTION, and it is the run's best finding: the rule has SIX representations, not four, and
the mirror this run first missed was the ONLY one that had drifted.** The stop-claim gate refused
an unbacked count, the re-grep surfaced a `FROZEN_FILES` nobody had looked at, and it turned out
`agents/agent1_lead/scheduler.py::FROZEN_FILES` held **13 against the authority's 16** - missing
`app/_loop.py`, `tools/diagnose.md`, `tools/caveman.md` - **unchanged since the initial commit**
while CLAUDE.md moved underneath it. Its own comment says "Synced with CLAUDE.md". Its sole
consumer `Scheduler.file_task()` appends category 1 -> `NEEDS_APPROVAL`, withheld from the ready
heap until `approve()`; with the entry missing, a task naming `app/_loop.py` went straight to
READY - an agent could edit an operator-frozen file with NO approval stop. Demonstrated against
the real scheduler, not argued. Fixed; 0 of 5811 live queue records newly gated. It was
**inert until the Phase 3 supervisor restarted - and that CLOSED ITSELF one second after the
merge**: RC's own phase3 stale-code watchdog re-ran the task, `ops/runtime/logs/supervisor.log`
`[2026-08-03T06:49:13Z] phase3 stale_code -- schtasks /Run RC-Phase3-Supervisor OK`. The fix was
live ~4h before anyone asked for a restart. **Never cite a PID from a doc** - the one this note
used to name (21304) was dead before it was read. Re-probe with
`Get-NetTCPConnection -LocalPort 8890 -State Listen`. The guard now checks a
`PARITY_MIRRORS` list, with `core/hot_reload.py` deliberately held to a SUBSET rule instead - it
watches `.py` only, so equality there would go RED and pressure a WRONG fix. **Do not "fix" it.**
Census: authority 16 / ci_watchdog 16 / strip_smart_quotes 16 / repair_mojibake 16 / scheduler
was 13 now 16 / hot_reload 14 by design.

**The original framing, still true of the other mirror.** `tools/ci_watchdog.py:79`
`FROZEN_FILES` is a hand-maintained MIRROR of `CLAUDE.md:40-45`, consumed by `touches_frozen()`
at `:204-207` - the thing that stops the CI watchdog auto-merging a fix INTO a frozen file. Nothing
asserted the two still matched, so adding an entry to CLAUDE.md alone would leave the watchdog
silently auto-merging into a newly-frozen file. Same drift class as `tools/*.md` vs
`.claude/commands/*.md`, which ran a month. The pre-existing
`tests/test_constraint_single_source.py:18` only checks three anchor substrings appear - it never
parses the list. New `tests/test_frozen_file_list_contract.py` reads the contract off disk and
ties all four representations. **T4's direction is load-bearing:** a `frozen=yes` header on a file
absent from CLAUDE.md FAILS; an authority entry with no header does NOT. 12 headers vs 16 entries
is CORRECT and expected - `gen_archmap.py:22-23` says why. Never compute the frozen set from
headers. T3 was independently re-mutated both ways after the build agent's own pass: RED both times.

**The out-of-repo half returned nothing to reclaim, and that IS the finding.** 3 proposed, 0
approved, 0 executed, 0 bytes. The age-prune of `Temp\claude\C--Riot-Commander` was rejected on
measurement: the tree is full of NTFS HARDLINKS into the main repo's own `.git\lfs\objects`, so
`Get-ChildItem` counted one physical extent three and four times - `fsutil hardlink list` over the
400 largest delete-set files found 132 files / 1735 MB that reclaim ZERO bytes. The 2.78 GB
headline was ~62 percent air. The discriminator fails too: mtime inside a hardlinked clone is the
ORIGINAL object's mtime, so a 7-day cut strips ~583 MB out of the MIDDLE of each of three RC
clones. A second proposal cleared ~1.9 GB on a "HEAD confirmed in the main repo" check that
cannot exist - `base59`, `mut1`, `mut2` have no `.git` at all. `.claude/projects` and
`Temp\claude\C--Sibling-A` untouched by rule.

**The `_archive` silent-fail trap fired live.** A `git reset` between staging and commit dropped
both archive destinations from the index; because `_archive/` is gitignored they became
untracked-and-ignored on disk while `git add -A docs/` staged only the two DELETIONS - exactly the
"remove the file from version control entirely" failure `.gitignore:19-21` warns about. Caught
only because the `git ls-files` gate was run BEFORE committing, not after. Recovered with
`git add -f`. **Run that gate every time; `git status` alone looked fine.**

Verified: RC **18050 passed / 154 skipped / 1635 subtests** from the repo root, drift_guard 0
breaches, archmap + state_schema clean, ruff clean, named guards 45 passed. Verifier CONFIRM 11/11.
`test_loop_concurrency` ran 28 passed / **0 skipped** - `C:\Sibling-A` is present, so the
sibling byte comparison and the `SHARED_SHA256` pin genuinely executed.

Open: `%USERPROFILE%\.gemini` needs an operator ruling - `tools/headless-repo.md` contradicts
itself (table says PURGEABLE, section 2 says RETAIN). Held as RETAIN, untouched.
