# Loop Improvements - gemini<->claude headless iteration (2026-06-27)

Synthesis of 4 research lanes (caveman-teardown, rc-loop-audit, oss-patterns, prompt-eng).
Every premise re-verified live against `ops/loop/*` + `.claude/settings.json` (grep + Read,
file:line cited). Already-shipped loop features are NOT re-pitched: Python controller
(`ops/loop/loop_controller.py`), gemini-3-pro-preview DIRECTOR/AUDITOR
(`director_prompt.md` / `auditor_prompt.md`), AHK v2 bridge (`claude_gui_bridge.ahk`),
`done_sentinel.py`, per-cycle /done + /clear, newest-first ledger-HEAD digest +
persisted directive chain (commit d8445fec), gemini spend meter + $200 ceiling
(`config.json:4`), the `control/gemini_ask.txt` escalation channel + `tools/gemini_ask.ps1`,
the STOP-file abort, and the orchestrator-merge executor framework
(`.claude/commands/headless-upgrade.md`). wenyan is being wired separately by the
operator - explicitly OUT of scope here.

## 1. Executive summary

- The loop's signature failure (R28 stale-directive re-ship) is only HALF closed: the
  d8445fec continuity fix covers within-run directive chain + newest 60 LEDGER lines but
  does NOT defend against commits made OUTSIDE the loop while it was idle - the exact R28
  vector. A cross-run `DELTA SINCE LAST RUN` git block + a machine-readable DONE-id
  allowlist closes it.
- Three SILENT-TERMINATION / MIS-BILLING bugs are live in the controller: a flaky-gemini
  timeout is misread as `NO_WORK` and prematurely ends a 100-cycle run
  (`loop_controller.py:379`); the gemini-ceiling counter resets to 0 on a controller
  restart (no checkpoint), defeating the runaway backstop; and the spend meter pins one
  transcript at launch and under-reports after a mid-run session rotation.
- The grounding hole is structural: the director can hallucinate file state (R28 invented
  `ENGINE_VERSION 1.144.0`) and the auditor self-grades from a text diff while
  `done_sentinel.py` trusts the executor's self-reported test counts. Mandated
  PREMISE-CHECK + a sentinel that shells out to the real pytest run close both.
- The prompt layer carries the highest-leverage cheap wins: an explicit ENGINE-IMPACT
  schema line that bans the R19 bump/no-bump contradiction outright, a forced GROUNDED
  prefix proving the director read the digest (not its memory), and a one-word THEME: line
  that repairs the already-built chain digest the de-dup logic depends on.
- The caveman repo contributes ONE genuinely additive lift (a live-spend statusline badge,
  Tier-0) and surfaces ONE live defect unrelated to any lift: the SessionStart hook at
  `.claude/settings.json:87` points at `tools/caveman_default.py`, which does NOT exist on
  disk - the fleet caveman-default doctrine is silently dead on Legion.

## 2. NOW lane (HIGH-lift, low-risk, real file:line integration point, testable)

Ordered by leverage. Each cites a verified integration point and a test hook.

### N1. ENGINE-IMPACT directive schema line (bans the R19 bump/no-bump contradiction)
> **SHIPPED 2026-06-27 (`83a19108`, operator-delegated continuation).**
- **WHAT:** Add a mandatory `ENGINE-IMPACT: NONE|BUMP` line to the directive skeleton the
  director emits, with a one-clause justification, encoding the settled forward-marker
  convention (memory `feedback_ds_forward_marker_no_bump`). Forbid emitting both a bump
  instruction and a "byte-identical when unconsumed" instruction in the same directive -
  that pairing IS the R19 contradiction (`ORCHESTRATION_PLAN.md:299-306`) and cost a
  synchronous `gemini_ask` round-trip to resolve.
- **WHERE:** `ops/loop/director_prompt.md` HARD RULES (insert after `:13`); the REFILL
  PROTOCOL slice block is at `:50-55`, FINAL STEP at `:70-71`.
