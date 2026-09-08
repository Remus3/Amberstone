# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-08c - RM-386 second half: a refusal is no longer an answer, and the row asking for it was two-thirds stale

Single-row session. Tier-1, no `ENGINE_VERSION` bump, no DS bounce, no frozen
file. `RC-InboxResponder` was DISABLED for the run and re-enabled at wrap.

**Read the code before the row.** RM-386's body named three terminal states
that "answer a note and tell the sender NOTHING". Two were already closed when
the session opened - the bounce shipped the same afternoon fires on exactly
{exhausted, refused} and had arms proving it, and the `minItems: 1` fix made an
empty proposal illegal. The third was always the RM-385 class. What was open
was the clause the row filed as an OPTION: refusals were written to the
answered record, which made them PERMANENT, which is why RC deleted an entry by
hand to re-cycle RSC's 1456 note. A session that trusted the row's summary
would have rebuilt the bounce.

**Shipped.** `record_responded` went from FIVE call sites to ONE (inside
`_deliver`), so the record means only what it says. Refusals and exhaustion now
write a HOLD record, `ops/runtime/inbox_responder_held_notes.json`, keyed by
`note_sha12` of the RAW name: the note stays pending and unanswered,
`pick_note` skips it as it skips one at the spawn cap, every row carries
`notes_held`, and gate 4b says `runner-failed / notes-held` rather than
`empty` - `attempt-cap` still wins when a note is also at the spawn cap, and
the guarantee is that neither is ever `empty`. One deleted entry re-cycles the
note.

**Both costs RSC disclosed are paid, not argued away:** the repeat-refusal
storm (288 held dirs a day) is suppressed by the hold, and head-of-line
starvation - which RC had been buying off by answering refusals without knowing
it, RSC refutation 6 - is prevented by a younger note being picked ahead of the
held one, with an arm driving exactly that. Both record faults fail CLOSED:
unreadable terminates `held-record-unreadable` before anything is spent,
unwritable clears `bounce_target` so nothing goes into the sibling's tree.

**Traps worth keeping.** A fixture that makes the record a DIRECTORY does not
test the unwritable path - the unreadable gate catches it first; the arm needs
the `.json.tmp` name occupied instead. And `metrics_row_ok` bans the substring
`refus` on a non-refused row, so the vocabulary had to be `notes-held`, not
anything spelled with "refusal".

**Live data measured, and one entry deliberately LEFT.** The answered record
holds 108 entries: 106 are the deliberate seed, one is the correctly answered
1530 note, and one - the 1456 note, `e83297be2bf9` - is the single false entry
the old code wrote (only ever refused then exhausted, never replied to).
Deleting it is an OPERATOR call, not a neutral repair: it is older than the two
unanswered notes now in the inbox, so it would sort to the head and spend the
first hop of the next agreement. Command is in `docs/LEDGER.md` 1366.

**Do NOT redo:** the hold record and its two fail-closed directions, the
`notes-held` / `held-record-unreadable` vocabulary, the three repaired mutants
plus the one added, the amended spec sections 2 and 4b.

**Still open:** RM-385 (strict-xfail untouched), RM-387, RM-388. A
`destination`-stage refusal is still answered on purpose - `_deliver` records
before the link attempt and a mutant pins that order.

---

# 2026-09-08b - the responder was ARMED, and running it found what testing could not

Continues 2026-09-08 below. The runner was armed against RSC (A5-measurement-only,
`hop_budget 1`, 24 h window, `agreement_id a9f7e59541f9ab87`) and **it delivered**:
`2026-09-08-1657-from-RC-RESPONDER-re-6e62aa1071a0.md`, `delivered / delivery=1 of 1`,
M1 LOWER_BOUND hops 1, M3 21 turns, m4 proposed 1 allowed 1. RSC independently
confirmed receipt at 17:00, 2889 bytes. First machine-authored note that channel
has carried.

**FOUR live defects that a green suite could not see.** Every one surfaced by
RUNNING the thing, not by testing it. (1) The first armed tick refused a real
note on `name-grammar` - and RC's own filed cause was WRONG: `NOTE_NAME_MAX` was
a red herring, the binding constraint was `NOTE_NAME_RE`'s `{1,80}` TOPIC group,
and raising the named cap alone would have fixed ZERO of the 34 failing names
across 208 unique notes. Caps now `{1,160}` / 200; 0 of 208 fail. (2) The
re-queued note was then EXHAUSTED silently - and the root cause was in the
PROMPT, not the gates: `SYSTEM_PROMPT` literally instructed "if there is nothing
to measure, return exactly `{"actions":[]}`". Fixed with `minItems: 1` plus a
rewritten paragraph, and RSC's bounce design adopted (a `.txt` that fails the
note grammar on every clause, own allowance, excluded from budget/M1/M2/M5).
(3) `SPAWN_TIMEOUT_S` 120 was too short for a 618 MB export - now 240. (4)
`MAX_TURNS` 12 was too tight - the delivering cycle used **21**, so the old
limit would have failed a third time and hit the attempt cap. Now 30.

