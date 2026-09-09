# ADR-015: Repo-root enumeration in tests goes through `tests/_repo_walk`, tracked-set primary

**Date:** 2026-09-09
**Status:** Accepted

## Context

A guard that sweeps the whole repository has to answer one question before it can
assert anything: **what is the repo?** Every guard that asked it separately
answered it differently.

The census below is `tests/_repo_walk.py`'s OWN docstring (`:5-11`), quoted
rather than freshly measured, and independently re-derived on 2026-09-09 when
this ADR was written: ten guards under `tests/` walked the repo root and each had
grown its own skip set by hand. Four of the ten skipped `_archive` / `.git` /
`node_modules` but NOT `.claude`, and none of those four skipped `python-embed`
(1842 `.py` on disk, ZERO of them tracked) or `moon_sync_inbox` (51 `.py`,
gitignored, sibling-repo mail). A guard whose needle happens not to appear in
vendored bytes is green by luck, not by construction.

`tests/_repo_walk.py` was written that day to end the divergence, and it was
given no record - no ledger row, no ADR, no line in `CLAUDE.md`. The consequence
arrived on 2026-09-09 as RM-394: five guards that had gone on hand-rolling their
own walks were all RED on Legion and GREEN in CI, every one of them tripping on
`ops/runtime/responder_export/<sha>/`, a gitignored FULL COPY OF THE REPO written
by the inbox responder. The row that filed the defect proposed re-deciding the
universe from scratch, because nobody could find the decision that had already
been made. (The module is named in the docs from the RM-394 repair onward -
LEDGER 1376 and the RM-394 row - so "no record" describes the two days that
mattered, not the tree today.) **This ADR exists so that cannot happen a second
time.** The code was never the gap.

Alternatives considered, and why they lose:

- **A per-guard skip list.** This is the status quo that produced the divergence.
  It fails silently the moment a new ignored tree appears under a new name, and
  it fails once per guard: repairing the five RM-394 reds by hand would have
  meant five edits in five hand-lists in five files that do not know about each
  other.
- **`os.walk` minus everything `git check-ignore` claims.** Correct, and it keeps
  untracked-but-not-ignored files in scope. Rejected as the primary on COST
  SHAPE, not on shelling out - the chosen design shells out too, and is saved
  only by the `lru_cache` on `tracked_relpaths()`. One cached `git ls-files` per
  root answers the whole walk; `check-ignore` has to be fed the candidate set,
  which is the thing being enumerated. For the case that actually bites - a
  vendored or exported COPY of the repo - the index gives the same answer.
- **Deleting the offending trees.** Treats the symptom, is destructive, and the
  next runtime export re-creates it.

## Decision

Any test that enumerates the REPO ROOT uses `tests/_repo_walk`, and the universe
is **the git index first, directory-name skips as a backstop**:

- `tracked_relpaths()` reads `git ls-files`, and returns **`None` - never an
  empty set** - when git is missing or the call fails. An empty frozenset would
  filter every candidate out and present as a spotless repo; `None` makes the
  caller fall back to `EXCLUDED_DIRS` instead.
- `EXCLUDED_DIRS` matches path SEGMENTS against the path **relative to the walk
  root**, never the absolute path. Matching absolute parts is a live trap: when
  the checkout itself lives under `.claude/worktrees/<id>/`, every file has
  `.claude` in its parts and the walker returns nothing, which reads exactly like
  a clean tree.
- A guard keeps only the skips that are its OWN scope choice (`{tests, docs}` in
  `test_anthropic_base_url_pin.py`, for example), applied ON TOP of the walker.
  Infrastructure exclusions belong in the shared list and nowhere else.
- **Empty is never clean.** `self_check()` proves the walker still reaches known
  tracked anchors, and any guard whose assertion is empty-set-safe must carry its
  own anti-vacuity arm - see Watch for.

## Consequences

**Good:** one place to fix, one place to audit. The RM-394 repair added
`responder_export` to `EXCLUDED_DIRS` ONCE and covered five guards; the hand-list
alternative would have fixed one of five. New guards inherit the exclusions
rather than rediscovering them, and a guard can no longer be green because its
needle happened to be absent from a vendored tree.

**Trade-off:** a brand-new UNTRACKED `.py` is invisible to these guards until it
is staged. This is deliberate. `git ls-files` reads the INDEX, so a staged file
IS seen, and staged is the state both the commit hook and CI observe - nothing
reaches `main` unguarded. The narrow loss is local feedback on a file created and
not yet added. One arm genuinely needed the old behaviour (the net-new-site
control in `test_anthropic_base_url_pin.py`) and passes `tracked_only=False`
explicitly, which names which half it is proving.

**Watch for:**

1. **An empty-set-safe assertion is the failure mode this decision creates.**
   Converting a guard from a disk walk to the shared walker can turn a
   machine-local RED into a silent always-GREEN, which is worse than what it
   fixed. Measured during RM-394:
   `test_skip_condition_hygiene.py::test_universe_covers_every_test_bearing_tree_in_the_repo`
   asserts `discovered - set(_TEST_TREES)` is empty, which an empty enumeration
   satisfies - forcing the enumeration empty left that module at 56 passed. It
   now anchors on the directory holding the guard itself. **Before converting a
   guard, ask whether an empty enumeration would PASS it, and add an anchor if
   so.**
2. **Adoption is partial, and BOTH holdouts are green by luck - including the
   one that looks safe.** Measured 2026-09-09, two guards still walk the repo
   root without the helper, and neither is safe by construction.
   `tests/test_dead_endpoint_cleanup_item186.py` enumerates **9112** `.py` of
   which **4772 (52 percent) sit inside the gitignored export copies** - its only
   filters, `.claude/` and `/_archive/`, remove ZERO files today. It is NOT green
   because the deleted symbols are absent from those copies: they are present,
   in the export trees' own copy of that very guard file, which its path-exact
   self-exemption does not cover. It is green because no line in those copies
   carries both `import` and a deleted symbol. That is one line-shape away from a
   phantom, and an export tree is a SNAPSHOT of an older repo, so a symbol
   deleted AFTER the snapshot still lives there.
   `tests/test_laning_verdict_flip_retired.py` looks safe because its
   `_SKIP_DIRS` excludes `ops` wholesale, which nobody chose for that reason -
   but it does not skip `python-embed`, and it walks **2082** files of which
   **1685 (81 percent) are vendored `python-embed`**. It is green by luck in
   exactly the way the Context paragraph above condemns. Both filed as RM-395;
   not converted here because this ADR is a record, not a refactor.
3. **A subdirectory walk is not a root walk** and does not need converting.
   `(REPO_ROOT / "web" / "css").rglob("*.css")` is scoped by construction, and
   there are 39 of those against the 2 true root walks. Do not let a grep for
   `rglob` turn this ADR into a repo-wide rewrite - and do not trust a
   single-line grep to find the root walks either: an enumeration split across
   two lines is invisible to one, which is how RM-394 missed a member of its own
   population. Resolve receivers with AST, following alias chains.
4. **`tests/_repo_walk.py` and `ops/loop/slots.py` are different kinds of shared
   file.** This one is ordinary shared test support with no cross-repo byte
   contract; it is not pinned by `SHARED_SHA256` and editing it needs no joint
   act.