- **WHY/EVIDENCE:** R19 + R28 both shipped self-contradictory ENGINE instructions; the
  loop has no structural ban, only executor goodwill.
- **TEST:** characterization test asserting a directive containing both `ENGINE-IMPACT:
  NONE` and an `ENGINE_VERSION` bump string is rejected by the auditor (pairs with N4).
- **RISK:** LOW - pure prompt text in one `.md`; no controller change.

### N2. MANDATORY GROUNDING PREFIX + newest-item-supersedes rule (kills R28 root cause)
> **SHIPPED 2026-06-27 (`83a19108`, operator-delegated continuation).**
- **WHAT:** Force the director to open every directive with a 3-line GROUNDED block:
  `GROUNDED-AGAINST: HEAD=<sha> LEDGER-TOP=<newest item id> CHAIN-LAST=<last cycle id>`,
  `NOT-A-DUPLICATE-OF: <nearest digest item + the one file/accessor/test that makes this
  distinct>`, `PREMISE-CHECK: <each factual claim tagged [from-digest] or UNVERIFIED>`.
  Add a supersede rule: items that landed AFTER a plan/LEDGER row was written WIN over the
  older phrasing. The digest already exists in `build_director_context`
  (`loop_controller.py:237-247`) but the prompt never makes the director PROVE it read it -
  R28's "keyed off LEDGER 618 phrasing without reading 619/620 above it"
  (`ORCHESTRATION_PLAN.md:216-239`) is exactly a passive-cross-check failure.
- **WHERE:** `ops/loop/director_prompt.md` (insert after `:13`, before HARD RULES);
  optionally tighten the DE-DUP RULE string at `loop_controller.py:243-247` to demand the
  single not-yet-on-disk artifact.
- **TEST:** prompt-render test asserting the emitted template contains the three GROUNDED
  headers; auditor REGRESS test for a directive whose NOT-A-DUPLICATE-OF artifact already
  exists.
- **RISK:** LOW - prompt text; the optional controller-string tweak is one line.

### N3. Director timeout vs NO_WORK disambiguation (stops false run termination)
> **SHIPPED 2026-06-27 (`83a19108`, operator-delegated continuation; tests/test_loop_gemini_timeout.py).** N12 (caveman_default.py) shipped earlier this session in the wenyan commit.
- **WHAT:** `gemini()` returns `""` both on a genuine empty answer AND on all-3-retries
  exhausted after the 300s timeout (`loop_controller.py:196-219`, worst case ~924s of dead
  loop). `main()` then reads that `""` as `NO_WORK` and calls
  `stop("director returned no work")` (`:379-380`) - a flaky CLI falsely ends a 100-cycle
  run. Fix: have `gemini()` return a distinct sentinel (e.g. `None`) on
  retries-exhausted-error vs `""` on a successful empty; in `main()`, only the literal
  `NO_WORK` token from a SUCCESSFUL call terminates - on the error sentinel, log + re-enter
  the same cycle (or fall to `fixed_directive`).
- **WHERE:** `ops/loop/loop_controller.py:196-219` (`gemini`) + `:378-380` (`main`).
- **EVIDENCE:** real `gemini try 1 error: ... timed out after 300 seconds` event in
  `controller.log` 2026-06-22T13:22:11.
- **TEST:** add a `--gemini-timeout` / config.dry injection so the director stub returns the
  error sentinel on cycle N; assert the loop does NOT stop and re-enters the cycle (extends
  `claude_stub.py:44-48`, which today only does `--hang` / `--regressions`).
- **RISK:** LOW-MED - small control-flow change on a well-isolated function; dry-run covered.

