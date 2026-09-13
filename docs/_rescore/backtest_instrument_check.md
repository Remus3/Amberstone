# Instrument check on RC's refutation-gate back-test

Read-only, 2026-09-12. Applies the sibling (LL) methodological defect to
`docs/REFUTATION_GATE_BACKTEST_2026-09-12.md` and its source
`docs/_scratch_backtest_A.md`. No tracked file edited. Every sha below was
verified with `git cat-file -t` and returned `commit`.

## 0. The test being applied

LL reported that running a pre-flight at the parent of each commit that FILED a
finding caught 0 of 17, and that 0 was an instrument defect rather than a
verdict: a new test module, its registration and its ledger entry all land in
ONE commit, so the tree in which the registration was missing was never
committed. Rebuilding from the fix commit's own additions caught 9 of 9.

The question for RC: for each of its 7 located instances, DID THE DEFECTIVE
STATE EVER EXIST IN A COMMITTED TREE THAT GIT CAN ADDRESS?

RC's back-test already concedes part of this in its LIMITS 5 ("the dispatch
artifact does not exist on disk for instances B, C and D"). That is the
starting point, not the answer, because LIMITS 5 does not say what it costs.

## 1. Per-instance addressability

Each row has TWO resolver inputs: the ROW (the claim text a resolver reads
tokens out of) and the TREE (the state those tokens are resolved against).
Addressability has to be graded on both.

| # | Verdict | Row input committed? | Tree input committed? | Addressability |
|---|---|---|---|---|
| A | MISSED | YES `BACKLOG.md:188` | YES same blob | **ADDRESSABLE** |
| B | CAUGHT | NO relayed inbound note | YES | **PARTIAL** |
| C | CAUGHT | NO loop directive | YES | **PARTIAL** |
| D | CAUGHT | NO hand-off prompt | YES | **PARTIAL** |
| E | PARTIAL | YES `ROADMAP.md:41` | YES | **ADDRESSABLE** |
| F | MISSED | YES `BACKLOG.md:255` | YES | **ADDRESSABLE** |
| G | MISSED | YES `BACKLOG.md:257` | YES | **ADDRESSABLE** |
| H, I | UNGRADEABLE | - | - | never enumerated |

### 1.1 The four ADDRESSABLE instances, proved

For each, the defective row was introduced by one commit and corrected by a
DIFFERENT, later commit, so it sat in committed trees for a measurable period.
LL's single-commit create-and-correct defect does not apply to any of them.

| # | Row text | Filed at | Shipped at | Commits in between |
|---|---|---|---|---|
| A | `RM-217 OPEN (filed 2026-08-15...` | `b73f0fde6` 2026-08-15 | `59eeea064` 2026-09-12 | **518** |
| E | `RM-386 SECOND HALF OPEN (filed 2026-09-08...` | `fc0be1320` 2026-09-08 | `8aa2b81f1` 2026-09-08 | 6 |
| F | `RM-394 FILED 2026-09-09...` | `73e1e88db` 2026-09-09 | `57ecfeb82` 2026-09-09 | 4 |
| G | `RM-385 OPEN (filed 2026-09-08...` | `fc0be1320` 2026-09-08 | `8315ea33b` 2026-09-08 | 9 |

Commands used, per row: `git show <shipping>^:<path> | sed -n '<N>p'` returns
the defective text, and `git log --oneline -S"<row prefix>" --reverse -- <path>`
returns the introducing commit as the FIRST entry and the shipping commit as the
SECOND. All four printed exactly two commits, which is the proof that the row
was not created and corrected inside one commit.

The refuting fact was also committed and CO-RESIDENT with the stale row in each
case:

- **A** - `git show 59eeea064^:BACKLOG.md | sed -n '292p;294p'` prints
  `RM-398 PARTIAL SHIPPED 2026-09-10` and `RM-396 REFUTED 2026-09-09` in the
  SAME blob as the stale `RM-217 OPEN` at `:188`.
- **E** - `_emit_bounce` was introduced at `b291b9a72` (2026-09-08), 4 commits
  before `8aa2b81f1^`, while the row asserting the silence was already live.
