# Portable Project Conventions

**A project-agnostic operating doctrine for Claude-run software projects on Windows.**

This document is the transferable half of a working setup: the rules, rituals, agent
topology, doc layout, CI tiers and failure-class knowledge that make a solo operator plus
Claude productive without the operator becoming the bottleneck. It contains no
project-specific content. Drop it into any new repo and it works.

- **Status:** living. Refresh protocol in section 18.
- **Audience:** Claude, at the start of a new project, and the operator reviewing it.
- **Placeholders:** `<PROJECT>` (the project name), `<ROOT>` (its absolute root path),
  `<PY>` (absolute path to the Python interpreter), `<PORT>` (its allocated base port).

---

## 0. The one rule that generates the others

**The operator's attention is the scarcest resource in the system. Everything below
exists to spend less of it.**

Three corollaries, in priority order:

1. **The main session stays usable by the operator at all times.** Heavy work runs in
   subagents and worktrees, not in the main thread. The main thread holds the plan and
   the merge, and stays responsive so the operator can interject on any turn without
   waiting for a long tool chain to unwind.
2. **The operator does the bare minimum, and only what Claude physically cannot do.**
   Claude executes and reports. Operator-only actions are: things requiring their
   physical presence in an external application, financial or account actions, sign-off
   on irreversible or outward-facing changes, and taste calls on product direction.
   Everything else, Claude does.
3. **Rediscovery is the dominant failure mode, not ignorance.** Redoing closed work,
   re-pitching a refuted idea, acting on a stale doc, or writing a finding into the wrong
   file costs more than any bug. Section 4 and section 11 exist for this.

---

## 1. Fresh-clone bootstrap order

A fresh clone has NO local wiring. Git hooks, MCP config, and local settings are all
untracked or local-config. **A new clone runs zero protection until someone wires it.**

Run in this exact order, first thing, in any fresh clone:

```
python scripts/install_hooks.py        # sets core.hooksPath, installs .githooks/
python scripts/verify_env.py           # asserts interpreter, toolchain, paths, ports
python tools/memory_sync.py            # mirrors markdown memory into the recall store
```

`install_hooks.py` must be idempotent and must FAIL LOUDLY if `core.hooksPath` cannot be
set. `verify_env.py` prints a table of every external dependency with found/missing and
exits non-zero on any missing hard dependency.

**Never treat a hook's presence as proof it fires.** The only valid test is end to end:
stage a violation, attempt a real commit, assert HEAD is unchanged. See section 16 for
the four ways a hook can exist and silently do nothing.

---

## 2. Documentation topology and single source of truth

Every fact has exactly ONE owner file. Other files link to it; they never restate it.
A restated fact is a fact that will drift.

| File | Owns | Never contains |
|---|---|---|
| `CLAUDE.md` | Rules, hard constraints, frozen list, settled decisions, paths, topology | Per-item history, counts, ledger entries |
| `README.md` | Outsider-facing: what it is, install, run, first result | Internal process, roadmap, session notes |
| `ROADMAP.md` | OPEN work only, with IDs and acceptance criteria | Completed work, aspirational ideas |
| `BACKLOG.md` | Aspirational and conditional-trigger items, one line each | Anything currently being worked |
| `docs/LEDGER.md` | Append-only, newest-first per-item completion record | Rules, open work |
| `docs/ARCHITECTURE.md` | Module map, data flow, seams, ownership | Ops commands, counts |
| `docs/OPERATIONS.md` | Commands, restart, scheduled tasks, runbooks | Architecture, rationale |
| `docs/adr/` | One file per architectural decision, indexed in `docs/adr/README.md` | Anything not a decision |
| `docs/GATED.md` (Amberstone: `docs/LIVE_GAME_GATED_SYNC.md`) | Items blocked on something outside the repo | Items merely unstarted |
| `WAKEUP_NOTES.md` | Last 2-3 sessions at full fidelity | Anything older (archive it) |
| `docs/history_notes.md` | Deep archive of pruned notes and old ledger items | Current state |
| `memory/` | Durable cross-project and cross-session facts (section 11) | Project state derivable from code |

**Rules:**

- **Never append a per-item completion entry to `CLAUDE.md`.** It is auto-loaded every
  turn and is size-budgeted. Ledger entries go to `docs/LEDGER.md`.