### N4. Auditor gets the directive + ENGINE/slice/test-count REGRESS triggers
- **WHAT:** The auditor body is `tmpl + range + log + diff` only
  (`loop_controller.py:277`) - it has no baseline, no expected-shape, so it cannot tell a
  bump that SHOULD have happened from one that should not, nor catch a re-shipped no-op.
  Feed it the directive being graded + the self-reported `last_done`, and add REGRESS
  triggers to `auditor_prompt.md`: (a) ENGINE handling contradicts the directive's
  ENGINE-IMPACT line; (b) a file edited that the SLICES block assigned to a different slice
  or to no slice (scope creep); (c) self-reported `tests_pass` LOWER than prior with no
  deleted-test justification; (d) the directive claimed to CREATE an accessor/file/test that
  already existed (empty/trivial diff = re-shipped no-op, the R28 class).
- **WHERE:** `ops/loop/loop_controller.py:277` (pass `last_done` into `auditor()`, already in
  scope at the call site `:422`); `ops/loop/auditor_prompt.md:5-12` (current triggers) -
  append after `:11`.
- **TEST:** unit test feeding a directive + a diff that touches a file outside its declared
  slice; assert VERDICT: REGRESS. (Auditor stays advisory; binary verdict still gates at
  `:422`.)
- **RISK:** LOW - one controller plumbing line + prompt text; auditor output already parsed
  only for CLEAN/REGRESS.

### N5. THEME: line repairs the directive-chain digest the de-dup depends on
- **WHAT:** `directive_title()` prefers a `THEME:` line (`loop_controller.py:138`) but the
  director never emits one (verified: grep `^THEME:` in `director_prompt.md` -> 0 hits), so
  titles fall through to the verbose `DIRECTIVE:` first line. The "DIRECTIVES ALREADY
  ISSUED THIS RUN" chain (read at `:234`, persisted newest-first and NEVER cleared per the
  `record_directive_outcome` docstring `:154`) is therefore noisier than designed -
  degrading the very de-dup the chain exists for. Fix is prompt-only: make the FIRST emitted
  line `THEME: <2-4 word area tag>`. Zero controller change.
- **WHERE:** `ops/loop/director_prompt.md` (add to the emission skeleton); parser already at
  `loop_controller.py:130-148`.
- **TEST:** `directive_title()` unit test on a body starting with `THEME: cc-ehp-consumer`
  returns the tight tag, not the DIRECTIVE line.
- **RISK:** LOW - free win, parser path already shipped.

### N6. /clear race hardening - clipboard-paste the slash line, not per-char SendText
- **WHAT:** `claude_gui_bridge.ahk:58-67` documents the real 2026-06-06 incident where
  `/clear` landed as `clear/` (SendText raced the TUI slash-menu) and the session silently
  did NOT reset - a full context-bleed cycle the controller cannot detect (it treats
  `gemini.ready` disappearing at `:76` as proof of typing, with zero read-back). The current
  mitigation is a hand-tuned `Sleep 400` (`:66`). For the `/clear` line specifically, prefer
  `A_Clipboard := "/clear"` + `Send("^v")` - paste is atomic and cannot interleave with the
  slash-menu. Keep SendText for the directive body.
- **WHERE:** `ops/loop/claude_gui_bridge.ahk:58-67`.
- **TEST:** dry-mode bridge run against the `RC-LOOP-DRYRUN` Notepad target
  (`ahk_mode.txt = dry`, `:7`); assert the literal `/clear` lands intact in the buffer.
- **RISK:** LOW - isolated to the one most-consequential line; SendText path unchanged for
  the body.

### N7. AHK PID-stale title-match fallback + distinct log line
- **WHAT:** `Target()` resolves the live window by `ahk_pid <pid>` from
  `target_pid.txt` (`claude_gui_bridge.ahk:25-32`), written once at launch. The moment the
  Claude window is reopened mid-run the PID goes stale; `WinExist` then fails silently
  (`:44-47` just `Sleep 1500; continue`) until the controller's 120s deadline (`:399`). Fall
  back to the `claude_window_title` title-match (already in `config.json:14` = "Claude")
  when the pinned PID no longer exists, and log a distinct "PID stale, fell back to title"
  line so a wrong-window type is diagnosable.
