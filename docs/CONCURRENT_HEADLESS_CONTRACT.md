# Concurrent Headless Loops - the three-project contract

**Status:** authored 2026-08-01 on Legion, from the RC / Sibling-A / Sibling-C
build. Written to be **handed to a different machine with three different
projects**, so nothing below names a project except in examples, and every
project-specific value is a parameter.

**ROSTER UPDATE 2026-09-06.** The "authored from" line above is left as written,
because it records which build this document came out of and that does not
change. The CURRENT trio does: Sibling-C is archived read-only at
`a sibling private repo`, its working copy at `C:\Sibling-C\` is deleted, and
**Sibling-B takes the vacated slot** in the machine-wide concurrency
governor. Its path is `C:\Sibling-B` - with a SPACE, not a hyphen.
Participants are now RC, Sibling-A and Sibling-B. The count is
unchanged at three, so `MAX_CONCURRENT_SLOTS` stays 3: the bucket models
ANTHROPIC ACCOUNT concurrency, one rate-limit pool, and a pool does not shrink
because a name changed. Source: `moon_sync_inbox/2026-09-06-1702-from-RM-
archived-resin-compute-takes-the-third-slot.md`, RM's final message.

**The shared-file half is DONE on RC's side, and RC was the follower.** RM's
message asked for `ops/loop/slots.py` line 5 to read "Sibling-B" where it
read "Sibling-C". **Sibling-A authored those bytes and carried the red
window**; RC discovered it the way the guard intends - not by reading the note,
but by `test_shared_modules_are_byte_identical_to_lw` going red against LW's
live tree. RC then copied LW's file VERBATIM (a byte-level copy, never a text
write: `write_text` turns LF into CRLF on Windows and the pin is on bytes),
confirmed the ONLY delta was that one line, re-hashed from its OWN disk, and
re-pinned `SHARED_SHA256` to `1c4f8af4...`. Do NOT edit a pin constant to make a
local edit pass - re-sync the file, then let the digest follow.

**Still outstanding, and it is not RC's to do:** Sibling-B vendors its copy
LAST, since it has no pin to break until it has one.

**What this is.** Three separate repositories, each running its own autonomous
headless Claude loop, on one machine, at the same time, without stepping on each
other. It is a set of shared conventions plus one genuinely shared file.

**What this is not.** A framework. There is no central daemon, no registry
service, no orchestrator-of-orchestrators. Every project stays standalone and
independently runnable. Coordination is achieved by each project agreeing to the
same small set of rules about **names and one lockfile directory**.

**The one-sentence version.** Everything that can be namespaced per project IS
namespaced per project; the only thing genuinely shared is a machine-wide token
bucket that bounds total concurrent AI worker calls, because that is the one
resource no amount of naming can partition.

---

## 0. The seven shared surfaces

On a single Windows box, three projects collide on exactly seven things. Six are
solved by namespacing. One is not, and that is the interesting one.

| # | shared surface | solved by | mechanism |
|---|---|---|---|
| 1 | TCP ports | namespacing | disjoint blocks, section 2 |
| 2 | scheduled tasks | namespacing | `<PREFIX>-*`, section 3 |
| 3 | the Desktop | namespacing | `<PREFIX>-NEXT-SESSION.txt`, section 8 |
| 4 | OS named mutexes | namespacing | `Global\<PREFIX>_*`, section 5 |
| 5 | state / logs / locks | namespacing | in-repo only, section 3 |
| 6 | credentials | namespacing | per-repo key file, section 3 |
| 7 | **the AI account** | **NOT namespaceable** | **shared token bucket, section 4** |

Surface 7 is why this document exists. Three loops fanning out to N agents each
is 3N concurrent calls against **one account with one rate-limit pool**. No
naming convention can partition a rate limit. It must be *governed*, and the
governor has to be machine-wide, which means it is the single piece of shared
state the three projects genuinely have.

---

## 1. Project identity

Each project declares five values once. Everything else in this document is a
function of them.

```
PREFIX        short uppercase token, unique on the machine    e.g. RC, LW, RM
ROOT          absolute repo path                              e.g. C:\Project
PORT_BLOCK    a contiguous reserved TCP range                 e.g. 8900-8919
TASK_PREFIX   scheduled-task namespace, conventionally PREFIX-
MUTEX_PREFIX  named-mutex namespace, conventionally Global\PREFIX_
```

**Rule 1.1 - the prefix is assigned once, by a human, and never inferred.** Two
projects independently choosing a prefix from their own names is how you get two
projects called `RC`. Write the assignment down where all three can see it.

**Rule 1.2 - no project reads another project's tree.** Not for facts, not for
config, not for "just checking". Cross-project information moves through the
channel in section 7, in prose, quoted. This rule is what keeps the three
projects independently clonable, and it is the rule most often broken by an
agent trying to be helpful.

---

## 2. Ports - disjoint blocks, and a registry that is CHECKED

### The blocks

Each project reserves a **contiguous block wider than its current use**. Width is
the point: a new service can be added to any project without re-auditing the
other two.

Example allocation from the live build:

```
8770-8789   project A     (5 named, 2 actually bound)
8860-8879   subsystem     (reserved ahead of a migration)
8888-8895   project B     (7 bound)
8900-8919   project C     (1 named, bound only while a human runs it)
```

### The registry

Each project carries `core/ports.py` (or its idiom's equivalent): one module
naming every port that project binds, with a docstring per constant citing the
file:line that actually binds it.

**Rule 2.1 - never write a port literal at a bind site.** Import the constant. A
literal spelled out at the bind is how a registry silently goes stale.

**Rule 2.2 - the registry must be CHECKED, and the check must not be a
tautology.** A test asserting `ports.DASHBOARD == 8888` passes forever while the
real server moves. The test must **import the binding module and compare**:

```python
def test_dashboard_port_matches_server(self):
    self.assertEqual(ports.DASHBOARD, self._live("dashboard.server", "PORT"))
