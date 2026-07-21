# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-21k - R160 PERCENT-PENETRATION CATALOG PARITY (gemini headless loop, cycle 7) - ENGINE UNCHANGED 1.237.0

LEDGER 1001. Commit `d6d3fb3f`. ENGINE-IMPACT NONE - no math change, no production `.py` touched,
no `ENGINE_VERSION` bump, no DS bounce, no RC restart.

## What shipped

`agents/daemon_slayer/tests/test_pen_pct_catalog_r160.py` - a catalog-derived parity guard for the
PERCENT penetration axis. The directive asked for a pen sweep across percent armor pen, lethality
and magic pen; R152 had already closed lethality (31 exact-match, 0 absent) and R153 had already
closed FLAT magic pen with a permanent guard. The premise check found the one third nobody swept:
`armor_pen_pct` / `magic_pen_pct` had no catalog-derived test at all.

Three read-only agents on disjoint scopes - two catalog to registry, one running it BACKWARDS
(registry to catalog, the direction that catches a credited id the catalog dropped). All three
converged: **zero uncredited live ids on either axis.** 12 armor-pct swept (6 exact), 9 magic-pct
(7 exact), 16 credited rows, 0 stale. Every population was re-derived independently against both
catalog layouts before a single assertion was written.

## The three divergences are pinned, not fixed

- `223036` / `226694` state 40 percent in the Arena feed, registry credits their SR twins' 35.
- Terminus `3302` / `223302` state a PER-STACK value (10 SR, 8 Arena) vs a full-stack credited 0.30.
- `6632` / `226632` state 3 percent from dead mythic-template text but are unbuyable everywhere.

## The test failed first, and the failure was the finding

The draft asserted the flat and percent sweeps are disjoint by id. RED on `3175` Spellslinger's
Shoes, which states BOTH `18 Magic Penetration` and `8% Magic Penetration` on consecutive rows -
DS credits both axes correctly. They are disjoint by MAGNITUDE, never by id. Now pinned.

## Gates

Verifier CONFIRM 8/8 with live-object defect injection (baseline 0 failures; `3135` pen to 0.0
gives 2; `3036` to 0.99 gives 1; restored 0), and it caught a wrong docstring path fixed
pre-commit. DS 9190 passed / 1 skipped / 3865 subtests. Guard 17 / 28 subtests. ruff clean,
0 non-ASCII, zero production mutation. Share `--check` in sync 1.237.0 / 497 files.

## Carry-forward

The Arena-inheritance doctrine call is now 12 rows across three sweeps (R152 7 lethality, R153 2
flat magic pen, R160 2 percent armor pen + Terminus). Escalated to the director via PART C
`gemini_ask.txt` with both options and their blast radius. Do NOT reconcile any of those rows
without the answer - the guard will go red by design if someone tries.

---

# 2026-07-21j - R159 RUNE-OFFENSE SATURATION, REMAINING THREE TREES (gemini headless loop, cycle 6) - ENGINE UNCHANGED 1.237.0

LEDGER 1000. Merge `add6f26f` (slice `77d448af`). ENGINE-IMPACT NONE - no math change, no behavior
change, no `ENGINE_VERSION` bump. The default-OFF `apply_rune_offense_grants` path stays
byte-identical. No DS bounce, no RC restart: there is nothing to reload.

## What shipped

R158 closed Domination `8100` + Sorcery `8200` and recorded the carry-forward that Precision
`8000`, Resolve `8400` and Inspiration `8300` were still PROSE-ONLY. This closes them.
`_SATURATED_TREE_IDS` in `agents/daemon_slayer/tests/test_rune_offense_saturation_r158.py` is now
all five trees, so the module docstring's saturation claim is a thing CI can fail on rather than a
sentence. Coverage: 62 live runes = 5 registered (`8010`, `8233`, `8236`, `8316`, `9104`) + 57
adjudicated, up from 23, counted by a new test rather than eyeballed.

## The point of the slice is the two honest non-answers, not the 32 easy ones

A guard whose reasons are wrong is worse than no guard - it converts an unmeasured claim into a
green test. Two of the 34 new ids DO grant a real offensive stat, and both are recorded as blocked
gaps naming the blocker, following the `8232` Waterwalking precedent:

- **`8008` Lethal Tempo - ROLE-BLOCKED.** It grants stacking attack speed (6% melee / 4% ranged per
  stack to 6 stacks). The value is role-split and this seam takes no melee-or-ranged argument, AND
  that same bonus attack speed is already an INPUT to Lethal Tempo's own on-attack damage term in
  `rune_procs.py`. Crediting it here independently would DOUBLE-COUNT, not close a gap. The two
  lanes have to be wired together.
- **`8313` Triple Tonic - UPTIME-BLOCKED.** Its level-6 Elixir of Force grants 25 Adaptive Force,
  but for 60 seconds once, and this engine has no consumable-uptime anchor to spend that against.
  Its two siblings grant nothing offensive (Elixir of Avarice is gold plus minion-only true damage,
  Elixir of Skill is a skill point).