**Three of the spec's own UNMEASURED guesses were measured by running it**:
export size (618 MB), `SPAWN_TIMEOUT_S`, `MAX_TURNS`. Each failure labelled
itself correctly rather than lying, which is the one thing the build got right.

**Do NOT redo:** the caps, the prompt/schema fix, the bounce, the two constants.
RC and RSC independently converged on the SAME six bounce properties, which is
the strongest evidence the shape is right.

**Open, all in `BACKLOG.md`:** RM-385 (junction-named note invisible forever,
plus a second instance - a note with sender and date transposed), RM-386 second
half (THREE terminal states answer a note and tell the sender nothing), RM-387
(reply body shows the sender their filename clipped to 80), RM-388 (metrics
ledger never trimmed while the invocation log is; from RSC's refutation list -
four of their six were checked and do NOT apply to RC, recorded so nobody
re-checks them).

**Operational:** the task must be DISABLED to run the suite (it writes the live
log every 5 min and the autouse arm guards exactly that). The `hop_budget 1` is
now SPENT, so every further cycle reads `budget / consumed=1 budget=1` until a
new agreement is written - which is an operator act.

---

# 2026-09-08 - RM-384: the responder runner is BUILT, and the three conditions are MEASURED

31 commits `f4472f58e..966febbfd`, pushed. Full `pytest tests` from the repo
root: **21591 passed, 102 skipped, 1 xfailed, 4921 subtests, 0 failed** in
65m31s. No `ENGINE_VERSION` bump, no DS bounce, no frozen file touched.
Per-item detail in `docs/LEDGER.md` 1364.

**What shipped.** `tools/inbox_responder_{procs,prompt,exec,export,spawn,runner}.py`,
`ops/install_RC_InboxResponder.ps1`, and eight test files - procs 18, prompt 13,
exec 90, export 15, spawn 55, runner 187 (+1 skipped, +1 xfailed), mutants 76,
task 45, each measured individually on the frozen tree. Nine worktree slices,
subagent-first, verifier or adversary gate on every merge.

**The three conditions, measured not written.** (1) `validate_proposal` is gate
12, one tagged call site, driven live; 26 `# GATE:` tags each exactly once
against a literal census; 68 mutants, 68 reddening. (2) Interactive
`--dry-cycle` reports `SUMMARY: PASS 12 FAIL 0` and exits 0, and the TASK-FIRED
run - the one the interactive run cannot stand in for - delivered on pid 31320,
not the shell's 6384. (3) Two live `disarmed / no_agreement` ticks five minutes
apart, pids 15084 and 23072. The arming note went to RSC's inbox, 13907 bytes,
disclosing both vocabulary extensions.

**A ROW LIST IS NOT A COVERAGE PROOF - the single most useful thing learned.**
The first mutants agent reported "44 of 44 redden", which was TRUE and was not
the claim that mattered. A second adversarial pass measured that two of the 26
gates, `start` and `deliver`, had NO mutant on the gate's own call site: every
candidate mutated a helper nearby. The census now requires each arm's needle to
sit INSIDE the statement its `# GATE:` comment marks. If a future session takes
a mutant score at face value, this is the paragraph to re-read.

**Three of RC's OWN spec mutants were vacuous**, and are recorded in the spec's
new "Build measurements" section rather than quietly patched: `harden` is inert
when driven by `git status` (the pre-check re-derives the identical rule, so
only POSITIONAL cases are unique to hardening); `gate-exception` as written is a
SyntaxError; `reason-scrub`'s codec mutant cannot fire, because validator
reasons pass model values through `repr` and are ASCII before the scrubber sees
them.

**The dry cycle earned its keep by FAILING first.** Run one terminated
`spawn-failed / timeout` - correctly labelled, not as the reassuring
`exhausted` - and measured two figures the spec had flagged as guesses: the
tracked-only `origin/main` export is **618 MB**, and `SPAWN_TIMEOUT_S` 120 is
too short for a session that Reads and Greps it. Raised to 240; every bound in
section 11 still holds (500, 560, both under 600). Also measured: the CLI does
NOT reject an unsatisfiable schema - it returns `subtype success` with
`structured_output {"actions": []}`, which is exactly why `exhausted` must mean
`actions == []` only.

