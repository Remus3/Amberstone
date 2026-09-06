# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-06c - LANE 8 true-audit: core/rofl_archive.py, and the verifier caught MY regression

On main: `387a593a2` (code+tests), `4fcf1980b` (LEDGER 1354), `66f167a90`
(gitignore fix). RM-310 CLOSED, RM-371 now PARTIAL (its rofl third done, the
`core/riot_api.py:319` and `core/sgp_client.py:167` thirds UNCHANGED).

Audited `core/rofl_archive.py` (repeat offender - lane 8 had done it twice
already, LEDGER 1176 + 1311, and it still carried two open lane-8 rows). Five
weaknesses, all fixed, 11 guards, 9 mutations all killed.

**The thing worth remembering: the verifier REFUTED the slice and it was right.**
Bounding the gunzip with `zlib.decompressobj` silently ACCEPTED truncated bodies
that `gzip.decompress` had rejected via EOFError - a 43-percent-truncated replay
kept its RIOT magic, passed validation, was written under its final name, and
was recorded in an index that is idempotent on match id, so every later pull
skipped it FOREVER. Neither the 8 guards nor the mutation driver could see it:
the driver only mutates lines the guards already cover. **Swapping a stdlib call
for a bounded equivalent changes its ERROR contract as well as its size
contract, and the error contract is the half nobody tests.** Fixed with
`not dec.eof` + a member loop.

Second verifier catch: my archive probe used a NON-recursive glob, so I reported
15 replays / 18.6 MB max when the truth is 13896 / 180.4 GiB / 28.48 MB max.
Corrected in code and ledger. The 64 MB ceiling is right either way, and it must
NOT inherit `lib/http/client.py`'s 16 MB default - real replays exceed it.

Do NOT redo: the 3 RC suite failures in the lane worktree are CRLF-environmental
(`core.autocrlf=true`, 1878 files), they pass on the clean main tree. An earlier
suite run reported "22 failed" - that was a crashed xdist worker aborting the
session, not regressions.

**Pre-publication audit run this session (operator is considering going public,
chose MIT).** Findings in chat; the actionable set: `config/vision_token.txt` is
a TRACKED live 32-hex `X-RC-Token` secret from the initial commit (rotate per
`core/vision_token.py:12-30`; `:8889` is loopback-only so it was never a remote
vector); 48.9 MB of scraped Aggregator J HTML nothing reads; lolmath/Overlay App E/101qq
data shipped as verbatim vendor payloads. Operator decided: delete Aggregator J,
obfuscate lolmath + its history, drop `Share/` at publish. NOTE Overlay App E
`mayhem_augment_stats` IS referenced by `tools/ds_feed_index.py` +
`tools/ds_share_sync.py`, and the 101qq raw capture IS the live duo-synergy
fallback seed - neither is dead, both need re-expression, not deletion.
**A history rewrite is NOT safe to start opportunistically: 6 live worktrees and
lane 10 pushes to main continuously. It needs a quiet window.**
MIT should land in the SAME pass as the data purge, not before - otherwise it
asserts an MIT grant over data that is not ours.

---

# 2026-09-06b - LANE 10 cycle 15: RM-364 shipped, and it ADOPTED a crashed cycle

RM-364 is on main (`d9e8c5d98` code, `f01918b4b` sha citation). LEDGER 1353.
The prompt sanitizer had ONE production importer against 17 Anthropic egress
files; the five ranked ones are now cleaned at prompt ASSEMBLY, and the
population is pinned by a bidirectional census guard instead of remembered.
Residue filed as **RM-381 OPEN** (7 builders + the two `_run_coach` sites the
file-level guard structurally cannot see).

DO NOT REDO / read before touching this area:
- The fix is at ASSEMBLY, never at `messages.create` - `moon_proxy.get_coaching`
  is the PRIMARY egress for the TFT builders, so an API-call-side guard is dead
  code on the live path. This was measured, not assumed.
- The threat model was CORRECTED by the row's own census: no summoner name,
  riot ID, chat or queue name reaches any prompt. The unconstrained bytes are
  Haiku-VISION OCR output - a self-inflicted model-to-model channel.
- `modes/shared_vision.py` + `tft/tft_vision_reader.py` were REFUTED, not
  missed: their untrusted input is PIXELS. Do not "fix" them.

**NEW FINDING, worth more than the row:** the pre-commit hook pulled
`docs/ARCHITECTURE.md` in, and running `tools/gen_archmap.py` reproduced
**RM-378 live** - it rewrote the whole file as CRLF (343 pairs), reddening
`tests/test_text_line_endings.py` while `git status` read CLEAN throughout.
The committed blob was never affected. One datum for **RM-343**, fenced: the
re-checkout produced LF because `.gitattributes` pins `eol=lf`, overriding
`core.autocrlf=true` in the shared `.git/config` - so THAT file's CRLF came
from the generator, not from worktree materialization. One file, not the 1884.