- **Do not restate a measured number in prose.** Counts (tests, coverage, versions, item
  totals) belong in exactly one machine-checked place with a drift guard. A hardcoded
  count in a doc is a lie with a timestamp on it. If a doc must display one, generate it.
- **Dated artifacts go to `docs/_archive/`**, excluded from ripgrep searches via
  `.rgignore` or an explicit glob, so they never pollute a search for current truth.
- A doc heading carrying an explicit date marks its own section historical. A drift guard
  should encode that so dated sections are not audited as current.

### 2.1 File-size budgets (context management)

Context is the binding budget in every session. Enforce in CI:

| File | Starting budget | Enforcement |
|---|---|---|
| `CLAUDE.md` | < 40 KB | CI hard fail |
| Any single auto-loaded file | < 40 KB | CI hard fail |
| `memory/MEMORY.md` (index) | < 20 KB | CI hard fail |
| Any `memory/*.md` leaf | < 6 KB | CI warn |
| `ROADMAP.md` | < 60 KB | CI warn, triggers a relocate pass |

**These are the numbers to START a new project at, not this repo's live limits.**
Amberstone itself enforces **60 KB for `CLAUDE.md` and 80 KB for `ROADMAP.md`** -
`tests/test_doc_size_budget.py` holds the constants and `tools/drift_guard.py`
warns at 90 percent of each. `CLAUDE.md` here sits above 40 KB and is compliant.
Read the guard, never this table, before reporting a budget violation in this
repo; a new project adopting these conventions should start tight and raise the
number deliberately rather than inherit a grown one.

When a budget is hit, **relocate, do not delete**. Move detail to a sub-index or an
archive file and leave a one-line pointer. A sub-index (`INDEX_<domain>.md`) holds the
domain entries; the top index holds one line per domain plus the handful of entries too
costly to ever miss.

---

## 3. Session model

Sessions are **scoped**: one focused unit of work per session. Clear between units,
between building and reviewing, and between focus areas.

**Session start:**
1. Read `CLAUDE.md`, the memory index, `ROADMAP.md`, `WAKEUP_NOTES.md`,
   `docs/ARCHITECTURE.md`.
2. Read the live-state probe output injected by the SessionStart hook.
3. **Recall before building.** Query the semantic store with the task in your own words.
   If a settled or ledger hit says the work is CLOSED, REFUTED, or shipped, stop and
   report that instead of building. This is the entire point of the store.
4. Verify the plan against ground truth (grep cited `file:line`, probe live endpoints,
   read `git log`) BEFORE scaffolding anything.

**Session end (the `/done` ritual):**
1. Run the tier-appropriate test suite and report the exact counts observed this run.
2. Commit with a descriptive message, push.
3. Sync living docs: append the per-item entry to `docs/LEDGER.md`, update `ROADMAP.md`
   (move closed items out), refresh `WAKEUP_NOTES.md` (keep last 2-3, archive older).
4. Run the drift guard.
5. Confirm CI is green.
6. **Print the full next-session continuation prompt.** This is not a courtesy; it IS the
   continuity mechanism. Every session ends with one.

**Run the drift guard at EVERY `/done`.** Thirty seconds each time beats a cleanup
session later.

---

## 4. Open / closed / gated: how work items are organized

Every work item is in exactly one of four states, in exactly one file.

| State | Home | Shape |
|---|---|---|
| **OPEN** | `ROADMAP.md` | `<ID> - <one line> - acceptance: <testable condition> - tier: <0/1/2>` |
| **ASPIRATIONAL** | `BACKLOG.md` | One line. No acceptance criteria required. Not scheduled. |
| **GATED** | `docs/GATED.md` - this repo names it `docs/LIVE_GAME_GATED_SYNC.md`; `docs/GATED.md` does not exist here | One line + the exact external condition that unblocks it |
| **CLOSED** | `docs/LEDGER.md` + a `Settled` line in `CLAUDE.md` if it must never reopen | Newest-first, dated, with a verification pointer |

**Prose discipline for all four:** one line per item. If an item needs a paragraph, it
needs its own file and the line becomes a pointer. Ban narrative in these files - they
are indexes, and an index that reads like an essay stops being scanned.

**The `Settled` section of `CLAUDE.md`** holds decisions that must never be re-litigated,
each stating what was decided AND what specifically not to re-pitch. A settled entry that
only records the conclusion invites someone to rebuild the argument. Record the fence.

