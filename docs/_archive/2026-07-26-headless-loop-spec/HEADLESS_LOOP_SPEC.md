# Headless self-adjudicating loop - spec

> **ARCHIVED 2026-08-16. Do not read this as current.** Two reasons, both measured:
> it was a TRUE ORPHAN (zero references anywhere in the tracked tree or in `.claude/`),
> and it describes a "Director / auditor (Gemini)" as a live participant. That vendor was
> retired 2026-08-01 - Claude is now director, executor, adjudicator and auditor, and the
> loop is single-vendor. The AHK GUI bridge it treats as the current fallback has also
> moved on. Kept for the design record only. Live loop docs: `docs/ORCHESTRATION_PLAN.md`
> and `ops/loop/`.


Status date: 2026-07-26. Supersedes the AHK/GUI executor path for new work; the
GUI bridge stays as a fallback until the headless lane has a proven run.

## 1. Where the GUI dependency actually is

The loop already has three participants and **only one of them needs a GUI**:

| Participant | Today | Headless? |
|---|---|---|
| Director / auditor (Gemini) | `gemini` CLI, `--approval-mode plan` | **already headless** |
| Adjudicator fallback (Claude) | `claude.cmd -p --permission-mode plan`, body on stdin (`config.json` -> `claude_adjudicator`) | **already headless** |
| **Executor (Claude)** | `ops/loop/claude_gui_bridge.ahk` types directives into a resolved Claude Desktop `hwnd` | **NO - this is the whole problem** |

So this is not a rewrite. It is replacing one component.

**Why the executor was GUI-bound:** it needs full write authority and a
long-lived conversation, which the read-only `-p --permission-mode plan`
adjudicator path deliberately does not grant.

**That constraint is now obsolete.** Claude Code CLI **2.1.205** (verified
installed at `C:\Users\Administrator\AppData\Roaming\npm\claude.cmd`) exposes
every flag the executor needs:

| Flag | Why the executor needs it |
|---|---|
| `-p, --print` | non-interactive, no TUI |
| `--permission-mode bypassPermissions` | full write authority without a human at a keyboard |
| `--session-id <uuid>` | **deterministic session identity - this is what makes concurrency safe** |
| `-r, --resume [id]` | continue the same conversation across cycles |
| `--output-format stream-json` | machine-readable result + a real exit code, instead of scraping a transcript |
| `--append-system-prompt` | inject the standing directive without retyping it |
| `--add-dir`, `--model`, `--fallback-model`, `--agents`, `--settings` | per-project scoping |

### NOT used: `--max-budget-usd` (operator decision, 2026-07-26)

The executor deliberately passes NO dollar cap, and `cycle_budget_usd` is absent from
every `ops/loop/config*.json`. The account is a **Claude Code Max 20x subscription**, so
the CLI's `total_cost_usd` is a notional API-equivalent price, not money being billed. A
cap set against that number truncates a cycle mid-work for no real saving.

Measured on the F1 phase-6 gate run: the cycle reported `$22.01` against a `$25` cap and
a slightly larger scope would have been cut off, while nothing was actually spent per
call. Contrast the P5 doc-append cycles at `$0.56` and `$0.66` - the figure tracks
workload size, which is why it is still recorded.

Two rails survive and mean different things:

- `ceiling_usd` rails the ADJUDICATOR (gemini). That is metered money and a real cap.
- `cycle_deadline_sec` rails the executor. **Time is the executor's only real budget**,
  because it bounds a runaway cycle without pricing the work.

`executor_usd` in `control/budget.json` stays as a relative effort signal. Read it as
workload size, never as spend, and never gate on it. The transcript-scraped
`claude_usd_info` is weaker still - see the meter caveats in section 4.

## 2. What the GUI path costs today

These are the failure modes the headless lane removes outright, all of them
already recorded in this repo:

- **Foreground focus is a global singleton.** `WinActivate` steals it. Two loops
  typing on one desktop interleave keystrokes into each other's window - which
  is the concurrency question this spec exists to answer.
- **One `claude.exe` owns MANY top-level windows**, so `ahk_pid` targeting can
  land on the wrong project. RC fixed this with EnumWindows -> `target_hwnd.txt`
  (`1a310c04`, ported from Sibling-A `a703ac1`) - a mitigation, not a cure.