---

# 2026-09-06 - LANE 10 BUILT AND RAN: a queue-drain loop shipped 15 rows overnight

**FIRST ACTION NEXT SESSION: stop the queue loop before firing anything else.**
The lane roster is a 1-slot mutex, so a new lane cannot start while this one
holds it. Clean stop, at a cycle boundary, no work lost:

```
echo stop > "C:\Riot Commander\ops\loop\control\lanes\QUEUE_STOP"
```

Then delete that file once the driver has exited, or the next launch refuses.
Hard stop if needed: `taskkill /F /T /PID <driver pid>` (never `Stop-Process`).
Driver pid is in `ops/loop/reports/queue_loop.log`; cycle history is
`ops/loop/reports/queue_loop.jsonl` (both gitignored as of this session).

STATE. LEDGER 1338. NEW lane 10 `queue`: `tools/headless-queue.md` (worker
prompt), `ops/loop/queue_loop.py` (driver), `ops/loop/launch_queue_loop.ps1`,
roster wiring in the five sites that must agree, plus a `README.md` refresh
(the port map was missing `:8890` / `:8891` / `:8895`). It drains one filed row
per cycle: the worker ships exactly one row and EXITS, and the driver re-fires
it, because a worker that looped internally would accumulate context until it
degraded and a crash in row 4 would take rows 1-3 with it.

SHIPPED BY THE LANE, unattended: **RM-348 through RM-360 plus RM-363** - the
entire lane-5 refill queue - each its own commit, ledger entry and CI green.
It also FILED RM-369 through RM-379 off its own sibling sweeps. Next free id
was RM-380 at hand-off; re-derive, do not inherit.

**THE LESSON WORTH THE MOST, and it cost three iterations: an instruction a
worker can rationalize past is not a mechanism.** CI acceptance was
unsatisfiable at the lane's own cadence - `ci.yml:38-40` cancels in-progress
runs per concurrency group, a run takes 45-67 min, a cycle takes 25-45, so
cycle N+1 always killed cycle N's run. Fix 1 moved the read to a
`workflow_dispatch` group; the lane's own next dispatch cancelled it 23 minutes
later. Fix 2 told the worker in prose to BLOCK until its run completed; over six
cycles it complied twice and bailed early four times. Fix 3 moved the wait into
the DRIVER (`wait_for_ci`), which cannot rationalize because it is the only
thing that starts the next cycle. Verdicts now land inside each cycle's own
JSONL row; a `failure` sets `stopped_by=ci_red` and stops the loop. **The lane
filed RM-370 against my first two attempts - read it before touching this.**

FOUR DEFECTS IN MY OWN WORK, all found by RUNNING it rather than reading it:
the launcher passed an unquoted path so `pythonw` got `C:\Riot` and the launcher
printed "driver started" over a dead process; three tests read live machine
state (one asserted a stale `STOP` file existed, two took the REAL driver mutex
and went red exactly when the lane was looping); and `lanes.py` said "seven
headless lanes" over an eight-entry tuple - fixed by deleting the count from the
prose, not incrementing it.

MEASURED THIS SESSION, for anyone sizing work on this box: dual suite 31854
items, **250s at `-n auto` / 5070s serial** (20.5x, superlinear - the suite is
wait-bound); `-n auto` resolves to **8 workers, not 16** (Ryzen 7 7700X, 8
physical / 16 logical); pre-commit gate on a 1-file commit **2.6-5.3s**; and
**there is no pre-push test hook at all** - `.githooks/pre-push` is the stock
Git LFS hook, so CI is the only suite gate.

NEXT SESSION, as directed: a **true-audit headless loop lane** and a **research
headless loop lane**, both on the lane-10 driver pattern rather than one-shot
fires. **Blocker, stated so it is not discovered at run time:**
`ops/loop/lanes.py:138` is `MAX_SLOTS = 1` and the 1-slot bucket IS the mutex,
so two concurrent RC lanes need that raised, with `tests/test_lane_lock.py:138`
and the module docstring updated deliberately. Machine budget and the
oversubscription math are now in `docs/MISSION_CONTROL_PLAN.md` under "Machine
concurrency budget": RC 2 lanes, Resin 1, Sibling-E 1, and a second RC slot
wants a worker-side `-n 4` cap because `-n auto` is 8 and two suites at once
would put 16 pytest processes on 8 physical cores.

ALSO: RM-368 filed for the `github.com/affaan-m/ECC` harness lift - MIT, license
gate passed against all three declarations, whole-package lift REFUTED in the
row itself, three sub-rows worth taking. A Sibling-E session was spawned
separately to port this lane there.