**Gated items are never closed synthetically.** If an item is blocked on an external
condition, substituting a proxy for that condition and declaring it done is the single
most common way a gated backlog gets falsely drained. Split gated items into a DRAIN half
(needs the condition) and a PREP half (harness, assertions, fixtures - always available)
and work the PREP half freely.

### 4.1 Item ID discipline

Give every roadmap item a stable short ID (`<PRE>-nnn`). IDs are permanent, never reused,
and are what ledger entries, commits, tests and branches cite. A ledger entry citing only
a commit SHA is fragile: worktree-agent commits often do not survive cherry-pick. **Cite
the item ID, the merged file, and the test name - not the slice SHA.**

---

## 5. Session default: orchestrated, multi-agent, self-adjudicating, self-adversarial

**This is the default shape of EVERY session, not an escalation.** Choosing it needs no
justification; departing from it does.

Four properties, each load-bearing:

- **Orchestrated.** One merger holds the plan and the merge. Work is decomposed into
  disjoint slices BEFORE any of it starts. The merger's context stays small - it holds
  the plan and the seams, not the implementations.
- **Multi-agent.** Slices run in parallel on non-overlapping files, worktree-isolated
  wherever they write. Disjointness is a precondition, checked before dispatch, not a
  hope.
- **Self-adjudicating.** A distinct agent decides between competing outputs against
  stated criteria. **The agent that produced a thing never grades it.**
- **Self-adversarial.** Findings and "done" claims get an independent pass whose job is
  to REFUTE them, defaulting to refuted when uncertain.

**The only exception is genuinely trivial work:** a one-line cosmetic edit, a doc typo, a
single string, a conversational answer. Substance decides, not file count. A one-file
engine change is substantive; a five-file rename is not.

### 5.1 Why this keeps the main session usable

The operator must be able to type at any moment and get a response. That is only true if
the main thread is not itself doing the long work. Concretely:

- The main thread reads, plans, dispatches, merges, and reports. It does not run long
  builds, long suites, or wide sweeps inline.
- Long-running work is backgrounded so the operator can interject while it runs.
- Never fabricate or predict a pending agent's result. If the operator asks before it
  lands, say it is still running.
- Relay what matters from an agent's report; the operator does not see it.

### 5.2 Adversarial verification specifics

- **Agreement between two agents is not evidence.** Two agents can be wrong the same way,
  especially when both derive from the same stale doc or the same fixture.
- Spawn refuters with distinct LENSES (correctness, security, does-it-reproduce,
  resource lifetime) rather than N identical skeptics. Diversity catches failure modes
  redundancy cannot.
- Default to REFUTED when uncertain. A finding that survives a hostile pass is worth ten
  that survived a friendly one.
- **Never trust a subagent's claim about test counts, green CI, or file existence.**
  Probe independently: `ls` the cited file, re-run the suite, read the exit code.

### 5.3 Spec first, then act

A planning agent (or the orchestrator) emits the spec BEFORE any code exists. Verify the
spec against ground truth - grep every cited `file:line`, probe every cited endpoint,
read the git history - before a single file is scaffolded. **Never scaffold against an
assumed API surface.**

---

## 6. Execution efficiency rules

These govern HOW a step is executed - which tool, how much verification. They do NOT
govern the SHAPE of the work; section 5 governs shape, and where the two disagree,
section 5 wins.

### Text-first (R1-R4)

- **R1** Files are read and written with the file tools only. Never use a visual or
  screen-automation tool to read or change a file.
- **R2** Runtime and application state comes from an HTTP endpoint or a state file on
  disk. Never screenshot to read a number, a version, or a state.
- **R3** Visual tools (screenshot, computer-use, browser capture) are ONLY for
  rendered-pixel questions with no text equivalent: CSS, layout, visual hierarchy, and
  genuine live-capture. This is a scoping rule, not a ban - see section 13.
- **R4** Prefer built-in tools over shell. When shell is needed, use absolute paths (no
  `cd`) and one compound command over many round-trips.

Enforce R1-R3 with a `PreToolUse` guard that denies pure screen-text readers and points
at the text path, with a documented escape-hatch flag file for the legitimate exceptions.

### Tiered verification (R5-R7)

| Tier | Scope | Verification |
|---|---|---|
| **0** | Cosmetic: doc, comment, string, non-runtime constant | Edit + syntax check only. No suite, no restart. |
| **1** | Local logic in one module | Syntax check + that module's tests only. |
| **2** | Schema, engine, core algorithm, version bump, public interface | Full suite + service restart + any mirror sync. |