**Four defects found by the arms, three fixed.** The export module filed every
runner fault as `exc:str` (and its own arm passed only because the stub carried
an exception OBJECT, a shape the seam never produces); `metrics_row_ok`
destroyed gate 11's own exception tag via the `exhaust` substring invariant;
held `spawn.json` dropped `kill_skipped`. **STILL OPEN and xfail-pinned:** a
note whose NAME is a directory junction never reaches the gate 6 link checks,
because `pending_notes` filters on `is_file()`. It reads `empty / none_pending`
and sits in the inbox unremarked on every later tick. Not a containment hole - a
companion PASSING arm pins that nothing outside the inbox is opened, quoted,
spawned for or delivered - but fixing it means editing `inbox_responder.py`,
which spec section 15 forbids, so it needs its own scoped item.

**Two repo guards tripped and were fixed properly, not suppressed.** The
home-path guard flagged the responder's own scrubber control fixtures, which
must feed a real home-shaped path to prove the redaction - pinned BY MEASURED
COUNT using the guard's own `findings_in`. Three surrogate-filename arms gated
their skip inside an `except`, which the skip-hygiene guard cannot resolve;
reshaped into a real capability probe, which then measured that NTFS here
accepts BOTH `\udcff` and `\ud800`, so both cases RUN.

**THE WINDOWS SUITE PASSING 21591 SAID NOTHING ABOUT LINUX.** CI then found
two real portability defects. `ensure_export`'s adopt-the-winner branch caught
`FileExistsError`, and that errno is not portable - POSIX raises ENOTEMPTY /
ENOTDIR / EEXIST for a rename onto an existing non-empty directory - so a
benign two-cycle race surfaced as `ExportFailed: exc:OSError`; it now decides
on the STATE of the destination. And the four dry-cycle-report arms depended on
the HOST having a resolvable `claude` binary, which no runner has. The sweep
caught two more of the same class: a shim written without the exec bit is
invisible to POSIX `shutil.which` (one arm was passing VACUOUSLY), and the ps1
no-account-name arm read the account from `os.environ`, which on the GitHub
runner is literally `runner` - it would have matched `inbox_responder_runner.py`
and the English word and raised a FALSE accusation. Final head `cf69d7904`,
34 commits; `ci` green with the `check` job confirmed RUN at 19 steps, and
`docs-guards` DISPATCHED (it path-ignores `.py`, so it would not have run at
all) and green at 11 steps.

**And one correction this session owes itself.** The pre-session `ci` run at
`f4472f58e` was red, and it was first written up as inherited breakage that
covered part of this build's failure. Opening `jobs[]` instead of citing the
run conclusion shows the failing job was `nightly-full-suite` with `check`
SKIPPED - so that run says NOTHING about the job that judges a push, and the
only hard `check` failure on these commits was RC's own export arm. The memory
`reference_green_ci_run_may_have_skipped_the_job` is about a GREEN run hiding a
skip; this is the identical error in the red direction, and it is the more
tempting one, because "already broken" is a comfortable thing to conclude.

**Operational fact worth carrying:** `RC-InboxResponder` is registered and
Ready but DISARMED (no agreement record), and it must be DISABLED to run the
full suite, because it appends to the live responder log every five minutes and
the suite's autouse arm guards exactly that surface.

---

# 2026-09-07e - ULTRAPLAN: the responder runner is SCOPED, not built. Next session builds it from `docs/RESPONDER_RUNNER_SPEC.md`

One commit, docs + memory only. No code, no `ENGINE_VERSION`, no frozen file,
no suite run (Tier-0). CI path-ignores `*.md`, so this push proves nothing and
claims nothing.

**Deliverable:** `docs/RESPONDER_RUNNER_SPEC.md` (133 KB, 16 sections + open
risks). It is the spec the implementing session executes WITHOUT re-deciding:
module map, `run_once` contract with the ordered gates, the read-only spawn,
the system prompt + `--json-schema`, the deterministic executor, output filter,
delivery, the metrics record, the invocation line, arming, `RC-InboxResponder`
registration, a 26-row GATE-TO-ARM TABLE with a mutant per gate, the dry-cycle
procedure, a TDD build order in six worktree slices S0-S5, non-goals, and what
the arming note to RSC must contain.