- **Keystroke timing is load-bearing.** After a `/clear` the bridge must sleep
  `CLEAR_PAUSE` 5000ms or the TUI reset swallows input (`b8990105`).
- **The operator cannot use their own machine** while a run is typing.
- **No exit code.** Success is inferred from a transcript, not returned.

## 3. Target architecture

```
loop_controller.py  (brain, unchanged)
      |
      +-- director / auditor  ->  gemini CLI            (headless today)
      |
      +-- executor            ->  claude.cmd -p ...     (NEW - replaces AHK)
                                    --session-id <uuid-v5(project)>
                                    --permission-mode bypassPermissions
                                    --output-format stream-json
```

One executor invocation per cycle. The directive goes on **stdin**, matching the
existing `claude_adjudicator` convention, so nothing has to be escaped for a
command line or a keyboard.

### Session continuity

Cycle 1 runs with `--session-id <uuid>`. Cycles 2..N run with
`--resume <uuid>`. `clear_each_cycle: true` becomes "mint a NEW uuid for the
next cycle" rather than typing `/clear` - which is strictly better, because the
5-second TUI-reset race disappears and each cycle's context is provably fresh.

**Derive the uuid deterministically, never randomly:**

```python
import uuid
SESSION_NS = uuid.UUID("6f2a1c3e-0b7d-4f9a-9c21-8e5d3a7b4c10")  # fixed for this loop
sid = uuid.uuid5(SESSION_NS, f"{project_root}|{run_id}|{cycle}")
```

A deterministic id means a crashed controller can resume the exact cycle it lost
instead of orphaning it, and two projects can never collide.

## 4. CONCURRENCY WITH A SECOND PROJECT (Sibling-A)

This is the requirement that shapes the design, so it is spelled out per shared
resource rather than asserted.

### 4a. What stops being shared

**Foreground focus** - the entire contention mechanism - is gone. Headless
`claude -p` never touches the desktop. Two, five, or ten projects can run
simultaneously with no interleaving, and the operator can use the machine
throughout. This alone resolves the question that prompted the spec.

### 4b. What is STILL shared, and must be handled

| Shared resource | Risk | Required handling |
|---|---|---|
| `~/.claude` config + plugin cache | concurrent writes | Read-mostly in practice. Pin each project with `--settings <project>/.claude/settings.json` so neither mutates the other's config. |
| Session transcripts | cross-project resume | Already partitioned per project (`~/.claude/projects/<slug>`), and uuid-v5 keys make collision impossible. Safe. |
| **Anthropic rate / usage limits** | **the real one - two loops burn one budget** | See 4c. |
| Git | none | Separate repos. No action. |
| Scheduled tasks, ports, `ops/runtime` | none | Per-project. No action. |
| CPU / RAM | oversubscription | Cap concurrent executors machine-wide (4d). |

### 4c. Rate limits are the genuine shared resource

Both loops authenticate as the same account, so they draw on one budget. Without
coordination, two loops hitting a limit simultaneously both back off, both
retry, and both fail again - the classic thundering herd.

**Required: a machine-wide token file, not per-project state.**

```
C:\ProgramData\claude-loop\rate.json     { "next_allowed_utc": "...", "holder": "<project>" }
C:\ProgramData\claude-loop\slots.lock    machine-wide concurrent-executor semaphore
```

Rules:
1. Before spawning an executor, take a slot (4d). No slot -> wait, do not spawn.
2. On a 429 / usage-limit signature, write `next_allowed_utc` with jitter. Every
   project reads it and honours it, so one project's backoff protects the other.
3. Jitter each project's cycle start by a per-project offset (hash the project
   name) so loops do not align on the same second.

The existing failover logic is the model to copy: the controller already detects
credit and quota exhaustion signatures (`quota`, `exhausted`, `insufficient
credit`, `429`, `RESOURCE_EXHAUSTED`) and swaps adjudicator backend. Reuse that
same detector for the shared rate gate rather than writing a second one.

### 4d. Single-instance per project, bounded across projects

Two locks, and the distinction matters:

- **Per-project lock** - `<project>/ops/loop/control/loop.lock`, holding pid +
  start time. Prevents a second RC loop. Must be **stale-tolerant**: if the pid
  is dead, reclaim it rather than deadlocking forever.
- **Machine-wide slot semaphore** - `C:\ProgramData\claude-loop\slots.lock`,
  default **2** concurrent executors. This is the knob that lets RC and LW run
  together while stopping a third and fourth from saturating the box.