- **F** - `git grep -l "_repo_walk" 57ecfeb82^ -- tests` returns **6** paths.
  `tests/_repo_walk.py` was introduced at `a0a23b57c` (2026-09-07), TWO DAYS
  before the row that asks the question it already answers was filed.
- **G** - `git show 8315ea33b^:BACKLOG.md | sed -n '256p'` prints
  `RM-386 SECOND HALF SHIPPED 2026-09-08 - a refusal is no longer an answer`
  on the line IMMEDIATELY ABOVE the stale row at `:257`. The two coexisted
  across 3 addressable trees (`git rev-list --count 8aa2b81f1..8315ea33b^` = 2,
  plus `8315ea33b^` itself, which is `8971bcee4`).

A resolver run at any of those commits would have seen the real input on both
sides. The MISSED verdicts are therefore verdicts, not instrument artifacts.

### 1.2 The three PARTIAL instances

For B, C and D the TREE side is committed and was queried correctly; the ROW
side never existed in any committed tree.

- **B** - the artifact is a relayed inbound note. `git check-ignore -v
  moon_sync_inbox` returns `.gitignore:201:moon_sync_inbox/`, and
  `git ls-files moon_sync_inbox` returns **0**. The channel is gitignored BY
  DESIGN, so no relayed note is addressable, ever. R3's input was the relay's
  ten quoted figures, which exist nowhere in this repository's history.
- **C** - the artifact is a loop directive. The tree half is clean and provable:
  `git grep -c "NamedMutex" 44877b548^ -- '*.py'` returns EMPTY. But the token
  `NamedMutex` reaches the resolver only from the directive, which is untracked.
  Report A already flags that whether the directive named RM-407 and RM-399 BY
  ID "is not recoverable from the tree", which is precisely this defect.
- **D** - the artifact is a `/done` hand-off prompt. Searched directly:
  `git show a74a75dc4^:WAKEUP_NOTES.md | grep -n "RM-38[78]"` returns NOTHING,
  and the only `fallback` hit in that blob is an unrelated prose line about a
  shell `|| echo 0`. The preceding wrap `10c67b7c6` (a confirmed ancestor of
  `a74a75dc4`) likewise carries no FALLBACK section. **The stale FALLBACK naming
  RM-387 and RM-388 was never committed.** The earliest committed mention of it
  is `9be24afa1`, which is AFTER `a74a75dc4` and is a description of the defect
  written by the burned session, not the artifact.

## 2. Corrected tallies

**Of RC's 3 CAUGHT (B, C, D): ZERO were graded end-to-end against a state git
can address.** All three are PARTIAL - correct tree, reconstructed row. The row
half in every case is a secondhand account written after the fact.

**Of RC's 3 MISSED (A, F, G): 3 of 3 are MISSED for a real reason.** Row and
refuter both sat in committed trees, together, for 518 / 4 / 9 intervening
commits respectively. None is an artifact of the instrument.

**The 1 PARTIAL (E) is fully ADDRESSABLE and stands unchanged.**

Corrected table:

| Class | Published | After the instrument check |
|---|---|---|
| CAUGHT on an addressable state | 3 | **0** |
| CAUGHT on a reconstructed row, addressable tree | - | **3** (B, C, D) |
| MISSED for a real reason | 3 | **3** (A, F, G) |
| MISSED as an instrument artifact | - | **0** |
| PARTIAL, addressable | 1 | **1** (E) |
| UNGRADEABLE | 2 | 2 |

**The defect runs the OPPOSITE way from LL's.** LL's non-addressable states
produced false MISSES, so fixing the instrument INVERTED their result from 0/17
to 9/9. RC's non-addressable states sit entirely in the CAUGHT column, so the
same defect cannot rescue a single RC miss. It can only put pressure on RC's
catches. RC's result does not invert.

## 3. LL's alternative construction, applied

Rebuild the defective state from the fix commit's OWN ADDITIONS instead of from
the parent tree.