- **WHERE:** `ops/loop/claude_gui_bridge.ahk:25-32,44-47`; title source `config.json:14`.
- **TEST:** dry-mode run with a bogus `target_pid.txt`; assert the bridge resolves the title
  fallback and logs the stale line.
- **RISK:** LOW - additive fallback; existing PID path preserved.

### N8. Controller checkpoint/resume of GEMINI_USD + prev_sha + same_sha_streak
- **WHAT:** On a mid-run controller crash, `main()` re-initializes `prev_sha = head()`
  (`:360`), `same_sha_streak = 0` (`:362`), and `GEMINI_USD = 0.0` (`:33`) from scratch -
  the gemini-ceiling counter resets to 0, DEFEATING the $200 runaway backstop
  (`config.json:4`). `directive_history.jsonl` survives but the spend meter does not. Persist
  `{gemini_usd, prev_sha, same_sha_streak}` to `control/loop_state.json` after each cycle
  (atomic, reuse the `awrite` helper at `:41`) and reload it in `main()` at `:354-363`.
- **WHERE:** `ops/loop/loop_controller.py:33,354-363,418`.
- **TEST:** write a `loop_state.json` with `gemini_usd=199.5`, start the controller, assert
  it resumes at 199.5 and trips the ceiling on the next gemini call rather than zeroing.
- **RISK:** LOW - additive persistence; absent file = current cold-start behavior.

### N9. Spend meter unions in any newer session that appeared after start
- **WHAT:** `session_files()` pins the single newest transcript at launch and bills it for
  the whole run (`loop_controller.py:296-306`); a `/clear`-driven session rotation or
  crash-reopen creates a new `.jsonl` the pinned meter never sees, so `claude_info`
  under-reports (it showed a frozen `$5.55` across cycle 1 and 2 of the last dry run). Since
  Claude spend is uncapped (`config.json:5`) this is informational, but the operator's
  runaway-watch is blind. When no `session_jsonl` is pinned, re-scan each `meter()` call for
  ALL top-level jsonls with `mtime >= start_ts` and union them, instead of locking the
  single newest at launch.
- **WHERE:** `ops/loop/loop_controller.py:296-306` (`session_files`) + `meter()` `:308-327`.
- **TEST:** two jsonls both newer than `start_ts`; assert `meter()` sums both.
- **RISK:** LOW - widening a scan; the explicit-pin path (config-set) is untouched.

### N10. Live-spend statusline badge (caveman #4 lift)
- **WHAT:** The statusline at `.claude/settings.json:96` renders
  `[Legion] <model> - <cwd> ctx:N%` but NO spend. The loop already computes live spend
  (`loop_controller.py:308-327` `meter()` -> `control/budget.json` with `gemini_usd` +
  claude info, also surfaced via `/loop-monitor`). Append `$d.cost.total_cost_usd` (Claude
  Code feeds cost into the statusline JSON) or read `control/budget.json` so a live `$X.XX`
  shows during an uncapped 100-cycle run without opening `/loop-monitor`.
- **WHERE:** `.claude/settings.json:96` (single-line statusLine command edit).
- **TEST:** Tier-0 - run the statusLine PowerShell with a sample JSON carrying
  `cost.total_cost_usd`; assert the `$X.XX` appears.
- **RISK:** LOW - Tier-0 settings edit, single line.

### N11. done_sentinel shells out to the REAL pytest run (closes the self-report hole)
- **WHAT:** `done_sentinel.py:37` records `tests_pass` + `regressions` from the `--tests` /
  `--regressions` args the executor PASSES - i.e. self-reported, the exact fabricated-count
  failure mode CLAUDE.md "Verification Discipline" warns about. Harden it: have the sentinel
  itself invoke the pytest run (or read a machine-written result file the directive's FINAL
  STEP produced) and capture the real exit code + count, so `:406` /the auditor gate at
  `:422-426` keys on a machine-observed signal, not the executor's claim. Note: this is a
  partial; the fuller deterministic-verifier (ReVeal pattern) and the SDK-channel migration
  (F-lane) are the complete answer - see FUTURE.