Use `msvcrt.locking` or an atomic `O_EXCL` create; do NOT hand-roll
check-then-write, which races precisely when two loops start together - the case
this exists for.

## 5. Concrete executor call

```python
cmd = [
    CLAUDE_CMD, "-p",
    "--session-id", str(sid),            # or: "--resume", str(prev_sid)
    "--permission-mode", "bypassPermissions",
    "--output-format", "stream-json",
    "--include-partial-messages",        # progress without polling a transcript
    "--model", "opus",
    "--fallback-model", "sonnet",        # survive an opus capacity blip
    "--add-dir", str(project_root),
    "--settings", str(project_root / ".claude" / "settings.json"),
]
proc = subprocess.run(
    cmd, input=directive_text, capture_output=True, text=True,
    cwd=str(project_root), timeout=cycle_deadline_sec,
    creationflags=(0x08000000 if os.name == "nt" else 0),   # CREATE_NO_WINDOW
)
```

`creationflags` is **not optional**: the controller runs under a scheduled task,
and an unguarded console child flashes a window on the operator's desktop -
which would reintroduce, through the back door, exactly the desktop intrusion
this spec removes (`b2b6a4f3`, and the four sites fixed in `ops/rc_supervisor.py`
on 2026-07-26).

## 6. Migration, in order

1. **Add the lane, do not remove the old one.** New `executor_mode` config key:
   `"gui"` (current default) or `"headless"`. Both paths present.
2. **Dry-run first** with the existing `config.dry.json` and
   `--permission-mode plan`, so the lane is exercised with zero write risk.
3. **One live cycle** on a trivially-verifiable unit. Acceptance: a commit lands,
   CI goes green, and the controller saw a real exit code.
4. **Concurrency proof - this is the acceptance test for the actual requirement.**
   Run RC and Sibling-A loops simultaneously for >= 3 cycles each. Assert:
   both commit to their own repo, neither session id appears in the other's
   transcript dir, the slot semaphore is respected, and the operator can use the
   desktop uninterrupted throughout.
5. **Flip the default** to `headless` once step 4 passes twice.
6. **Retire the AHK bridge** only after that. Keep `claude_gui_bridge.ahk` and
   `target_hwnd.txt` in-tree, marked legacy, until the headless lane has a week
   of clean runs - the GUI path is proven and the headless one is not yet.

## 7. Open questions - answer before building

- ~~Does `bypassPermissions` respect the repo's PreToolUse hooks?~~
  **ANSWERED 2026-07-26 - NO. See section 8; this is now a P0 on the migration,
  not an open question.**
- **What is the usage-limit signature in `stream-json`?** The existing detector
  reads stderr text. Confirm the shape in JSON output rather than porting a
  regex that silently never matches.
- **Does a resumed session inherit `--append-system-prompt`?** If not, the
  standing directive must be re-sent each cycle.
- **Per-project account isolation** is NOT available today (one account, one
  budget). If the two loops routinely starve each other, that is an
  account-level decision for the operator, not something this design can fix.


## 8. MEASURED: the headless executor does NOT inherit the PreToolUse gate

This was section 7's load-bearing open question. It is now measured, and the
answer changes the migration order.

### The experiment

1. **Control.** Staged a file containing a U+2014 em-dash and invoked
   `tools/precommit_gate.py` directly on a synthetic Bash/`git commit` payload.
   Result: `precommit_gate BLOCKED commit - banned glyph: em-dash`, **exit 2**.
   The gate works.
2. **Test.** Nested `claude -p --permission-mode bypassPermissions --model sonnet`
   with `cwd` = repo root, instructed to run `git commit`.
   Result: **the commit LANDED, em-dash and all.** (Reset immediately; the tree
   returned to `95412016` and nothing was pushed.)

### The discriminator, because the output is misleading

The run printed `Running Share/ mirror sync (precommit-gated)...`, which reads
like the gate firing. It is not. That line comes from **`.git/hooks/pre-commit`**
- a GIT hook, which runs no matter what Claude does.
`grep -c precommit_gate .git/hooks/pre-commit` returns **0**.

**So: git hooks RAN, Claude PreToolUse hooks did NOT.** Anyone re-running this
who stops at the console output will draw the opposite conclusion.