The other 32 are plain non-grants, each grounded in the rune's own DDragon `longDesc` and, where
applicable, an existing registration elsewhere: `8005`, `8014`, `8017`, `8299`, `8369`, `8437`,
`8439`, `8401` cite `rune_procs.py`; `8439`, `8429`, `8242` cite `_rune_resist_grants.py`; `8446`
Demolish and `8021` Fleet Footwork cite the explicit honest-exclusion notes already in
`rune_procs.py` (tower-only damage, and a heal whose AD/AP appear only as scaling INPUTS); `9105`
Legend: Haste and `8347` Cosmic Insight use the settled MEASURED-INERT ability-haste wording;
`8451` Overgrowth and `8345` Biscuit Delivery say health is not one of this registry's three
columns rather than falsely claiming no offensive stat.

## Verification

TDD RED recorded before the mapping landed: `2 failed, 9 passed, 52 subtests` -
`AssertionError: 28 != 62` on the new counting test, plus a 34-element diff naming every uncovered
id starting at `('8005', 'Precision/PressTheAttack')`.

Verifier subagent CONFIRM 8/8, re-running the DS suite itself rather than taking the slice's
numbers: `_ADJUDICATED_NON_GRANTS` resolved by AST `literal_eval` (57 keys, no silent dict-literal
collapse), `ENGINE_VERSION` diffed against main to prove it untouched, and - the claim that
mattered - the `longDesc` for `8008`, `8021`, `8299`, `9103`, `8451`, `8446` read out of the feed
and compared against each reason string to hunt for a false non-grant.