- **WHERE:** `ops/loop/done_sentinel.py:28-42`; consumed at `loop_controller.py:402-406,422`.
- **TEST:** call the sentinel with `--tests 9999` while the real suite has a known failure;
  assert the written `claude.done` reflects the real count, not 9999.
- **RISK:** MED - the sentinel is Claude's LAST cycle action; a wedged pytest could starve
  `claude.done`. Bound it with a timeout (the existing `head()` already times out at 30s,
  `:23`) and degrade to the self-reported value on timeout so continuity is never lost.

### N12. Create the missing tools/caveman_default.py (live defect, not a lift)
- **WHAT:** The SessionStart hook at `.claude/settings.json:87` invokes
  `pythonw.exe "...\tools\caveman_default.py"` but the file does NOT exist on disk
  (verified: `ls tools/caveman_default.py` -> No such file). The hook fails silent (hooks
  no-op on missing target), so the "caveman default-on all 3 machines" doctrine (memory
  `feedback_caveman_default_fleet`) is NOT enforced on Legion. Create the stub that writes
  the caveman-active flag (or repoint the hook at the real activation path).
- **WHERE:** `tools/caveman_default.py` (missing); referenced `.claude/settings.json:87`.
- **TEST:** run the hook command; assert exit 0 + the activation flag file is written.
- **RISK:** LOW - new stub; no existing behavior altered (the hook is already dead).

## 3. FUTURE lane (valuable, needs a dependency / schema lift / operator call)

