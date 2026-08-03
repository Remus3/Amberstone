# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-03f - lane 8 cycle 6: a relay that reported only to a console it does not have, and a token literal the dashboard hands out

Audited `tools/liveclient_relay.py` - zero dedicated tests, running live as `RC-LiveClientRelay`.
Picked deliberately for a different SHAPE than cycles 4-5: an agent loop, not a server or a store.

**FINDING 1 - every diagnostic went nowhere.** The task's `<Command>` is `pythonw.exe` (no
console) and the module reported only via `print()`. It already KNEW - its own comment warns a
stale token "401s ... silently (pythonw, no console) -> coach dead" - and kept printing anyway.

**FINDING 2 - a dead token literal in FOUR files the dashboard SERVES UNAUTHENTICATED.**
`_serve_agent_file` has no auth at all and the dashboard binds `::`, so `GET /agent/<name>`
returns the source to anyone on LAN or tailnet (verifier confirmed reachable on both, not just
loopback). The literal is dead - proven by POSTing it to :8889 and getting 401 while the live
token 200s. **The fourth file was found by the test, not by me:** my hand grep checked the names I
happened to eyeball; the test reads `_AGENT_ALLOWED` off disk via `ast` and parametrizes over it,
and caught `phase_watcher.py`.

**FINDING 3** - upload target was a hardcoded LAN IP, sending the token in cleartext across the
LAN when both ends are the same machine. Now loopback, env-overridable. Verified :8889 accepts the
loopback POST *before* trusting the change.

**REFUTED:** no timeout-less call exists here (2s/3s already). My expectation was wrong.

**The logging test took THREE attempts to become non-vacuous, by two different mechanisms.** v1
read pytest's own root-logger handlers (`basicConfig` is a no-op when handlers already exist), v2
used a fixed marker that a stale log file already contained. Only mutation testing ever said so.

**The verifier REFUTED a measurement of mine.** I had recorded `screen_agent`/`phase_watcher` as
"already file-logging, the template to copy". They call `basicConfig` with no `filename=`/
`handlers=` - stderr only, discarded under pythonw exactly like a print. **My grep counted the
string `basicConfig` as evidence of file logging** - the function name, not the argument that
matters. RM-154 rewritten; it was pointing the next implementer at a broken template.

**Then the deploy caught a regression the diff could not.** With the FileHandler live and no game
running, the relay wrote a WARNING every ~6s: ~2 MB/day burying the one line that matters. Giving
a silent module a channel is only half the job. Now WARN-on-change / DEBUG-on-repeat / INFO-on-
recovery. Measured live: old process ~50 warnings in 5 idle minutes, new one logged once and grew
**0 lines in 45 idle seconds**.

**RM-155, found by accident and worth more than it cost: the RC suite is NOT IDEMPOTENT in a fresh
tree.** `data/fusion_shadow.jsonl` is gitignored; run 1 SKIPS the invariants test and passes -
and the suite itself writes 1 record to that production path. Run 2 reads the 1-record corpus,
stops skipping, and fails. Measured end to end. Never bites a dev box (main tree has 565 records).
NOT caused by this slice - main tree at HEAD passes.

Also self-inflicted and owned: my first RM-154 draft blew the ROADMAP 80 KiB CI budget; fixed by
compressing rows and leaving narrative in the LEDGER where it belongs.

22 tests, 5 mutations RED. RC `tests/` 18136 passed / 154 skipped; DS 10341 passed.
LEDGER 1183 (+ post-deploy addendum). Deployed + verified live on the relay task.

**Session wrap (cycles 3-6, one session).** Four files audited end to end, all 7 dimensions each:
`lcu/lcu_postgame_collector.py` (1180), `dashboard/api_schema.py` + `_handler.py` (1181),
`core/riot_api_cache.py` (1182), `tools/liveclient_relay.py` + 3 sibling agents (1183). Plus the
cycle-2 merge and its two process findings (1179). **Filed, not fixed: RM-151..RM-155.** At wrap,
`drift_guard` flagged ROADMAP at 100 percent of its 81920-byte budget - relocated the CLOSED
RM-04 roster sweep (13589 bytes, zero open markers) verbatim to `docs/ROADMAP_HISTORY.md`,
leaving a fence that keeps the two probe hazards. ROADMAP now 68892 bytes / 84 percent.

---

# 2026-08-03e - lane 8 cycle 5: a cache that dies silently forever, and 3.33 GB nobody could see

Audited `core/riot_api_cache.py` - **zero LEDGER mentions across 1181 entries**, never audited,
sitting on the API-key path and persisting external Riot bodies.

**My headline expectation was REFUTED and the design was right.** I went in expecting the API key
in a cache key or a log line. Keys carry `_key_fingerprint()` - a real `sha256[:12]`, verified as
actually hashing, not a docstring promise. The verifier scanned all 3.3 GB of payloads, not just
keys: zero `RGAPI` anywhere. Recorded as a negative so nobody re-spends on it.

**FINDING 1 - a deleted DB file killed the cache for the life of the process.** `_ensure_schema`
short-circuits on `self._initialized`, which is PROCESS state, not FILE state. Lose the file and
SQLite makes a new empty one, the schema never re-runs, and every call fails "no such table" -
caught, logged, returning None/False. **Callers cannot tell that from a cache miss**, so RC
re-fetches from the Riot API forever, burning rate limit, silently, until restart. Fixed by
clearing the flag on that specific error. The call that NOTICES still soft-fails and only the next
one heals - documented that way rather than oversold, and the verifier was pointed at that claim
specifically.

**FINDING 2 - three docstring claims untrue of the code**, incl. a promised `BEGIN IMMEDIATE` that
appears exactly once in the file: inside the sentence promising it. The concurrency is actually
fine (autocommit + single-statement atomicity). Third cycle running where a module's prose was the
defect.

**RM-153 - the operationally important one.** `cache_immutable` never expires by design and the
live DB is **3.33 GB / 12,305 rows, freelist 0** - all real data, a VACUUM reclaims nothing.
Nothing caps it, nothing watches it, and the only introspection reported ROW COUNTS and had no
production callers. `stats()` now reports bytes; picking an eviction policy is an operator call.
Check first whether `rewind_history.db` + the `.rofl` archive already duplicate this retention.

**The verifier found two defects in my own work, and the second one matters.** (a) I wrote "no
callers anywhere in the tree" - literally false, tests call both; now "no production callers".
(b) **My BEGIN IMMEDIATE guard accepted a docstring MENTION as proof of executable code** - it
scanned everything after the module docstring, including method docstrings, so re-adding the false
promise plus a decoy mention stayed green (measured: 11 passed). Rebuilt to strip docstrings via
`ast`; the demonstrated evasion is now RED. A guard that accepts prose as proof of code is the
`feedback_guard_on_nondefault_call_path_is_untested` shape wearing a different hat.

Also worth keeping: **one mutation silently failed to apply** - a shell heredoc mangled a line-
continuation backslash, the anchor assert fired, and the suite trivially passed 11. Caught and
re-run from a file-based script, which produced the real 3-test RED. A mutation that does not
apply looks exactly like a guard that works.

11 tests, 5 mutations RED. Suites: RC `tests/` 18114 passed / 154 skipped; DS 10341 passed.
Deployed + verified live (RC pid 1880; `stats()` now surfaces the 3.33 GB). LEDGER 1182.

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