DS 9173 passed / 1 skipped / 3837 subtests (verifier's own fresh run, exit 0). ruff
`All checks passed!`. 0 non-ASCII bytes in both sources and both Share mirrors. Commit is exactly 5
files with 0 deletions. `test_no_adjudicated_id_credits_anything_on_its_own` grew to 114 subtests
(57 x 2), which is what proves the mapping inert on both an AD and an AP build. Share mirror +
`MANIFEST.md` restamp landed in the SAME commit via the precommit hook; `--check` in sync at
1.237.0 / 496 files.

The slice agent hit the known worktree-index corruption right after committing (~500 phantom staged
deletions). `git reset` repaired it; both the agent and the verifier re-confirmed the commit is
still the same 5 files with everything present on disk.

## Don't-redo

All five rune trees are now machine-guarded and the sweep is CLOSED. A future patch that adds a
stat rune will fail the guard by itself, so do NOT re-scan the feed for uncovered runes.

`8008` Lethal Tempo and `8313` Triple Tonic are KNOWN, RECORDED gaps with named blockers, not
oversights. Crediting Lethal Tempo needs the attack-speed lane wired to its existing `rune_procs.py`
damage term (double-count hazard); Triple Tonic needs a consumable-uptime anchor that does not
exist. Neither is a free win.

---

# 2026-07-21i - R158 RUNE-OFFENSE SATURATION GUARD (gemini headless loop, cycle 5) - ENGINE UNCHANGED 1.237.0

LEDGER 999. Merge `b3085653` (slice `3deb619d`). ENGINE-IMPACT NONE - no math change, no behavior
change, no `ENGINE_VERSION` bump, diff purely additive (77 lines, 0 deleted). No DS bounce, no RC
restart: there is nothing to reload.

## What shipped

The directive asked for "raw AD/AP grants for Domination and Sorcery" and named five runes. All
five were refuted against `data/meta_build/ddragon/16.14.1/runesReforged.json` before any code was
written. Eyeball Collection `8138`, Zombie Ward and Ghost Poro `8120` are ABSENT from 16.14.1 -
Domination slot 2 is Sixth Sense / Grisly Mementos / Deep Ward, slot 3 is Treasure Hunter /
Relentless Hunter / Ultimate Hunter. `8126` is Cheap Shot (proc damage). `8234` is Celerity (move
speed only); Absolute Focus is `8233` and shipped with `8236` in R145. Both cited PATHS were wrong
too - the module is `agents/daemon_slayer/_rune_offense_grants.py`, not `core/`, and the feed is
under `data/meta_build/ddragon/`, not `data/daemon_slayer/`.

Sweeping all 25 runes across both trees came back SATURATED: 2 registered, 23 already adjudicated
(proc damage / move speed / ability haste on the settled measured-inert axis / gold / trinket haste
/ ward / vision / heal / mana / ult-amp), plus `8232` Waterwalking, which grants real Adaptive Force
but is uptime-blocked on river occupancy with no anchor in this engine. Zero uncovered grants.

So the artifact is a GUARD, not a grant. The saturation claim lived only in the module docstring's
prose exclusions - which cannot fail CI when a patch adds a stat rune, and which is exactly how a
directive came to spend a cycle chasing three runes deleted from the game. Added
`_ADJUDICATED_NON_GRANTS` (23 ids -> the verbatim existing reasons) beside the 5-entry registry, and
`agents/daemon_slayer/tests/test_rune_offense_saturation_r158.py` (7 tests / 52 subtests): every
rune registered OR adjudicated with the offending id named on failure, sets disjoint, **every
adjudicated id still EXISTS in the feed** (the check that catches this directive's own error class),
ASCII reasons, and byte-identical credit between the full 25-id list and `[8236, 8233]` alone. TDD
confirmed by a pre-mapping `ImportError`.

## Gates

Verifier 10/10 CONFIRM, re-running both suites itself: `git diff --numstat` `77 0` / 0 deleted
lines, `ENGINE_VERSION` untouched, 0 non-ASCII in 53956 + 9156 bytes, 23/5 disjoint by real import,
no `Share.zip` / `_scratch/` / mass-deletion in the commit. DS 9169 passed / 1 skipped / 3769
subtests post-merge. ruff clean. Hygiene 13/13. Share `--check` in sync at 1.237.0 / 496 files -
mirror + `MANIFEST.md` restamp landed in the SAME commit via the precommit hook's own sync run.

## Carry-forward

Precision, Resolve and Inspiration are still prose-only. Precision is the live risk: `9105` Legend:
Haste and `9103` Legend: Bloodline sit unguarded beside the registered `8010` Conqueror and `9104`
Legend: Alacrity - the same shape this cycle just closed for two trees. That is the obvious R159.

---

# 2026-07-21h - R157 HEXCORE OFFLINE EXPLORER (gemini headless loop, cycle 4) - ENGINE UNCHANGED 1.237.0

LEDGER 998. Pushed `fc8199c9..d2f87add` (`9403b8ca` html + `d2f87add` docs sync). ENGINE-IMPACT
NONE - `docs/HEXCORE_offline.html` is a standalone offline artifact; no DS math, no served path,
no Share mirror delta, no DS bounce, no RC restart.

## What shipped

The directive asked for the same unit R151 already executed, and its NOT-A-DUPLICATE line was
wrong: it claimed R155/R156 shipped net-new `.py` files. They did not - R155 widened an existing
`(ad, ap)` tuple to `(ad, ap, attack_speed_fraction)` inside `_rune_offense_grants.py` and R156
appended a census function to that same existing file. Diffing R151's OWN merge point (`79c3deba`)
instead of the directive's inherited `d584e02e` baseline, additions only, minus tests, minus
`Share/`, returns exactly ONE path: `ops/loop/adjudicator.py`.

The gap worth fixing was bigger and was not what the directive asked for: the whole `ops/loop/`
subsystem - the autonomous loop that AUTHORS these directives - had zero representation in the
explorer. Added node `o_headlessloop` plus dust leaves for `loop_controller.py`, `adjudicator.py`,
`done_sentinel.py`, `claude_stub.py`.

Stale anchors resynced at every site, not just the obvious one: `nodes: 141` -> 142 lives in FOUR
places (HUD row, header lede, `sr-only` h2, `noscript` fallback) and `325 dust` -> 329 in FOUR
(those three plus a machine-read comment). Also ENGINE 1.233.0 -> 1.237.0 and 9087 -> 9162 DS
tests in both the HUD tooltip and the DAEMON_SLAYER.md node desc, LEDGER entry 989 -> 997,
commits 3789 -> 3823.

## Two lessons worth carrying

**A verifier gate only checks the claims you thought to make.** The 11-claim verifier returned
11/11 CONFIRM and even re-ran the DS suite itself rather than taking 9162 on faith - but it never
knew about `tests/test_hexcore_offline_dust.py`, an 11-test pre-existing guard that pins a
machine-readable `// DUST: N real extra source files` comment as the DECLARED count and
cross-checks it three ways. The visible-text edit left that comment at 325 and the full RC suite
failed 3/3. Green verifier is not a substitute for the suite.

**The visual capture earned its cost on a docs-only change.** The browser render is what caught
the header lede still reading 141 while the HUD beneath it read 142 - a mismatch invisible to the
grep that had just "fixed" the count.

## Gates

DS 9162 passed / 1 skipped / 3717 subtests. RC 12545 passed / 23 skipped / 406 subtests (first
run 3 failed / 12542 passed - exactly the hexcore guard - then re-run end to end after the fix
rather than reporting a patched number). ruff clean. Hygiene 13/13. Verifier 11/11 CONFIRM.
`node --check` exit 0 on both extracted inline script blocks. 0 non-ASCII bytes.

## Don't-redo

HEXCORE is CURRENT as of `9403b8ca`. Do NOT re-run a "net-new .py since `d584e02e`" sync - that
baseline now yields zero real work and manufactures a duplicate of R151/R157. Diff from
`9403b8ca` forward, and remember the count lives in five places including the machine-read
`// DUST:` comment.