### F1. Migrate the executor channel from AHK send-keys to the headless SDK (`claude -p`)
- The AHK bridge IS the send-keys anti-pattern Claude Code docs warn against ("special
  characters, quotes, newlines... break unpredictably") - and `claude_gui_bridge.ahk`
  documents the lived proof (the `/clear` -> `clear/` race at `:58-67`, the
  `LINE_PAUSE:=1500` / `Sleep 400/350` pacing hacks). A `claude -p --output-format json
  --resume <session_id> --permission-mode dontAsk` call invoked directly where the
  controller writes `gemini.ready` (`loop_controller.py:386-391`) would: (a) return exact
  `total_cost_usd`, retiring the transcript-scraping meter (`:296-327`, fixes N9 entirely);
  (b) let `--json-schema` return `{sha, tests_pass, regressions}` directly, retiring
  `done_sentinel.py` + the `claude.done` handshake; (c) eliminate the slash race + typing
  deadline + the always-on AHK process.
- **OPERATOR CALL:** RC deliberately drives a LIVE interactive window (the gemini-headless
  skill /clears the CURRENT session); `claude -p` is a separate process. This is a
  channel-architecture decision, not a drop-in. Gate behind a `channel: ahk|sdk` knob in
  `config.json` alongside the existing `ahk_mode.txt` file-selector. Highest architectural
  leverage; present as a migration, not a swap.

### F2. Pre-push validation gate (move one verifier gate ahead of the irreversible action)
- The irreversible action is `git push origin/main` inside each cycle (directed at
  `director_prompt.md:67-69`); the Gemini auditor runs AFTER the push
  (`loop_controller.py:422`, post-`claude.done`), so a regress lands on main and the next
  cycle inherits it. RC already has the building block (the `verifier` subagent gate before
  MERGE, `director_prompt.md:53`). Extend the directive to require the verifier + a fresh
  suite BEFORE push; keep the post-push Gemini auditor as the independent second check.
  Prompt + directive-schema change; low risk but touches the commit ritual, so stage with a
  full Tier-2 suite run.

### F3. 0.0-1.0 auditor quality score + quality-plateau early stop
- The auditor emits only binary `VERDICT: CLEAN|REGRESS` (`auditor_prompt.md:15-19`),
  discarding gradient - a low-value scope-creeping cycle reads identical to an excellent one,
  so the director cannot prefer higher-quality lanes. Append a `QUALITY: 0.0-1.0` line
  (test-coverage / scope-discipline / ASCII-hygiene), persist it in `record_directive_outcome`
  (`loop_controller.py:150-168`, which already stores `verdict` - add a `quality` field), and
  add a code-side `stop("quality plateau")` near the same-sha guard (`:417-420`) when the
  rolling mean falls below a floor. Same-sha never trips on trivial-but-new-sha cycles, so
  this is the missing utility-guided stop. Needs the schema lift on the chain record +
  consumer wiring in `build_director_context`.

### F4. Distilled "open-rows-only" handoff instead of the full-plan dump
- `build_director_context` (`loop_controller.py:235-250`) splices the FULL
  `docs/ORCHESTRATION_PLAN.md` + 25 commit lines + 60 ledger + 120 ROADMAP into EVERY
  director call - the deteriorating-context anti-pattern. The plan already carries Status
  fields; filter to OPEN/WIP rows before splicing and cap commit/ROADMAP slices by
  phase-relevance rather than fixed line counts. This is an additive refinement of the
  d8445fec continuity fix, NOT a redo - but it changes what the director sees, so it needs a
  careful before/after de-dup comparison and is operator-reviewable.

### F5. Deterministic-test verifier (ReVeal pattern), not text-diff self-grading
- The full version of N11: the auditor judges from a `git diff` (text), never executing
  the code. The complete fix is a verify step that constructs/runs the tests via the Python
  interpreter and appends `<tool-feedback>` (real pass/fail per case) for the next turn -
  reliability "from deterministic execution checks, not LLM judgment." This is a larger
  architectural lift on top of N11 + N4 and pairs naturally with F1's `--json-schema`
  machine-reported result.

### F6. Per-slice contract block + fan-out sizing rules (Anthropic multi-agent guidance)
- The director mandates "disjoint-file slices" (`director_prompt.md:50-55`) but no per-slice
  CONTRACT (exact file set / output artifact / test it must pass) - underspecified slices
  cause the parallel worktree agents to overlap or leave gaps (Anthropic's documented
  duplicate-work failure). Add a per-slice contract to the emission skeleton and a fan-out
  sizing table (trivial 1-file -> single agent; 2-4 file -> 2-3 agents; schema/multi-scorer
  -> full fan-out), mirroring CLAUDE.md R9. Prompt-side, but couples with N1/N2's skeleton
  rework, so sequence after those land.

### F7. Source-quality + broad-then-narrow heuristic for the research-refill lane
- Refill lane 2 (`director_prompt.md:41-42`) sends the executor to do competitor-lift /
  deep-dive research with no source-quality guidance, risking the content-farm bias for the
  COMPETITOR_LIFT artifacts it produces. Add a one-line heuristic (prefer primary docs /
  source / academic over listicles; verify against the live codebase per CLAUDE.md
  "Verification"). Trivial prompt change, parked as FUTURE only because it depends on the
  REFILL skeleton rework in F6.

### F8. Structured escalation shape for gemini_ask.txt
- The R19 round-trip used free-form `gemini_ask.txt`. Tighten the executor escalation rule
  (`director_prompt.md:23-26`) to a fixed shape:
  `ASK: <decision> | OPTIONS: <A|B> | DEFAULT-I-WILL-TAKE: <X> | BLOCKING: <yes/no>`, with
  the director answering `DECISION: <option> because <one clause>`. Cuts multi-turn
  escalation to one line. Low risk; FUTURE because it is a refinement, not a fix, and best
  bundled with the F6 prompt rework.

## 4. CLOSED lane (considered + rejected, or already shipped - never re-pitch)

### Already shipped (do NOT re-pitch as new)
- **Python controller / DIRECTOR + AUDITOR / AHK bridge / done_sentinel / per-cycle
  /done + /clear** - all live in `ops/loop/`.
- **Newest-first ledger-HEAD digest + persisted directive chain** - commit d8445fec;
  `build_director_context` (`loop_controller.py:223-262`), chain NEVER cleared (`:154`).
- **gemini spend meter + $200 ceiling** - `loop_controller.py:308-327` + `config.json:4`;
  the ceiling caps GEMINI only, Claude is uncapped per operator (`config.json:5`).
- **Two-way escalation channel** - `control/gemini_ask.txt` (read `loop_controller.py:252`)
  + `tools/gemini_ask.ps1` (verified on disk).
- **STOP-file instant abort** - `main()` clears + checks `control/STOP` (`:349`).
- **Orchestrator-merge executor** - 1 merger + up to 100 worktree subagents + read-only
  verifier gate (`.claude/commands/headless-upgrade.md`; mandated in
  `director_prompt.md:51-55`).
- **Same-sha no-progress stop** - `loop_controller.py:417-420`.
- **Dry-run harness** - `claude_stub.py:44-48` (`--hang` / `--regressions`),
  `config.dry-hang.json` / `config.dry-budget.json`.

### Rejected with reason
- **wenyan classical-Chinese output compression** - OUT OF SCOPE; the operator is wiring it
  separately right now. Do not propose.
- **caveman-compress (Python prose-compressor over the plan/WAKEUP)** - MED-HIGH risk: a
  lossy rewrite of the director's PRIMARY work source (`docs/ORCHESTRATION_PLAN.md`, re-read
  every cycle `loop_controller.py:232-248`) can drop a session-id/status the director needs,
  and collides with the no-history-rewrite doctrine (memory `feedback_no_history_rewrite`).
  The safer win is bounding the injected slice (F4), not compressing the canonical file.