- **R5** Classify every change into a tier and run only that tier's verification.
- **R6** Run the relevant suite ONCE and trust the exit code. Re-run only if you edited
  since, or the tool pipe demonstrably glitched. Never prophylactically.
- **R7** **Adversarial verification is the default, not the exception.** Every
  substantive claim gets an independent refutation pass before it is called done,
  including your own single-thread edits. Tier-0 is exempt.

### Overhead (R8-R11)

- **R8** Never re-read a file you just edited to confirm the edit. Edit fails loudly.
- **R9** Orchestrated multi-agent is the default shape (section 5). Inline solo is the
  exception, reserved for trivial edits.
- **R10** Batch independent reads and greps into one message.
- **R11** Skip the visual-audit ritual for backend, version and doc changes. It is scoped
  to user-facing visual changes.

---

## 7. Test-driven development

All feature work and all bug fixes follow TDD:

1. Write the failing characterization or regression test FIRST.
2. Watch it fail for the right reason. **A test that passes before the fix is a test
   about nothing.**
3. Implement the minimum that makes it pass.
4. Grep for every sibling case sharing the same root cause and add a test for each.
5. Run the tier-appropriate suite.

### 7.1 Testing discipline

- **Before writing any test or probe, grep to confirm every method, field and data shape
  it will use actually exists, and cite `file:line` for each.** Never scaffold against an
  assumed API.
- Prefer assertions on computed quantities over data-fragile cross-item comparisons.
- Run suites from the repo root with explicit target directories, never a bare recursive
  invocation from the root - that can sweep runtime state directories and destroy live
  locks or data.
- When adding a required field to a dataclass, **append it at the END with a default.** A
  mid-class required field breaks every existing positional construction.
- Subagents that generate test files must run the linter before reporting done.
  Subagent-generated tests have broken CI before.

### 7.2 Test-quality failure classes (learned the expensive way)

- **A mutation that fails to apply looks GREEN.** Assert the anchor text was actually
  replaced. Suspect the test harness when a mutant survives, not just the test.
- **A surviving mutant may be an EQUIVALENT mutant** - one that cannot change behavior.
  Swap the mutant, do not weaken the test.
- **Beating a naive alternative is not soundness.** Derive attacks from the mechanism,
  not from what a lazy implementation would miss.
- **A negative assertion rules out without pinning down.** "Field X is absent" passes for
  the correct output AND for a totally collapsed one. Assert what IS there.
- **A raising spy is vacuous under fail-soft code.** If production catches broad
  exceptions, a spy that raises `AssertionError` proves nothing - the guard passes both
  ways. Use a recording spy and assert on the record.
- **A guard on a non-default call path is untested.** Delete the guard; if the suite
  stays green, the guard was never exercised.
- **Fixtures built parallel to the implementation stay green through the real defect.**
  Build fixtures from real captured data, not from the code's own assumptions.
- **The unrun gate is where the bug hides.** A skipped suite is not a passing suite.
- **"Zero bad rows" is relative to a SET.** State the set. The same file can be clean
  under one filter and filthy under another.

---

## 8. Tiered CI

Four tiers, each with a different latency and a different job.

### Tier 0 - local hooks (instant, blocking)

Git hooks via `core.hooksPath` plus Claude `PreToolUse` and `PostToolUse` hooks. Defense
in depth: **the git hooks are authoritative; the Claude hooks are a convenience layer.**

- `pre-commit`: character-set gate (7-bit ASCII in authored content), secret scan, lint
  on staged lines only, syntax check on changed files.
- `commit-msg`: message format, banned glyphs, required or forbidden trailers.
- `pre-push`: fast unit subset.
- `PostToolUse` on Edit/Write: syntax check the edited file, lint the edited lines.
- `PreToolUse` on commit and shell: the same character and secret gate, so a violation is
  caught before the git hook even runs.

### Tier 1 - fast lane (every push, target under 3 minutes)

Lint, type check, unit tests, doc size budgets, drift guards, link check. This is the
lane that must never be red.

### Tier 2 - full lane (nightly and on tag)