**How it was produced, so its confidence is legible.** One 16-agent workflow:
5 read-only readers (task analog, test isolation + CI, headless contract,
delivery path, prompt + schema) -> 3 independent designs (enforcement-first,
untrusted-input-first, measurement-first) -> 3 judges (tally 150 / 159 / 135,
untrusted-input-first won) -> synthesis -> 3 refuters (43 raised, 42 stood) ->
repair. Then THREE independent verifier passes on the repaired doc: 16 must-fix
-> 9 -> 3, each round repaired by a separate edit agent. The final 3 + 13 were
applied and PRESENCE-CHECKED BY GREP, not adversarially re-read: **there was no
fourth pass.** The build session re-refutes each section as it lands.

**Measured this session (main thread, CLI 2.1.251 - version-pinned, expires on
upgrade; memory `reference_claude_p_readonly_spawn_shape`):**
- `claude.cmd` wraps a NATIVE `bin\claude.exe`; spawn it by path, never by
  bare name (RSC's first live spawn died on exactly that).
- `--bare` is UNUSABLE: it forces API-key auth and never reads OAuth, and RC
  rides the Max login with `ANTHROPIC_API_KEY` cleared.
- `--restricted --tools "Read,Glob,Grep" --strict-mcp-config
  --no-session-persistence --output-format json --json-schema <s>` ran a live
  9 s probe: exit 0, Max login, and ZERO project hooks fired (hook log and
  seen-set sha256-identical before and after). The json result carries
  `structured_output`, `total_cost_usd`, `usage`, `duration_ms`, `num_turns`,
  `is_error`, `subtype`, `terminal_reason` - the M3 source in one record.
- The CHECKOUT is not a public-safe read set (gitignored API key, `.mcp.json`,
  sibling-path config, 100+ other parties' notes, 5182 reflog-only commits),
  so the spec spawns against a tracked-only `git archive origin/main` export.

**Decisions the spec marks DECIDED (do not reopen in the build):** single
spawn per cycle; the executor EXECUTES A1 + A5 and HOLDS A2/A3/A4 (validated,
recorded in M4, never dropped); reply target = the SENDER only, from the
filename; arming = a well-formed, expiring agreement record (absent/malformed/
expired/STOP flag -> `disarmed` with `disarmed_by`); every write after the
session exits; `log_root` injectable so no test touches `ops/runtime`;
`RC_RESPONDER_REAL_SPAWN=1` gates the real spawner (CI never sets it). **Two
vocabulary EXTENSIONS beyond the settled seven + `spawn-failed`, both to be
DISCLOSED to RSC in the arming note, not slipped in:** a ninth termination
`runner-failed` (local instrument faults - export, slot timeout, nonce
collision, prelude - which `spawn-failed` would misattribute to the CLI) and
`attempt-cap`, which HOLDS a note for the operator after `MAX_SPAWN_ATTEMPTS`
and never answers or retires it (an instrument bound, judged by two verifier
passes not to be a stop rule in costume).

**Nine notes read (arrival order on RC's disk), all marked seen, none answered
- RC's silence stays "unready" by RC's own rule until the three conditions
hold:** LL 1815 (no scrub, count withdrawn), RSC 1800, LW 1813 (RC's 11 is
EXACT, the scope sentence "all in 8 blobs" is FALSE: 14 hits / 10 blobs / 4
files incl. two docs; a retired sibling absent from RC's headline; trees and
commit messages clean; `refs/pull` a controlled zero; `backup-pre-scrub` tag
public and clean; 6 post-recreate commits with the PERSONAL email; 5 commits
with Claude as author/co-author), LW 1820 (relay not owed), RSC 1817, RSC
1824, LL 1830 (its controls now named), CS 1905 (yes, restricted to A1-A2,
A1 needs an OUTPUT filter, CS's outbound ratio is ZERO), CS 2020 (a commit
shipped without pre-push grading it - RC's `pre-push` is git-lfs ONLY, so no
window here and no grading either; out of scope, recorded), RSC 1848
(LATENCY-ONLY armed 19:00-21:00, `spawn-failed` found by running, Task-XML
traps), LL 1905 (RC's 18-min skew confirmed as drafting-time stamps), and a
tenth after wrap began, LL 2035 (their identity count is now TWO; a split
token defeats every whole-token sweep - memory
`feedback_whole_token_search_is_a_contiguity_claim`).

**Acted on:** repo-local `git config user.email` set to the noreply address
(executes the already-taken LEDGER 1360 decision; the personal address was
still the checkout default and would have leaked a seventh time on this very
commit). **Open, operator-gated:** the 6 + 5 commits already public (a
rewrite); RC's own outbound ratio (unmeasured here).

**Operator feedback, mid-turn:** "be quieter on the token output in a session
that is supposed to be sub-agent first." Recorded in
`feedback_subagent_first_protocol` - the brief's INPUTS (115 KB of notes, ~20
probes) go to reader agents too; the main thread reads the brief and the
roll-ups.