- **caveman-shrink (MCP tool-description compression middleware)** - SUPERSEDED by RC's
  ToolSearch / deferred-tool loading (memory `feedback_cc_session_perf`: schemas fetched on
  demand, zero cost until fetched), which is a stronger lever. Redundant.
- **cavecrew subagent triad (investigator/builder/reviewer)** - RC's orchestrator +
  dedicated `verifier` subagent (`.claude/agents/verifier.md`) already EXCEED this; RC's
  verifier is a correctness gate, not just compressed output. Only the terse output FORMAT
  was marginally liftable and RC subagents largely do it already.
- **caveman per-finding severity emoji (4-tier review)** - NO downstream consumer: the loop
  branches only on CLEAN-vs-REGRESS (`loop_controller.py:422`); finer severity is inert.
  (Distinct from the F3 0.0-1.0 score, which DOES get a consumer wired.)
- **Formal caveman lite/full/ultra tier ladder** - cosmetic; RC runs caveman default-on
  fleet-wide already and ULTRA is referenced in prose; a tier selector adds no loop value.
- **caveman config-hierarchy (env -> repo -> user -> 'full')** - RC's loop precedence
  (`loop_controller.py:63-78` cycle_source: override > cycle_command > fixed_directive >
  director) is purpose-built and superior for the loop.
- **DS scorer / Part-2 conditional-target / registry re-pitch** - CLAUDE.md "Settled":
  the 6-scorer plan is fully wired, Part-2 is operator-CLOSED, the registries are
  machine-proven saturated. Out of scope for a loop pass.

## 5. caveman-repo lift table (6-point checklist)

