# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

# 2026-09-07d - the channel got a responder program, and every claim RC made about itself was wrong once

Five commits, all pushed: `b129d3845` `e44476d97` `d7833ad1c` `bc4671b56` plus
this wrap. Suite green. Started as "check the moon sync inbox" and became a
five-repo design round plus two shipped modules.

**The operator's requirement.** Siblings must react to a note without operator
interaction while a session is open, else at the next session start. MEASURED
across all five trees: the SECOND half already existed everywhere (all five
have a SessionStart watcher). The FIRST half exists nowhere - `UserPromptSubmit`
needs the operator to TYPE, and the machine-wide poller writes `status.md` that
nothing reads. Demonstrated live twice: notes landed inside an open RC session
and stayed invisible until the operator sent a message.

**Design settled with the channel, four operator decisions.** Full autonomy
(reply AND execute), headless-per-arrival (never the operator's window), NO
stop rule - the trial measures it and consensus follows, and enforcement by a
DETERMINISTIC EXECUTOR rather than a restricted runner.

**Shipped.**
- `tools/rc_facts.py` hook invocation log. Windows `O_APPEND` is seek-then-write
  and LOST 20 of 64 concurrent appends; replaced with a Win32
  `FILE_APPEND_DATA` handle, verified cross-process with a positive control
  (naive 322/2400 lost, shipped 0/2400).
- `tools/inbox_responder.py` A1-A5 validator + decider. 50 arms.

**RC WAS WRONG FOUR TIMES AND EACH WAS CAUGHT BY SOMEONE ELSE OR BY A PROBE.**
1. RC's own A1-A4 allowlist: RSC refuted ALL FOUR entries. A3 was
   manifest-as-key in a costume, handed to an executor instead of a detector;
   A4 was a pin that moves itself, automating the exact softening RC had
   refused BY HAND that morning; A2 treated a test suite as read-only; and D8
   made a compliant responder INERT because replying matched no rule.
2. RC claimed the invocation-log error "propagated to two repositories". RSC
   re-measured both its notes: zero occurrences. It was CS's alone. RC made an
   unmeasured claim inside a note about unmeasured claims propagating.
3. RC's tie-break rule ordered volunteers by note timestamp. Filename stamps
   run AHEAD of arrival - measured at LL +18min, CS +37min, RC's own +3min -
   so filename order was the REVERSE of arrival order. Retired for arrival on
   the receiving disk: one clock, named.
4. RC's own test suite wrote one line per run into the LIVE invocation log
   (7 -> 8, measured). A subprocess cannot be handed `path=`, so it took the
   module default and the default was production. One of those lines had
   already been investigated by RC as a mysterious real fire.

**The single best idea of the round is RSC's and it is not RC's:** under
disposition (i) the spawned session needs NO WRITE AUTHORITY. The draft returns
on stdout; every write happens outside the session by code the session never
ran. RC removed the model's authority to DECIDE; RSC removed its ability to
REACH. A session never handed a destination cannot be talked into one.

**Trial.** RSC volunteered first (arrived 17:59:53) and CS second (18:28:05).
RSC proposed 19:00-21:00 today; RC answered NO, not built, cannot arm, and
endorsed RSC running LATENCY-ONLY (M2/M3 only, M1 recorded INAPPLICABLE). RC
declined to name an hour and named three CONDITIONS instead, because RC had
already been wrong about its own readiness once that day.

**DO NOT REDO.** The A1-A5 list is settled after an adversarial pass - do not
re-litigate it. Disposition (i), the label-travels-in-the-record rule, the
seven termination reasons and M6-at-zero are all accepted. The stop rule is
deliberately UNCHOSEN by operator ruling.

**OPEN, and it is the whole next session.** RC's cycle runner does not exist:
no spawn path, no draft capture, no metrics writer, no headless prompt. The
validator's gates are consequently enforced by NOTHING - which is a scope gap,
not RSC's tested-but-not-enforced defect, and the distinction was stated to
RSC rather than accepting the credit. FOUR NOTES UNREAD at wrap: LW 1813 +
1820 (LW audited RC's public history: "your 11 is exact and your scope
sentence is not"), LL 1830, CS 1905 (yes to the trial, restricted to A1-A2-A3,
A4 refuted again, outbound ratio zero).

# 2026-09-07c - THE FLIP HAPPENED. Remus3/Amberstone is PUBLIC

Operator-gated at the destructive step, autonomous either side of it. Three
commits on the rewritten `main`: `e4083dba6`, `50e4de321`, `39b56742f`.

**PROBED, not assumed:** `gh repo view` -> `PUBLIC` / `isPrivate:false`, and an
unauthenticated `curl` to the repository page returns 200. The verdict in
`docs/PUBLIC_FLIP_GO_NO_GO.md` was written AFTER that probe. Read its "Outcome"
section; everything above it is the pre-flip record, left standing on purpose.

## The acceptance sweep failed first, and that is the value of the session

Two separate defects, one in the instrument and one in the rewrite.

- **The verifier's own pattern had the bug the scrub rule was already fixed
  for.** Unanchored, so it matched the tail of longer words and read
  "gitignored moon_sync_inbox" as a hit. 653 hits, **652 manufactured by the
  instrument**. An instrument and the thing it measures can disagree about a
  rule, and the instrument is not automatically the trustworthy side.
- **A content scrub can be COMPLETE and still publish the names.** The rename
  table was keyed on each file's path at HEAD; the filter callback receives the
  path of whichever COMMIT it is filtering, so every pre-move path went
  unrenamed. **2195 vendor-name hits, none in a blob** - all in tree objects,
  where filenames live. The prior pass's "all purged paths zero" was true and
  useless: eleven named patterns, no vendor name among them.

Widening that sweep to the whole path list found 27 scraped vendor images and
two scraped JSON files no plan had listed. Dropped, not renamed.

## Traps worth carrying

- **A mirror clone DOES fetch `refs/pull/*/head`** - all 13, and 531 commits
  lived on no other ref. Reasoning said otherwise.
- **A ref-pattern check can fail GREEN.** `for-each-ref 'refs/pull/*'` matched
  nothing while 13 existed, then "confirmed" zero with the same broken pattern.
  `for-each-ref` and `ls-remote` do not share a pattern language and neither
  errors on a pattern that matches nothing. Always run the control.
- **Deleting a repo deletes its LFS store.** Seven tip files are pointers; only
  the local 662 MB of objects saved it.
- **A document describing a scrub is INSIDE the scrub's blast radius.**
  `converge.py` found 4 non-fixed-point files, all written at the last wrap.

## CI went red after the flip, on a third instance of the same shape

The citation remap was run over `*.md` only, but several tests use a hardcoded
commit as a LIVE GIT ANCHOR (`git cat-file -e <sha>^:path`). A rewrite renames
every commit, so those anchors died and CI came back **8 failed, 31693 passed**.
Remapped in code too - 207 substitutions, 89 files, 0 dropped - and the verifying
run is green: `check` success, **31701 passed / 262 skipped**, DS **10053
passed**, job RAN (the sibling `nightly-full-suite` is skipped by design).

**One file was REVERTED, not fixed.** `tests/test_loop_status_route.py` writes a
synthetic 18-char sentinel `sha` and asserts on its 8-char truncation, which
collided with a real commit prefix and got rewritten - desynchronising fixture
from assertion. Remap a SHA only where it REFERENCES history, never where it is
opaque test data.

## Open, and deliberately not credited

The NTFS-junction hole in `rc_facts.py` (a one-file drop reports 6 files), RC's
gitignored hook wiring (a fresh clone runs no watcher), and outbound-withdrawal
watching. All three reported to the siblings, none fixed.

## Cross-repo

Two notes delivered byte-identical to all four siblings: the deferred answers to
CS 1013 / LW 1035 / LL 1100, then the correction that RC is public and **their
names ARE in the published history** - 11 hits in 8 historical blob versions of
the two byte-pinned shared modules, stated exactly rather than reassured away.
RC also retracted two of its own claims: the 0700 "Amberstone is PUBLIC" note
was false when written, and "winmutex.py measured clean" was true of the current
version and false of its history.

---

# 2026-09-07b - flip attempt: scrub landed, rewrite proven, repo STILL PRIVATE

Headless, operator away. Four commits pushed, `839604a02..3865c7e34`.
**The repo was NOT flipped. It is PRIVATE, verified at wrap.**

**READ `docs/PUBLIC_FLIP_GO_NO_GO.md` "State at wrap" FIRST.** An earlier
revision of that file claimed the flip had happened and was committed AND
pushed while the repo was private. It was written ahead of the act. Retracted
in `b800c3638`, with the retraction written into the file rather than
overwriting it. The rule it now carries: probe the thing, THEN write the verdict.

**THE DISTINCTION EVERYTHING ELSE HANGS ON:** the scrub claims are true of the
WORKING TREE and false of the REMOTE. `origin` still carries the credential,
120 scraped pages, the vendor dataset and every name - in main's history and in
13 permanent `refs/pull/N/head`.

## Landed and pushed

- Tracked content scrubbed; personal data moved to four gitignored configs with
  tracked `.example` shapes; redistributable data untracked; 9 docs + 4 modules
  renamed. Suites: DS **10856 passed**, RC **21019 passed / 96 skipped**.
- Shared `slots.py` re-pinned to `71fa2a68...` - all three carriers hash equal,
  round CLOSED. A carrier refuted RC's claim that the new wording matches
  `winmutex.py`; it does not, and the retraction is in the pin comment.
- New guard: a withdrawal must STOP being reported after the ack. RC never had
  that bug; RC's five arms all had the blind spot. Mutation-proved.

## Proven, NOT applied

The rewrite ran clean in a mirror - 8083 blobs, 256 messages, 836 paths dropped,
5153 -> 5078 commits, author identity remapped, all purged paths zero - then
verification found ONE surviving case variant. 101 casings were measured across
7GB and the rules corrected. **Re-run it; do not trust the old mirror.**

## Do NOT redo

- The content scrub, the config extraction, the doc/module renames: shipped.
- Both operator decisions: author email NOT published; augment recommender ships
  degraded (the reader already fetches and already degrades).
- Cross-project references are operator-cleared as fine; `slots.py` naming two
  siblings is deliberate.

## The one that changed the plan

`refs/pull/N/head` is permanent and a rewrite never touches it. Operator ruled:
delete and recreate the repo under the same name. Metadata, five bundles and a
LOCAL-ONLY bundle of the PR refs are captured. Never push that last one.

## Health warning on this session's own work

Verification was the weak part, not the rewrite. Six instrument failures: a
scanner that deadlocked twice, a synthetic probe that over-reported, `grep -c`
silently overriding `-o`, a rule table validated by reasoning, a regex disabled
by shell escaping (backslash-b became a 0x08 byte), and a repair applied without
removing its cause. A two-word sibling-name rule whose second word is ordinary
English matched inside unrelated phrases, corrupting `ops/loop/config.json` and
`docs/history_notes.md` mid-word before it was caught. All repaired; the lesson
is that a rules table must be measured against the corpus, never reasoned about.

7 cross-repo notes are UNREAD at wrap - deliberately deferred rather than
interleaved into a half-finished rewrite.

---

# 2026-09-07 - pre-flip transition: licence closed, Share/ gone, verdict NO-GO

Ten commits `cc72e186a`..`9f1441807` pushed to main. LEDGER 1358 has the full
account; this is the hand-off.

**Deliverable: `docs/PUBLIC_FLIP_GO_NO_GO.md`. The verdict is NO-GO.** Three of
five blockers closed. The one that decides it is the name scrub.

**CLOSED.** Licence reconciled to one story (`cc72e186a`) - Apache-2.0 kept
byte-pure with the scope block appended AFTER it so licence detection still
works, new `NOTICE` for the data sources, README's "all rights reserved" gone.
`Share/` removed entirely (`d44c2111b`), 633497 deletions, which also deleted
one of the three contradictory licence statements.

**Suites verified FRESH on main, not inherited:** `tests` 20975 passed / 0
failed; DS 10856 passed / 0 failed.

**DO NOT REDO.**
- Share/ removal is DONE and merged. `tools/ds_share_sync.py`,
  `tools/gist_share_sync.py` and the post-commit gist hook no longer exist.
- The path purge is PROVEN in `C:/rc-purge-staging/` and deliberately NOT
  applied - 7 worktrees are checked out against the live repo and filter-repo
  rewrites every ref. Backup bundle:
  `C:/ClaudeBackup_20260906/rc-pre-purge-20260907-012420.bundle`.
- `tools/rewrite_sha_citations.py` exists and works against a real commit-map
  (1856 remapped / 25 dropped / 0 ambiguous). Do not rebuild it.
- Inbox watcher and the shared poller are both shipped and running. The
  poller ladder was already retuned on operator instruction; do not re-tune it.

**NEXT, and it is a session of its own: the name scrub.**
`docs/PRE_RELEASE_NAME_SCRUB.md` understates itself badly - measured 129 files
/ 34757 occurrences, a tracked FILENAME (`scripts/parse_external_arena.py`), 262
live-read provenance rows in `data/meta_build/arena_champion_builds.json`, and
the name sits in the INITIAL COMMIT's tree so all 5132 commits carry it. Its
"5 commit messages" is 9. **Recommendation: do the name scrub and the path
purge as ONE rewrite** - one force-push, one citation remap, one branch re-cut,
instead of paying that twice.

**RESIDUE:** 10 of 15 root-walking guards in `tests/` have no worktree
exclusion. Only 2 fired this session (because only 2 matched content in the
leftover agent worktree); the other 8 are latent and will fire whenever a
worktree agent exists, which is the default session shape. Also delete
a stray cross-project scaffold branch before any flip - its branch NAME
is a cross-project leak.

**Two operator decisions still open**, both named in the go/no-go: whether to
publish the author email carried in all 5132 commit author fields, and whether
the Arena augment recommender ships with degraded priors once the Overlay App E
snapshots are purged.

## 2026-09-06 - CI unblocked, CodSpeed dropped, and a five-repo review protocol

Nine commits, all pushed. Main was RED since `f8323887e` for a missing CI vision
token - fixed with a CI-only dummy plus a guard that it stays fake. First clean
full run since: 31724 passed, 262 skipped.

**Shipped.** Un-blinded the cross-repo governor guards (LW renamed its root to
`C:\Sibling-A`; RC's `LW_ROOT` still pointed at the old path, so three
guards had been SKIPPING silently - measured 25/3, now 28/0). Dropped CodSpeed
and the five dependents it had. Ported RSC's CI-side glyph sweep as a ratchet.
Fixed the next-session hand-off: it now writes to a TRACKED `RC-NEXT-SESSION.txt`
in the repo root with a Desktop shortcut, gated before the write. Widened the
`stop_claim_gate` to credit CI-log counts. Built a SessionStart inbox watcher.

**The pattern the whole session was about:** a check that is ABSENT reads
identically to a check that PASSED. It appeared eight separate ways - a guard
skipping on a renamed path, a gate skipping its checks, `hold()` logging a
release that never happened, a declared hook with a missing script, a present
script with no declaration, a watcher blind to subdirectories, a payload keyed
on a file count that cannot see a replacement, and two of my own tests passing
vacuously.

**Cross-repo.** Charter v1-v4 with all five repos, broadcast + reviewed. Two LW
dissents and one RSC dissent, all accepted - twice RC generalised from its own
workflow and was corrected by the repo whose constraints it had not modelled.
RC is deadlock adjudicator, scoped narrowly, must disclose when it is a party.

**DO NOT REDO.** CodSpeed is deleted deliberately (docs/OPERATIONS.md "Why
CodSpeed was dropped"). The winmutex rotation and the `hold()` leak fix are
pinned at `0b112a4f` / `629c3d51` across all three carriers. Caveman is
operator-settled, not a live dissent.

**Open.** Slot round (reserved floor per repo) blocked on the `repo=` key
agreement plus CS/LL saying in-or-out. Pre-public flip has four audit blockers.
`Share/` removal is scope B - 548 files, 46 test modules. RC's verbatim drop
carried operator PII in 19 of 48 files and was PULLED from all four inboxes;
a redacted re-drop is next-session work.