Full suite with parallelism, integration tests, **clean-checkout probe** (clone fresh,
run the bootstrap, run the suite - this is the only thing that catches "works on my
machine" wiring), dependency audit, license audit.

### Tier 3 - release / visibility-flip gate (manual, pre-flip)

Full-history secret scan, PII scan (usernames, account ids, machine names, absolute home
paths), third-party license audit, README-completeness check, docs audit. See section 17.

**Budget note:** on a private repo, CI minutes are metered. Tiering exists so tier 1 is
cheap enough to run on every push and tier 2 runs on a schedule rather than per commit.

---

## 9. Local gates and enforcement details

- **Atomic writes only** for any file another process may read:
  `tmp.write_text(...); tmp.replace(target)`. Pollers read mid-write otherwise. Retry the
  rename on Windows - it can transiently fail while another process holds a handle.
- **Never use a graceful process-stop cmdlet that can hang a tool pipe.** Prefer a
  forced kill by PID.
- **Always syntax-check before restarting a background process.** Under a windowless
  interpreter a syntax error crashes silently and looks like a hang.
- **Frozen files.** Maintain an explicit list in `CLAUDE.md` of files that require
  explicit operator approval to modify - the process supervisor, the logging setup, the
  entry point, the state authority. An agent proposing to touch one must route through an
  adjudicator and record the grant in the ledger.

---

## 10. Character set, encoding and Windows discipline

- **7-bit ASCII in all authored content.** Code, comments, docstrings, markdown,
  commit messages, shell scripts, chat output. No em-dashes (U+2014), no en-dashes
  (U+2013), no smart quotes (U+2018 U+2019 U+201C U+201D). Use a spaced hyphen ` - ` for
  a clause break.
  **Why it is a hard rule and not a style preference:** Windows PowerShell 5.1 ANSI-
  decodes a `.ps1` with no BOM, turning a UTF-8 em-dash inside a double-quoted string
  into a character the tokenizer treats as a string terminator, cascading into a parse
  failure. One incident is enough to make this permanent.
- **Commit messages with special characters:** write to a temp file and use
  `git commit -F <file>`, or a single-quoted here-string. Never a double-quoted
  here-string and never a piped string - BOM and ANSI mangling risk.
- **`write_text` converts LF to CRLF on Windows.** `read_text` hides it, so byte counts
  and hash comparisons lie. Write bytes explicitly when the byte count matters.
- **Set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`** in the environment so subprocess
  output does not mojibake.
- **Never hardcode a machine name, a user account id, or an absolute home path** into a
  tracked file. Auto-detect at runtime. These are both PII and a drift source.
- Use a windowless interpreter for background daemons so no console flashes.

---

## 11. Memory layer

**Markdown is the single source of truth. The semantic store is a mirror, never the
source.** Never fix a fact only in the mirror.

### 11.1 Markdown memory

One file per durable fact, in `memory/`, with frontmatter:

```
---
name: <short-kebab-case-slug>
description: <one line, used to judge relevance during recall>
metadata:
  type: user | feedback | project | reference
---

<the fact. For feedback and project types, follow with **Why:** and
**How to apply:** lines. Link related memories with [[their-name]].>
```

- `user` - who the operator is, their preferences and expertise.
- `feedback` - guidance on HOW to work, corrections and confirmed approaches. Include the
  why, or it will be re-litigated.
- `project` - ongoing work, goals, constraints not derivable from the code or git log.
  Convert relative dates to absolute.
- `reference` - pointers to external resources and hard-won technical facts.

**Rules:**
- Every memory is reachable from `MEMORY.md` or from an `INDEX_<domain>.md`. A drift
  guard enforces reachability. Do not unindex a file to save bytes.
- Do not save what the repo already records: code structure, past fixes, git history,
  content already in `CLAUDE.md`.
- Check for an existing file that covers the fact and UPDATE it. Delete memories that
  turn out to be wrong.
- Hook lines in the index are SHORT. The index is scanned, not read.

### 11.2 Semantic recall mirror

A local, keyless, no-cloud semantic store over the markdown. Exists because grep plus
judgment does not catch paraphrase, and paraphrase is how rediscovery happens.

- **Recall through a thin projection tool, not the raw MCP call.** A raw recall can return
  each hit's full body more than once; a projection that returns key plus one-line
  description is two orders of magnitude smaller with the same answer. A mandatory step
  that is expensive is a step that gets skipped, which defeats the store.
- Fetch one full entity by key only when you actually need the body.
- **Re-sync after changing any source doc.** The sync must be idempotent - update in
  place by category plus key, never duplicate.
- **A "healthy" status is NOT proof recall works.** A store can report healthy while most
  rows have no embedding, silently degrading recall to keyword matching. Only
  `embedded == active` proves coverage. Assert that in a `--verify` mode and run it in
  CI tier 1.
- The store, its config and its wiring are LOCAL and gitignored. Only the sync tool is
  tracked. A fresh clone has no store - section 1.

---

## 12. Agents, skills, commands and MCP

### 12.1 Agent roster (`.claude/agents/*.md`)

Minimum viable roster for the doctrine in section 5:

| Agent | Role | Tools |
|---|---|---|
| `planner` | Emits the spec and the slice decomposition before any code | read-only |
| `builder` | Implements one disjoint slice, worktree-isolated | full |
| `verifier` | Ground-truth re-check: re-runs suites clean, confirms cited files exist, cross-checks claims. Reports a verdict, never edits | read-only |
| `adversary` | Tries to REFUTE a finding or a done-claim. Defaults to refuted | read-only |
| `adjudicator` | Picks between competing outputs against stated criteria | read-only |
| `researcher` | External research, license gate, candidate triage | read + web |
| `doc-sync` | Reconciles docs against a single canonical fact set, fixes drift | full |
| `ui-auditor` | The visual-hierarchy audit ritual (section 13.2) | full |

Every agent definition carries the section 5 block so the doctrine survives into subagent
context, which does not inherit the main thread's.

### 12.2 Commands (`.claude/commands/*.md`)

| Command | Does |
|---|---|
| `/done` | The section 3 end-of-session ritual, end to end |
| `/orchestrated-run` | Set up the section 5 shape for a named unit of work |
| `/tdd` | The section 7 loop for a named feature or bug |
| `/root-cause-fix` | Failing reproduction first, sibling-case grep, minimal fix, corrupted-data backfill check |
| `/sync-docs` | Reconcile every markdown doc against the canonical fact set |
| `/drift-guard` | Run all drift guards and report |
| `/audit` | One-file deep audit: correctness, security, error handling, resource lifetime, concurrency, input validation |
| `/weekly-hygiene` | Light maintenance: trim notes, scan memory staleness, triage anomalies |
| `/insights` | Grounded activity report read from git plus ledger plus roadmap, never from transcript inference |

### 12.3 Skills

Package a skill for any workflow that is repeated and has a checklist. Skills that pay
for themselves immediately: TDD, systematic debugging, root-cause-fix, the doc-sync
ritual, the end-of-session ritual, the visual audit ritual.

### 12.4 MCP servers

Wire what the project actually needs, and remember `.mcp.json` is local and gitignored -
document the re-wire command in `docs/OPERATIONS.md`.

Typical set: the local semantic recall store; a browser-automation server for UI work; a
scraping or search server for research; a language-server plugin for the project's
language; a scheduled-task server if the project has background jobs.

**Servers requiring interactive OAuth are unavailable in headless runs.** Do not build a
critical path through one.

---

## 13. Visual, OCR, CV and machine-use policy

These tools are **allowed and expected** where they are the right instrument. R3 scopes
them; it does not ban them.

### 13.1 Sanctioned uses

- Rendered-pixel questions: CSS, layout, spacing, visual hierarchy, theme rendering.
- Live capture of an external application that exposes no text interface.
- OCR and CV as a genuine DATA SOURCE when the target application has no API - this is a
  first-class ingestion lane, not a workaround. Build it as one: a capture stage, a
  region registry, a tiered recognizer (cheap deterministic OCR first, expensive model
  escalation only on miss), and a confidence score on every extracted field.
- Desktop automation for operator-facing actions the operator would otherwise perform.

### 13.2 The visual audit ritual

Any user-facing page change runs a 5-phase audit BEFORE the commit, not after:
**STRUCTURE, TYPOGRAPHY, HIT-TARGETS, CHARACTER-SET, HIERARCHY.** Every MUST-FIX is
resolved in the same slice. Shipping a page ahead of its audit is a process failure.

### 13.3 Visual failure classes

- **An undefined CSS variable fails silently.** It greps fine and inherits instead of
  erroring. Assert computed styles, not source text.
- **An innerHTML repaint destroys keyboard focus.** A timer-rebuilt panel becomes
  mouse-only, invisibly. Test focus survival across a repaint.
- **Binding lifetime is invisible to source-level tests.** Only a real interaction finds
  a listener attached to a node that is later replaced.
- **A capture artifact goes stale.** Verify the capture's timestamp before reasoning from
  it.

---

## 14. Third-party code and the license gate

**Before lifting anything from an external repo, check the license and state what it is.**
Five measured traps:

1. **A repo can contradict itself.** An MIT `LICENSE` file alongside a manifest declaring
   `UNLICENSED` and `private: true`. Or GPL-3 in `LICENSE` and `ISC` in the manifest. One
   source alone gives the wrong answer - read both.
2. **The person who cleared it may not own it.** A repo crediting prior authors has
   multiple copyright holders; its current maintainer cannot unilaterally relicense it.
3. **A LICENSE file can name NOBODY.** An unrendered MIT template reading
   `Copyright (c) {{ year }} {{ organization }}` is a grant with no grantor. Both files
   "agree on MIT" and an SPDX grep passes. **Read the copyright LINE, not just the name.**
4. **A truncated license** (warranty clause missing) is not the license it claims.
   A `NOTICE` naming adapted upstreams means clean-license but not vendor-safe.
5. **Source-available is not open source.** BUSL and similar: do not vendor, even though
   an additional-use grant may permit running it internally.

**GPL and copyleft stay DO-NOT-VENDOR regardless of verbal clearance** - vendoring would
relicense the project itself. **Verbal clearance is not written clearance**, and absence
of a LICENSE file is not permission.

**The always-legal path:** re-implement the mechanic in the project's own code from
observed behavior. Techniques and protocol facts are not copyrightable; source is.

**Game and application data assets** (data dumps, save files, extracted resources) are
owned by their publisher. Read them from the local install at runtime, gitignore them,
and ship only extraction code and small synthetic fixtures.

---

## 15. Verification discipline

**Before asserting external state - a key is valid, a process is dead, a file is missing,
a thing is broken - verify it live against the source of truth.** Never rely on a stale
doc or another agent's unverified output. Re-probe first, then assert.

**Ground truth when the tool pipe is unreliable** is `git status`, Edit success or
failure, test output written to a FILE, and an explicit exit sentinel. Not raw stdout -
stdout can replay stale or out-of-order results.

Before reporting complete:
- Re-run the relevant suite fresh.
- Confirm every cited test file exists on disk.
- Report the exact pass/fail counts observed THIS run. Never carry forward a prior count
  or a subagent-reported count.

### 15.1 Named failure classes to check against

- **A filed count is a hypothesis, not a fact.** Re-derive every count from the artifact
  before acting on it. Filed counts have been wrong by an order of magnitude, and rows
  have refuted their own author.
- **Check a row's AGE before building on it.** A row filed months ago may describe code
  that no longer exists.
- **A resolver fix is not a consumer fix.** A falling residual count can hide a private
  copy in a consumer that never adopted the fix. Diff the CONSUMER's artifact.
- **Proving your change happened is not proving it matters.** Verify the downstream
  output changed, not just that the code path executed.
- **An empty grep is a claim about your PATTERN, not about the codebase.** Vary the
  delimiters and the casing before concluding absence.
- **A rendered field is not evidence of a producer.** Grep for writers, excluding scripts
  and tests, before assuming a pipeline exists.
- **A decline reason goes stale before the count does.** Re-read why something was
  rejected before citing the rejection; the blockers may answer a proposal nobody made.
- **A caveat stated in chat is not a caveat in the artifact.** If it qualifies a result,
  it goes IN the deliverable.
- **A data filter is not an evaluator filter.** Narrowing the input set does not narrow
  what the evaluator considers.
- **A guard can be green while self-excusing** - skipping itself on the very files it is
  meant to cover. Read what the guard skips.
- **Serialized callers self-suppress, so a duplicate implies a race**, not merely shared
  state.
- **A detached background process can return a real PID and exit code zero while doing
  zero work.** Assert the work product, not the launch.
- **A syntax checker can be blind on certain file shapes.** Verify the checker actually
  parses the construct you care about before trusting a clean exit.

---

## 16. Hooks: the ways one can exist and silently do nothing

**Hook findings are version-specific and expire. Re-measure; never inherit.**

Four confounds to eliminate before ever concluding a hook did not fire:

1. **Invalid JSON in the settings file.** A single-backslash Windows path makes it
   invalid; it never parses, no hook registers, and nothing warns you. Assert it parses
   before trusting a negative.
2. **An untrusted workspace** makes a headless run silently discard the permission
   allowlist, which presents almost identically to hooks not loading.
3. **Path-string keying.** Trust and config keys are per path STRING, so `C:\X`, `C:/X`
   and `C:/x` are three separate entries and different modes read different ones. Each
   worktree path is its own key.
4. **Presence is not firing.** The only valid test is end to end: stage a violation,
   attempt the real action, assert it was blocked.

---

## 17. Private-first, public-later

Building private and flipping public later is a valid choice, but the hygiene work does
not disappear - it is deferred and it compounds. Mitigate from day one:

**From day one, even while private:**
- `.gitignore` every credential file, every local config, every game or application data
  asset, every capture artifact and every generated cache.
- Never commit a machine name, account id, absolute home path, or personal identifier.
  Auto-detect them at runtime.
- Keep a `LICENSE` file and a `THIRD_PARTY.md` from the first commit.
- Write `README.md` for an outsider from the first commit. It is much harder to
  retrofit.
- Keep internal process docs in `docs/`, clearly separated from outsider-facing docs.

**The flip gate (CI tier 3), all must pass:**
1. Full-history secret scan (not just the working tree - history is what leaks).
2. PII scan across all tracked files and all commit messages.
3. Third-party license audit against section 14.
4. No publisher-owned data assets tracked, in history or in the tree.
5. `README.md` gets an outsider from zero to a first result.
6. All doc cross-references resolve; no orphaned or stale markdown.
7. A clean-checkout probe passes on a machine that has never seen the project.

**If history is dirty, the honest fix is a fresh-history public repo**, not a rewrite that
will be incomplete. Decide this before the first commit, because it is much cheaper then.

---

## 18. Refresh protocol for this document

This file is the portable artifact. To update it from a mature project:

1. Diff this document against the source project's current `CLAUDE.md`, agent
   definitions, command definitions, hook config and CI config.
2. For every rule in the source that is NOT here: decide if it is project-specific
   (leave it) or general (port it, stripped of all project nouns).
3. For every rule here that the source has since REVOKED or SUPERSEDED: update it, and
   record what it replaced. A superseded rule that is silently deleted comes back.
4. For every failure class newly learned: add it to section 7.2, 13.3 or 15.1 with the
   mechanism, not just the symptom. A failure class without its mechanism is folklore.
5. Re-check that nothing project-identifying leaked in: no project names, no repo names,
   no machine names, no domain-specific nouns, no paths outside the placeholders.
6. Verify the whole file is 7-bit ASCII.

**Rule of thumb for what belongs here:** a rule earns a place if getting it wrong once
cost more than reading it costs. Everything else is noise that makes this file unread.

---

## 19. Setup checklist for a new project

```
[ ] Root folder created, git initialized
[ ] .gitignore before the first commit (credentials, local config, data assets, caches)
[ ] LICENSE + THIRD_PARTY.md
[ ] CLAUDE.md with: paths, topology, hard rules, frozen list, Settled section
[ ] README.md outsider-facing stub
[ ] docs/{ARCHITECTURE,OPERATIONS,LEDGER,GATED}.md + docs/adr/README.md
[ ] ROADMAP.md + BACKLOG.md + WAKEUP_NOTES.md
[ ] memory/MEMORY.md index + memory/ leaf convention
[ ] .githooks/ + scripts/install_hooks.py, run it
[ ] .claude/settings.json: model, effort, env, hooks, permissions, plugins
[ ] .claude/agents/: planner, builder, verifier, adversary, adjudicator, researcher,
    doc-sync, ui-auditor
[ ] .claude/commands/: done, orchestrated-run, tdd, root-cause-fix, sync-docs,
    drift-guard, audit, weekly-hygiene, insights
[ ] .mcp.json (local) + the re-wire command documented in docs/OPERATIONS.md
[ ] tools/: precommit_gate, edit_lint_check, drift_guard, memory_sync, verify_env,
    facts_probe (SessionStart live-state injection)
[ ] CI: tier-1 fast lane on push, tier-2 full lane nightly and on tag, tier-3 flip gate
[ ] Doc size budgets enforced in tier 1
[ ] Port allocation recorded and verified free
[ ] End-to-end hook test: stage a violation, attempt a commit, assert HEAD unchanged
[ ] Clean-checkout probe passes
```