| # | Item | WHAT | HAVE? | WHERE (file:line) | EFFORT / RISK | LIFT |
|---|---|---|---|---|---|---|
| 1 | Multi-intensity output modes | lite/full/ultra selector | Partial (flat caveman + prose "ULTRA") | `tools/caveman.md`; refs `.claude/commands/headless-upgrade.md:167,178` | LOW / LOW | LOW (cosmetic) |
| 2 | caveman-compress (prose -> caveman) | lossy .md compressor | No | target `loop_controller.py:232-248` | MED / MED-HIGH | LOW (collides w/ no-history-rewrite; F4 safer) |
| 3 | caveman-shrink (MCP desc) | compress tool descriptions | No (ToolSearch deferral instead) | N/A | HIGH / MED | LOW (superseded) |
| 4 | Token-savings statusline badge | live `$X.XX` on statusline | No (spend in `/loop-monitor` only) | `.claude/settings.json:96`; `loop_controller.py:308-327` | LOW / LOW | **MED -> NOW N10** |
| 5 | cavecrew subagent triad | terse investigator/builder/reviewer | Yes, stronger (orchestrator + verifier) | `.claude/agents/verifier.md`; `.claude/commands/headless-upgrade.md` | LOW / LOW | LOW-MED (format only) |
| 6 | caveman-review 1-line severity | 4-emoji review format | Auditor binary verdict | `auditor_prompt.md:15-19`; gate `loop_controller.py:422` | LOW / LOW | LOW (no consumer; cf F3) |
| 7 | Config hierarchy | layered mode resolution | Yes, richer | `loop_controller.py:63-78`, `config.json` | LOW / LOW | LOW (superior) |
| 8 | SessionStart mode-flag hook | auto-engage caveman | Wired but TARGET MISSING | `.claude/settings.json:87` -> `tools/caveman_default.py` (absent) | LOW / LOW | **N/A - FLAG -> NOW N12 (live defect)** |

Net: the only genuinely additive, not-already-done, low-risk caveman lift is #4 (statusline
spend badge, now N10). #8 is a live defect (now N12), not a lift. Everything else is
already-have, no-consumer, or superseded by ToolSearch.

## 6. Sources

RC ground-truth (verified file:line this pass):
- `ops/loop/loop_controller.py` (437 lines) - `gemini` 196-219, `build_director_context`
  223-262, DE-DUP RULE 243-247, `director`/`auditor` 264-279, `session_files`/`meter`
  296-327, `main` 348-432, NO_WORK stop 379-380, ceiling 414-415, same-sha 417-420,
  record_directive_outcome 150-168, directive_title 130-148, chain-never-cleared 154.
- `ops/loop/director_prompt.md` (79) - HARD RULES :13, ESCALATION :23, REFILL :30-55,
  FINAL STEP :70-71, push :67-69.
- `ops/loop/auditor_prompt.md` (19) - triggers :5-12, verdict :15-19.
- `ops/loop/done_sentinel.py` (45) - self-reported args :28-42.
- `ops/loop/claude_gui_bridge.ahk` (80) - Target/PID 25-32, WinExist-silent 44-47,
  /clear race 58-67, LINE_PAUSE :18.
- `ops/loop/config.json` (25) - ceiling :4, uncapped-Claude note :5, clear_each_cycle :11,
  session_jsonl :12, claude_window_title :14.
- `.claude/settings.json` - SessionStart hook :87 (dangling), statusLine :96.
- `docs/ORCHESTRATION_PLAN.md` - R28 216-239, R19 299-306; `docs/LEDGER.md:45`.
- `controller.log` - gemini 300s timeout 2026-06-22T13:22:11; frozen-meter dry-run lines.

External best-practice (oss-patterns lane):
- How we built our multi-agent research system - Anthropic
  (https://www.anthropic.com/engineering/multi-agent-research-system)
- Building Effective AI Agents - Anthropic
  (https://www.anthropic.com/research/building-effective-agents)
- Run Claude Code programmatically (headless) - Claude Code Docs
  (https://code.claude.com/docs/en/headless)
- ReVeal: Self-Evolving Code Agents via Iterative Generation-Verification - arXiv 2506.11442
  (https://arxiv.org/html/2506.11442v1)
- AI Agent Handoff: structured memory - XTrace
  (https://xtrace.ai/blog/ai-agent-handoff-why-context-gets-lost-between-agents-and-how-to-fix-it)
- Runtime Budget Guardrails for Agentic AI - Oracle
  (https://blogs.oracle.com/ai-and-datascience/runtime-budget-guardrails-agentic-ai)
- Ground truth in the age of AI agents - Label Studio
  (https://labelstud.io/learningcenter/ground-truth-in-the-age-of-ai-agents/)
- Agentic Loop Design / Building an Agentic Loop with Claude Code - MindStudio
  (https://www.mindstudio.ai/blog/agentic-loop-design-goals-verification-criteria)