- **D - it CORROBORATES, and this is the strongest single result here.**
  `git show a74a75dc4:tests/test_roadmap_backlog_disposition_drift.py` lines
  14-24 name `RM-387` and `RM-388` in its own docstring as rows where "ROADMAP
  said OPEN, BACKLOG said SHIPPED". Independently, the tree at `a74a75dc4^`
  carries `RM-387 SHIPPED` / `RM-388 SHIPPED` in BACKLOG and `RM-387 OPEN` /
  `RM-388 OPEN` in ROADMAP. So the DISAGREEMENT that R4 fires on WAS in a
  committed tree even though the prompt that pointed at it was not. D is the one
  instance where LL's construction upgrades the evidence rather than only
  restating the limit. **Verdict unchanged: CAUGHT.**
- **B and C - it cannot be applied.** The fix commits add ledger prose, not the
  relayed note or the directive. Reconstructing a row from a later summary of it
  is the very thing LL's construction avoids: LL rebuilt from the ARTIFACT's own
  bytes landing in the fix commit. No such bytes exist here. **Verdicts
  unchanged but downgraded in confidence to PARTIAL-addressable.**
- **A, F, G, E - it changes nothing.** The fix commits' additions ARE the
  refutation text, and the refutation names the thing the row omits. Feeding it
  to the resolvers changes no verdict, because the resolvers read the ROW, and
  the row is unchanged. Re-derived independently for this file, at the pick-up
  blobs:

  | # | Predicate | Count |
  |---|---|---|
  | A | row at `BACKLOG.md:188` names `RM-396` or `RM-398` | **0** |
  | E | row at `ROADMAP.md:41` names `_emit_bounce` | **0** |
  | F | row at `BACKLOG.md:255` names `_repo_walk` | **0** |
  | G | row at `BACKLOG.md:257` names `RM-386` | **0** |

  Four zeros. The defect is what the row does NOT carry, and no reconstruction
  of the row from its fix can put the missing token into it without ceasing to
  be the row.

## 4. Three-way verdict

### 4.1 The structural finding - SURVIVES, and is STRENGTHENED

"Every one of the five resolvers is a PRESENCE check over tokens the row NAMES;
the defect class is an ABSENCE" is the one conclusion this check makes stronger.
It rests entirely on the four FULLY ADDRESSABLE instances - the ones LL's defect
cannot touch - and its four zero-counts were re-derived here from historical
blobs rather than inherited. It does not depend on any reconstructed artifact.

### 4.2 The MISSED tally, 3 - SURVIVES

3 of 3 graded against committed trees in which both the stale row and its
refuter were present simultaneously. A sat 518 commits. No miss is an artifact.

### 4.3 The CAUGHT tally, 3 - WEAKENS

Not refuted, but it must never again be stated as "3 CAUGHT" without the
qualifier. Every catch is a counterfactual over a row reconstructed from a
later account of it. D is materially better than B and C because the fix
commit's own test docstring independently attests the ids and the tree carries
the disagreement; B and C rest on ledger prose alone. The honest restatement is
**0 of 3 catches were graded end to end against a git-addressable state; 1 of 3
(D) has independent corroboration from the fix commit's additions.**

Two consequences for the published file:

1. LIMITS 4 says the parent-of-shipping-commit approximation "for the CAUGHT
   ones could only help". That is too generous. For B, C and D the approximation
   is not merely imprecise - there is no commit at which the artifact existed,
   so no choice of pick-up commit improves it.
2. LIMITS 5 states the fact but not its cost. The cost is that the catch rate,
   and only the catch rate, is unfalsifiable from this repository's history.

### 4.4 Overall

**RC's published conclusion SURVIVES in its structural half and WEAKENS in its
numeric half.** The catch rate of 3 of 7 should be read as "3 counterfactual
catches on reconstructed artifacts, 3 measured misses on committed trees". The
recommendation's direction is unaffected: the check makes the evidence FOR the
gate softer and leaves the evidence AGAINST it exactly as hard as it was, which
moves the file's overall verdict further from the gate, not toward it.

## 5. Limits of this check

1. Absence of the artifact from git is not proof it never existed on disk. It
   proves only that no gate back-test can ever be run against it here.
2. "Committed tree" is graded over this repository only. A directive or relay
   may be committed in a SIBLING repository; that was not probed and is out of
   scope for a read-only pass on RC.
3. H and I stay UNGRADEABLE. They were never enumerated, so they are outside
   both the original back-test and this check.
4. n = 7, one repository, a 2026-08-15 to 2026-09-12 window.