```

**Rule 2.3 - assert block disjointness in code**, pairwise, with a count
assertion so a silently-dropped block is caught:

```python
self.assertEqual(checked, 6, "expected 6 pairs across 4 blocks")
```

**Rule 2.4 - add an unregistered-server scan.** Walk the source for
port-defining assignments and fail if any port found is absent from the
registry. Rule 2.2 catches "the server moved"; this catches "a NEW server
appeared and nobody told the registry", which is the likelier failure over a
year.

**Rule 2.5 - if a guard greps for foreign port literals, exclude the cross-repo
channel directory and scan by AST, not by regex.** Measured twice: a text scan
over a source file flagged the date `2026-08-01` as a port, and a working-tree
scan reached a sibling's prose note that quoted a foreign port. Prose
legitimately contains four-digit numbers.

### The two audit traps

**Trap 2.A - AUDIT BY SOURCE, NEVER BY NETSTAT.** This inverts the obvious
method and it is the most valuable single line in this section.

- A project whose service is human-launched and idle most of the time shows
  **zero** listening ports on an ordinary day. It reads as portless and the
  collision stays armed.
- A project with ports *reserved for future cycles* shows them as **free**. A
  scan reports "available" about numbers already spoken for.

A reservation is a claim about the future. Only source and the owner's registry
can answer it.

**Trap 2.B - a naive `bind(` grep produces false positives.** One real case: a
function named `_bind(modname, filename)` that is an importlib module loader, not
a socket. Filter, do not count.

### Third-party defaults

**Rule 2.6 - whoever wires a third-party listener passes it an explicit port
from that project's own block**, rather than letting it take its stock default.
Otherwise the stock defaults quietly become a fourth, unowned, undocumented
block that appears in nobody's tree until it collides.

---

## 3. The namespaced surfaces - tasks, state, credentials

**Rule 3.1 - scheduled tasks are `<TASK_PREFIX><Name>`.** No exceptions, and the
prefix goes in the task-registration script so it cannot be forgotten at the
call site.

**Rule 3.2 - all runtime state lives inside the repo.** Health files, locks,
caches, logs, reports. One exception, section 4.

**Rule 3.3 - credentials are per-project files inside the project**, gitignored.
Never a shared environment variable, never a machine-wide file. Three projects
sharing one key file means rotating it is a three-way flag day, and no project
can be moved to another machine alone.

**Rule 3.4 - logs are per-project and per-day.** When three loops run
concurrently, a merged log is unreadable and an interleaved one is misleading.

---

## 4. The governor - the one genuinely shared thing

### What it is

A **token bucket of exclusive-create lockfiles in one machine-wide directory**,
bounding total concurrent AI executor calls across all three projects.

```
acquire   O_CREAT|O_EXCL on <root>/<i>.lock for i in range(max_slots);
          first success wins. The file carries {pid, project, run_id, ts}.
reap      a lock whose ts is older than stale_after OR whose pid is not alive
          is reclaimed. FAIL-OPEN by design.
release   unlink, always, in a finally.
wait      JITTERED backoff.
```

### The five rules that make it work

**Rule 4.1 - the governor file is BYTE-IDENTICAL across all three repos, and
that is a contract, not a coincidence.** The loops coordinate *through this
file's on-disk protocol*. A divergence is not a merge conflict anyone notices;
it is a silent concurrency bug. Pin it: each repo carries a SHA256 constant and
a test asserting its own copy matches.

- **Re-pinning is a JOINT act.** Never regenerate the digest from local disk.
  All trees hashing equal IS the acceptance, not a note claiming it.
- The file must reference **no project**. Every project-specific value arrives
  as an argument. This is what makes byte-identity possible at all.

**Rule 4.2 - one N, written in all three configs, agreed out of band.** There is
no negotiation protocol and there should not be. If one project sets 3 while the
others set 2, the bucket is 3 wide whenever that project acquires first. **If
the N values differ, the governor is theater.** Add a test in each repo that
reads its own config value and fails if it is not the agreed constant, so drift
is loud.

*Starting value:* one slot per project. For three projects, N=3. Below that, one
project is always blocked and the throttle becomes a queue with unbounded
latency. Lower it together if the account rate-limits, and record the
measurement.

**Rule 4.2a - the equality guard makes an atomic change IMPOSSIBLE, so design
the transition, not just the steady state.** Learned the hard way on 2026-08-01,
by two projects independently, in the same hour.

Both guards compare against a sibling's working tree on disk: one asserts
set-equality of the declared values, the other asserts a subset relation. Either
shape means **whoever changes the number FIRST goes red until the others
follow.** There is no ordering in which nobody is red - "change it in the same
round" is not implementable, only approximable.

That is not an argument against the guard, which is the only thing standing
between three configs and a governor that is theatre. It is an argument that a
guard asserting "all participants agree" needs a way to express "a coordinated
change is in flight". Options, none of them free:

- read the agreed value from ONE shared file rather than from each sibling's
  config, moving the coordination into a single write;
- let a config declare a PENDING value alongside the current one, and accept
  either during a change window;
- or accept that one party is red for minutes, and **write down who goes first
  and why** before anyone edits.

The third is what the three projects actually did, and the deciding rule was
sound: **whoever is red should be the party not currently shipping.** An idle
project can afford a red suite; one landing commits through a gate cannot.

Whatever you pick, record the ordering in the config note next to the number, so
the next session reads a temporary disagreement as a planned transition rather
than as drift to be "fixed" by raising one side alone.

**Rule 4.3 - hold the slot ONLY around the executor call.** Never around git,
never around a merge, never around an adjudication call. A long merge in one
project must not starve another.

**Rule 4.4 - reaping is FAIL-OPEN.** A crashed holder must never deadlock a
sibling. A lock whose pid is dead, or whose timestamp is well past any plausible
cycle deadline, is reclaimed. Corrupt or half-written locks fall back to mtime so
they cannot wedge the bucket forever.

**Rule 4.5 - a slot timeout is a FAILED CYCLE, never permission to proceed
unslotted.** The one line that makes the governor real rather than advisory.

### Two implementation details that are not optional

- **Jitter the backoff.** Without it two waiters lockstep into each other and
  repeatedly collide on the same slot index.
- **A pid you cannot query counts as ALIVE.** One project may run as a scheduled
  task and another interactively, under different owners. Treating an
  unqueryable pid as dead double-books the slot. Prefer waiting to double-booking.

---

## 5. Exclusive resources - the mutex namespace

Slots bound *how many* run. Some resources need *exactly one*: a GPU, a metered
vendor account, a hardware device.

**Rule 5.1 - named mutexes are `Global\<PREFIX>_<RESOURCE>`.** Reserve the
namespace at bring-up even if the project holds no mutex yet. Reserving a name
costs nothing; discovering a collision costs a run.

**Rule 5.2 - acquire in the TOOL that touches the resource, not in the loop**, so
a manual run outside the loop is protected too.

**Rule 5.3 - an abandoned mutex is ACQUIRED, with a warning.** If a holder dies
without releasing, the next waiter gets `WAIT_ABANDONED`. Treat it as acquired
and log loudly: the previous holder's work may be half-done, but refusing to
proceed lets one crashed process deadlock the others indefinitely.

**Rule 5.4 - a fail-open path must emit a DISTINCT marker, never the ACQUIRED
one.** This is subtle and it was a real bug. If the fail-open branch logs
`ACQUIRED` unconditionally, it opens a window that the (correctly gated)
`RELEASED` never closes. A window-pairing parser then drops it silently - making
the one case where the mutex did *not* serialize the one case invisible to the
overlap check. An unserialized call passes green.

**Rule 5.5 - on a platform with no such primitive, degrade to a no-op that still
LOGS the unserialized marker.** A silent yield makes every serialization test
pass vacuously on that platform and leaves no trace in the log a reviewer reads.
Green then proves nothing.

---

## 6. The lane lock and the launcher

### 6.1 Two modules, never one

Split **who may run** from **what runs**:

- the lock is pure state management and **starts no process**, so it is fully
  testable without spawning anything;
- the launcher spawns and **decides nothing**.

### 6.2 The lock has THREE states

**Rule 6.1 - FREE / RUNNING / RECLAIMABLE, decided by PROBING the pid, never by
stat-ing the file.**

A lock file whose pid is dead is indistinguishable from a live one by file
inspection. Measured: a live lock carried `{"pid": 9380, ...}` and pid 9380 was
gone, so every reader that treated existence as RUNNING reported a loop that was
not there. **RECLAIMABLE must never render as RUNNING.**

**Rule 6.2 - reads do not write.** Auto-clearing a stale lock inside the
dashboard poll path makes a rendering pass mutate the control plane, and two
pollers race each other into a reclaim. Clearing happens only inside acquire.

**Rule 6.3 - refuse, do not queue.** A fire against a held lane returns a refusal
and mutates nothing. A queue turns one click into a run that starts minutes later
against a tree that has moved on.

**Rule 6.4 - the pid in the lock is the WORKER's, not the claimer's.** A fire
from a long-lived server process must re-point the lock as soon as it has a real
pid. Otherwise the state function probes a process that is always alive and the
lane reads RUNNING forever after its worker died.

**Rule 6.5 - any spawn failure RELEASES the lane.** A lock with no process behind
it is strictly worse than no lock at all.

### 6.3 Worktree-mandatory, enforced twice

**Rule 6.6 - a headless worker runs against a git worktree, never the main
tree.** Two writers in one working directory is the concurrent-index corruption
class and it is not recoverable by retrying.

**Rule 6.7 - enforce it at acquire AND at spawn.** The two checks happen at
different moments and a path can be handed in between them.

**Rule 6.8 - worktrees live OUTSIDE the repo.** Inside, they land in the very
tree the worker is forbidden to touch, and every repo-wide guard then scans them.
Root-scanning guards are worktree-blind.

**Rule 6.9 - the "where is the main tree" resolver must handle being imported
FROM a worktree.** The naive `parents[2]` **inverts the guard**: it returns the
worktree, so the check rejects the worktree a lane legitimately runs in and
ACCEPTS the main tree it must never touch. Detection needs no subprocess: in a
main tree `.git` is a DIRECTORY; in a worktree it is a FILE holding
`gitdir: <main>/.git/worktrees/<name>`.

**Rule 6.10 - detect the violation, do not only prevent it.** An agent has
written into a main tree while `git worktree list` showed no second tree. The
only check that catches a writer which bypassed the path guards is a
before/after `git -C <main> status --porcelain`, with any undeclared delta
failing the run.

### 6.4 Two measured spawn facts

**Rule 6.11 - `CREATE_NO_WINDOW` alone. Never `DETACHED_PROCESS`.** Measured,
three spawns of one script differing only in flags:

```
CREATE_NO_WINDOW | DETACHED_PROCESS -> pid issued, rc=0, log NEVER written
CREATE_NO_WINDOW                    -> pid issued, rc=0, log written
DETACHED_PROCESS                    -> pid issued, rc=0, log NEVER written
```

`powershell.exe` cannot initialise its host without a console, so it exits
immediately and silently: **a success exit code, a real pid, and no work done.**
The lane flips RUNNING then RECLAIMABLE on schedule and produces nothing, which
is the worst shape a failure can take.

**Rule 6.12 - the prompt goes on stdin, never on the command line**, and stderr
is folded into the log. Command-line quoting of a multi-kilobyte prompt is a
failure class you do not need to meet, and a native warning on stderr can kill a
worker that treats stderr as fatal.

### 6.5 The prompt file

**Rule 6.13 - the worker's prompt must be a TRACKED file.** A worktree is a fresh
checkout and **does not carry gitignored files**. A lane pointed at a gitignored
prompt directory starts with an empty prompt and the worker invents its own
scope. Test it: every lane resolves to a path that exists AND is tracked
(`git ls-files --error-unmatch`).

**Rule 6.14 - the spawn function is an injectable seam.** The default really does
start a process, and no test should. Build the seam when you build the launcher,
not later.

---

## 7. The cross-project channel

**Rule 7.1 - each repo carries a gitignored inbox directory of the same name.
You WRITE into the sibling's; you READ your own.** No shared directory, no
message bus, no database.

```
<A>/moon_sync_inbox/    <- B and C write here; A reads it
<B>/moon_sync_inbox/    <- A and C write here; B reads it
<C>/moon_sync_inbox/    <- A and B write here; C reads it
```

**Rule 7.2 - one file per message, named
`YYYY-MM-DD-HHMM-from-<PREFIX>-<topic>.md`.** Append-only in effect: never edit a
delivered note.

**Rule 7.3 - a note states what was VERIFIED and how, not what is recalled.** The
receiving project cannot check your claim without breaking rule 1.2, so the note
carries the evidence: file:line citations, command output, test counts.

**Rule 7.4 - the inbox is excluded from every source-scanning guard**, not merely
gitignored. Measured: one project's guard walked the working tree rather than
tracked files, so gitignoring the inbox left it fully in scope, and a sibling's
note quoting foreign port numbers would have failed the guard on content that
project neither owns nor ships. Latent for weeks, and it would have fired on a
day nobody connected it to the exchange.

**Rule 7.5 - do not invent a second channel.** Two of the three projects
independently invented a different channel on the same day before finding this
one. If a channel exists, use it.

---

## 8. The Desktop hand-off

Each project ends a session by writing its next-session bootstrap prompt to one
file on the shared Desktop:

```
C:\Users\<user>\Desktop\<PREFIX>-NEXT-SESSION.txt
```

Overwritten each time, never appended. The next session clears context and
re-feeds that file verbatim. **One artifact; a fresh context reads nothing else
to resume.**

**Rule 8.1 - the CONSUMER enforces the prefix, it does not merely use it.** If
the write target comes from a config or an on-disk intent document, validate it:
anything that is not a plain relative path under the user profile falls back to
the default - absolute paths, drive letters, `..` segments, empty and non-string
values - **and a filename not carrying this project's prefix falls back too.**

A project must not be talkable into overwriting a sibling's hand-off by a stale
or doctored document. **Cross-project writes are a deliberate act, never a
fallback.**

**Rule 8.2 - lifting this to a new project is one constant**, `REPO_PREFIX`.
Everything else is generic. Test it with three red assertions: a sibling's
filename, an absolute path, and a `..` path each fall back to the default.

---

## 9. One AI vendor, self-adjudicating

**Decided 2026-08-01 after running the two-vendor design for two months.**

The loop directs, executes and audits with **the same vendor**. The read-only
guarantee for the directing and auditing calls comes from the CLI's own
plan/read-only mode (`--permission-mode plan`), not from vendor diversity.

**Rule 9.1 - do not add a second AI vendor for adjudication.** It was tried. The
adjudication benefit did not materialize and the overhead was concrete and
ongoing:

- quota and status checks on a second account;
- exhaustion-signature matching against stderr strings, to tell "out of credit"
  from "transient overload";
- a **sticky failover** that could misread a parallel-call `RESOURCE_EXHAUSTED`
  as genuine credit exhaustion and swap the backend **for the rest of the run**;
- a metered-spend ceiling that governed only one of the two vendors, and so had
  to be excluded from the other's accounting to avoid stopping a free run;
- a CLI stdin size limit that every call had to be capped against;
- a second retry ladder with its own outage history and its own model-fallback
  chain.

None of that is adjudication. All of it is vendor management.

**Rule 9.2 - "self-adjudicating" is a real requirement, and it is about
INDEPENDENCE, not about vendor identity.** Keep these, which are what actually
catch errors:

- the agent that produced a thing never grades it;
- the grading pass is adversarial - it tries to REFUTE, and defaults to refuted
  when uncertain;
- agreement between two agents is not evidence.

**Rule 9.3 - flip by config, decommission separately.** Changing the default
backend is one line and instantly reversible. Deleting the second vendor is a
sweep across retry ladders, spend accounting, a scheduled task, and possibly a
byte-identical shared file whose mutex names cannot be edited unilaterally.
Do the flip; file the sweep. Leaving a reachable-but-unselected backend in place
is what keeps the flip reversible.

**Rule 9.4 - if a shared file names the retired vendor's mutex, changing it is a
JOINT act** under rule 4.1. One project cannot edit it alone, and the cost of
leaving a now-unused constant in place is zero.

---

## 10. Hooks - what does NOT survive headless

**This is the single most dangerous gap in a headless design, because the guard
appears to be present and does nothing. The SYMPTOM below is measured. The CAUSE
stated in the first version of this document was wrong, and the correction
matters more than the original finding.**

**What was observed (Legion, 2026-07-26, CLI 2.1.205):** a run invoked as
`claude -p --permission-mode bypassPermissions` did not fire the agent's own
PreToolUse hooks - a banned glyph committed straight through the agent hook while
the git hook blocked it. That observation stands.

**What it was blamed on, wrongly: headlessness.** A third project (Peer-VIP) ran a
three-arm probe on CLI 2.1.220 and reported that PreToolUse hooks DO fire under
both `--permission-mode bypassPermissions` and `--dangerously-skip-permissions`
when the process runs with its **cwd inside the project**, and do NOT fire when
cwd is elsewhere - the arm that wrote into the project by absolute path from an
outside cwd produced no hook at all. Their reference runner passed no cwd and its
scheduled task set no WorkingDirectory, which reproduces the reported symptom by
a mechanism that has nothing to do with headlessness.

**The variable is settings DISCOVERY, not headlessness.** Hooks come from the
project's `.claude/settings.json`, which is found relative to cwd. No cwd in the
project means no settings file, means no hooks exist to fire.

**Status of this correction, stated honestly rather than rounded up.** It is NOT
independently reproduced on Legion: the headless CLI there is not authenticated
(`Not logged in`), so the probe could not run, and there are two uncontrolled
variables between the machines - cwd AND CLI version (2.1.205 vs 2.1.220). Treat
the cause as strongly-evidenced-but-unconfirmed-here.

**What IS verified on Legion, and it is the consequential half.** RC's
`.claude/` directory is gitignored (`.gitignore:116`) and untracked, so a git
worktree does not carry it. Checked directly: the main tree has
`.claude/settings.json`; both live lane worktrees do NOT. **So every lane worker
runs with zero agent hooks regardless of which cause is right** - and the reason
is settings discovery, exactly as Peer describes, not headlessness. This is the
same fresh-checkout-has-no-wiring trap as Rule 6.13, applied to hooks instead of
prompts.

**Why the corrected cause is better news.** "Headless cannot have hooks" is a
hard limit you design around. "Hooks follow cwd and a gitignored settings file"
is a bug you FIX: pass cwd explicitly, set WorkingDirectory on the scheduled
task, and materialize the settings file into the worktree. The practical floor
below is unchanged either way, so a design that obeys it is safe under both
explanations - but only one of them is worth trying to repair.

**Rule 10.1 - git hooks are the authoritative gate. Agent hooks are a fast
in-session signal only, and their presence in the main tree says nothing about
whether a worker has them.**

**Rule 10.1a - pass cwd explicitly to every spawned worker, and set
WorkingDirectory on every scheduled task that launches one.** After this
correction, cwd is load-bearing: it is the difference between a worker the
guards can see and one they cannot.

**Rule 10.1b - if a worker runs in a worktree, materialize the gitignored agent
config into it, or accept that it has no agent hooks and say so out loud.**
Silently inheriting nothing is what made this look like a headless limitation for
a month.

**Rule 10.2 - a fresh clone has NO hooks.** `core.hooksPath` is LOCAL config and
is not cloned. A tracked hooks directory runs zero hooks until someone wires it.
First action in any fresh clone: run the install script.

**Rule 10.3 - worktrees INHERIT `core.hooksPath`; clones do not.** Verified: a
worktree returns the main tree's absolute hooks path, because a worktree shares
the main repo's config. Since the lane design is worktree-based, the unguarded
window applies to clones only. Confirm it on your own machine with one probe
rather than trusting this line - it depends on the configured path being
absolute.

**Rule 10.4 - the loop REFUSES TO START when the real gate is inert.** Preflight:
read `core.hooksPath`, confirm the directory and the hook files exist, exit
non-zero before spawning anything if not.

**Rule 10.5 - never treat a hook's PRESENCE as proof it fires.** The only valid
test is end-to-end: stage a violation, attempt a real commit, assert HEAD is
unchanged.

**Rule 10.6 - a per-edit full-suite hook does not survive fan-out, and the fix is
a DEFAULT, not an exception.** Make the post-edit hook compile-only by default
and gate the full suite behind an env var for a deliberate batch. The arithmetic:
a 19-second suite firing on every edit costs one agent 380s over 20 files, and
eight parallel agents pay that each while competing for cores - so wall-clock is
worse than linear. The real defect is subtler: **at fan-out width the suite tests
a tree that no single agent produced**, so it is not slow-but-correct, it is
slow-and-meaningless. Run the suite once per slice, where the slice claims done.

**Rule 10.7 - replace a SessionStart state injection with a probe IN the
prompt.** A worker whose run lasts an hour is better served running the probe
itself than receiving a snapshot taken before it started.

---

## 11. The control plane (per project, one each)

**Rule 11.1 - its own process, its own port, its own scheduled task.** NOT a
route on the application's web server. An app restart, a crash, or a hot-reload
must never take the control plane down with it. A control plane that dies with
the thing it controls is not a control plane.

**Rule 11.2 - explicit narrow bind, never a dual-stack wildcard.** One socket per
address in an explicit list. A control plane with process-killing POST routes
must not be reachable from the whole LAN by default.

**Rule 11.3 - bind failure exits NON-ZERO.** Logging a warning and returning
leaves the process up and the control plane silently absent, which is the worst
shape a failure can take. Exit, and let the task's restart policy engage and
record it.

**Rule 11.4 - no hot-reload watcher.** A control plane must not restart itself
because an unrelated file changed.

**Rule 11.5 - it renders the locks and the logs, and holds no state of its own.**
If the dashboard and the lock disagree, the lock is right.

**Rule 11.6 - import shared handlers, never fork them.** The temptation to copy a
handler "just for the control plane" produces two copies that drift.

---

## 12. Bring-up checklist for a new machine

In order. Steps 1-4 are the contract; 5-9 are one project's build, repeated per
project.

1. **Assign the three prefixes.** One human, one document, once.
2. **Assign the three port blocks.** Wider than current use. Write them where all
   three can see them.
3. **Agree N** for the shared bucket, and the bucket's directory path. Write the
   same N in all three configs.
4. **Create the three inbox directories**, gitignore them, and exclude them from
   every source-scanning guard.
5. **Per project: preflight.** End-to-end hook test (rule 10.5) and the
   `core.hooksPath` probe (rule 10.3). If a violation commits through, stop.
6. **Per project: the registry + its checked tests** (section 2).
7. **Per project: vendor the governor byte-identical, pin it, and tell the other
   two the same day** (rule 4.1). Adding a participant to a live bucket changes
   the others' behaviour.
8. **Per project: the lock, then the launcher, then the control plane**
   (sections 6, 11). Failing test first, each time.
9. **Per project: the tracked prompt files** (rule 6.13) and the Desktop hand-off
   resolver (section 8).

**Do not skip step 5.** It is the step that looks like paperwork and is the only
one that tells you whether any of the others are real.

---

## 13. The measured traps, collected

Every line here cost a real debugging session. They are the reason this document
is worth more than its rules.

| # | trap | why it hides |
|---|---|---|
| 1 | `DETACHED_PROCESS` yields a silent no-op worker | real pid, exit 0, zero work, correct-looking state transitions |
| 2 | A dead pid in a lockfile reads as RUNNING | file inspection cannot tell live from dead |
| 3 | The main-tree resolver INVERTS when imported from a worktree | the guard rejects the safe path and accepts the forbidden one |
| 4 | A gitignored prompt path is empty in a worktree | the worker starts with no prompt and invents scope |
| 5 | Agent hooks silently absent in a spawned worker (cause: cwd / gitignored settings, NOT headlessness - see section 10) | the hook is configured, present in the main tree, and never loaded by the worker |
| 6 | A netstat audit finds zero ports for an idle service | the project reads as portless |
| 7 | Reserved-but-unbound ports scan as free | a reservation is a claim about the future |
| 8 | A text scan for port literals flags dates | four-digit years are everywhere in prose |
| 9 | A working-tree guard reaches the sibling inbox | gitignore does not exclude it from an rglob |
| 10 | Unconditional `ACQUIRED` on a fail-open path | the unserialized case becomes the invisible case |
| 11 | A silent no-op mutex on an unsupported platform | every serialization test passes vacuously |
| 12 | Mismatched N across configs | the governor is theater and looks identical from inside |
| 13 | Size-preserving mutation leaves a stale `.pyc` | a restored tree reports failures; worse, a vacuous guard can report GREEN |
| 14 | A per-edit full suite at fan-out width | tests a tree no agent produced |
| 15 | An agent writes to the main tree with no second worktree listed | prevention passed; only a before/after diff catches it |

**Trap 13 deserves its own line of method:** when proving a guard non-vacuous by
mutation, **clear the bytecode cache between mutate and restore**, or use a
size-changing mutation. CPython's mtime+size validity check accepts a mutated
cache when the mutation preserves size and the restore lands in the same second.
The dangerous direction is the inverse of the one you notice: a stale cache
reporting GREEN makes a vacuous guard look proven.

---

## 14. What is NOT claimed here

- **Three-way concurrency has not been measured.** Two loops have run
  concurrently since 2026-07-26. The third joins next. Every three-way number in
  this document, including N=3, is reasoning.
- **This is Windows-shaped.** The named-mutex namespace, `CREATE_NO_WINDOW`, and
  `taskkill /F /PID` are all Windows specifics. The *structure* ports cleanly;
  those four sections do not.
- **The governor bounds calls, not tokens.** It cannot see a rate limit; it
  approximates one. If the account limits by tokens, N is a proxy and needs
  measurement.