### What is NOT yet isolated - do not overstate the finding

This does not separate "`bypassPermissions` skips hooks" from "headless `-p`
does not load project hooks at all". An isolated temp-directory attempt was
**invalid and discarded**: the settings file never loaded there in ANY permission
mode, so the hook could not have fired regardless - a test that cannot fail
proves nothing.

**The actionable conclusion is robust to either cause: the SDK executor does not
inherit the repo's PreToolUse gate.**

### Consequence

`bypassPermissions` is not merely an authority grant. It is a **silent removal of
the repository's own guard**, under exactly the conditions where it matters most:
unattended, no window, no operator watching. The banned-glyph and net-new-ruff
backstop is simply absent.

### Mitigation - proven by the same experiment

**Move the authoritative gate into the git pre-commit hook.** Git hooks
demonstrably survive `bypassPermissions`; that is precisely what the Share-sync
line proves. A git-level gate is channel-independent: AHK, SDK, a human at a
terminal, and CI all get it. Keep the PreToolUse copy for the fast in-session
signal, but it must stop being the only line of defence.

### THE TRAP IN THAT MITIGATION - `.git/hooks` is NOT version controlled

Dropping the gate into `.git/hooks/pre-commit` does not propagate to a fresh
clone, to another machine, or to a sibling project. This repo already has the
correct pattern and is **not currently using it**:

  * `.githooks/` is TRACKED and holds `pre-commit` + `commit-msg`.
  * `scripts/install_hooks.py` exists to install them.
  * But `core.hooksPath` resolves to `C:\Riot Commander\.git\hooks` - the
    UNTRACKED copy.

**The two have fully diverged.** The tracked `.githooks/pre-commit` runs
`precommit_pycompile.py`, `gen_archmap.py --check` and
`gen_state_schema.py --check`. The active `.git/hooks/pre-commit` runs only the
Share sync. **Three tracked guards are therefore not running on any commit**, and
that is a pre-existing defect independent of this spec.

**FIXED 2026-07-26 (`a35d3f84`).** All three steps landed together, in this
order, because flipping the pointer at a failing hook would have blocked every
commit in the repo:

  1. Verified the tracked hook's three checks against the live tree FIRST. Two
     FAILED - `gen_archmap --check` and `gen_state_schema --check` - because the
     artifacts had drifted while the hook sat inactive (25 lines of
     ARCHITECTURE.md, 10 of state_schema.js). Regenerated, re-verified all three
     PASSING, and only then continued.
  2. Merged both hook pairs so nothing was lost. `pre-commit` now runs the
     glyph/ruff gate FIRST, then py_compile, archmap, state_schema, and the Share
     sync LAST (it stages files, and Share/src is generated data outside the
     hygiene checks). `commit-msg` now carries BOTH jobs that had been split
     across the two copies - the co-author-trailer strip and the
     Conventional-Commits check.
  3. `scripts/install_hooks.py` rewritten to SET `core.hooksPath` and write no
     hook body at all. It was the root cause: it used to clobber
     `.git/hooks/pre-commit` with a Share-sync-only file.

**Verified by re-running the exact experiment from the top of this section:** a
nested `claude -p --permission-mode bypassPermissions` with a banned em-dash
staged previously COMMITTED IT; it is now **BLOCKED, exit 1, HEAD unchanged**.

`drift_guard.check_git_hooks_path` now fails if the pointer ever moves back.

The original three-step plan, kept for the reasoning:

So the mitigation is a three-step job, not a one-liner:

  1. Reconcile `.githooks/pre-commit` with whatever the active hook legitimately
     needs (the Share sync belongs in the tracked copy).
  2. Add the `precommit_gate.py` invocation to the TRACKED `.githooks/pre-commit`.
  3. Point `core.hooksPath` at `.githooks` and make `scripts/install_hooks.py`
     the documented per-clone step.

Step 3 changes which guards run on EVERY commit in this repo, so it needs its own
verification pass - do not fold it into an unrelated commit.

### Revised migration order

Insert before step 3 of section 6:

  ~~**Step 2b (P0).** Land the git-level gate.~~ **DONE 2026-07-26 (`a35d3f84`) -
  the SDK channel is no longer blocked on it.** Sibling-A needs the same
  fix before its SDK channel ships; the gate is only channel-independent in a
  repo whose core.hooksPath points at tracked hooks.
