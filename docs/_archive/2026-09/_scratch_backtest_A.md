# Back-test A: does RC's Q4 pre-dispatch re-grounding gate catch the nine it names?

Read-only measurement, 2026-09-12. No tracked file edited. `git check-ignore -v
docs/_scratch_backtest_A.md` exits 1 with no output, so this path is NOT gitignored -
it is an untracked new file in a tracked directory.

Target of the test: section 3 "Q4" of `docs/REFUTATION_COST_MEASUREMENT_2026-09-12.md`
(the five resolvers at `:322-330`, the instance list at `:339-355`).

## 0. First measurement, before any instance

The doc says "at least nine instances" and then enumerates **seven** bullets
(`docs/REFUTATION_COST_MEASUREMENT_2026-09-12.md:339-355`, derived this run by counting
`^- ` bullets in that range: 7). Two of the nine are never named, so they cannot be
located, reconstructed or graded. They are recorded UNGRADEABLE below and are not
counted as misses.

## 1. Table

| # | Instance (doc wording, abbreviated) | Primary evidence | Pick-up moment (tree as it stood) | Resolver that fires | Verdict |
|---|---|---|---|---|---|
| A | row worked whose sibling row refused it by name, same file, 28 days | `docs/LEDGER.md:71` (entry 1406); `BACKLOG.md:188` (RM-217 OPEN) and `:292` / `:294` (RM-398, RM-396) at `59eeea064^` | `59eeea064` (2026-09-12), tree `910cf8204` | NONE | **MISSED** |
| B | relayed inbound finding already fixed at an ancestor commit | `docs/LEDGER.md:75` (entry 1405); closure `c00b9af89` (LEDGER 1392) | `4f5158a5b` (2026-09-12), tree `86e4d4f0f` | R3 (quoted count re-derived) | **CAUGHT** |
| C | pre-flight triage killed 5 of 5 directive claims | `docs/LEDGER.md:103` (entry 1398), code sha `44877b548` | `44877b548` (2026-09-11) | R2 (named symbol exists) | **CAUGHT** |
| D | hand-off FALLBACK named two rows shipped 3 days earlier | `docs/LEDGER.md:130` (entry 1389); `tests/test_roadmap_backlog_disposition_drift.py:18-19` | `a74a75dc4` (2026-09-11) | R4 (superseding closure) | **CAUGHT** |
| E | row two-thirds stale on arrival | `docs/LEDGER.md:174` (entry 1366); `ROADMAP.md:41` at `8aa2b81f1^` | `8aa2b81f1` (2026-09-08) | R3, literal reading only | **PARTIAL** |
| F | row posed as open a question already answered in code | `docs/LEDGER.md:152` (entry 1377) and `:154` (entry 1376); `BACKLOG.md:255` at `57ecfeb82^` | `57ecfeb82` (2026-09-08) | NONE | **MISSED** |
| G | proposed disposal was what a sibling row had just stopped doing | `docs/LEDGER.md:172` (entry 1367); `BACKLOG.md:257` at `8315ea33b^` | `8315ea33b` (2026-09-08) | NONE | **MISSED** |
| H | (never enumerated) | - | - | - | **UNGRADEABLE** |
| I | (never enumerated) | - | - | - | **UNGRADEABLE** |

## 2. Per-instance predicate, written out, on the record as it stood

### A - RM-217 vs RM-398. MISSED.

Row at pick-up: `git show 59eeea064^:BACKLOG.md` line 188, `RM-217 OPEN (filed
2026-08-15)`. Its ACCEPTANCE asks for "a `RETRACTED:` marker the scanner honours when
it appears in a LATER assistant message naming the same figure". Line 292 of the same
blob carries `RM-398 PARTIAL SHIPPED 2026-09-10`; line 294 carries `RM-396 REFUTED
2026-09-09`, whose closing text rejects "a retraction token (a self-serve silencer)".

Resolver by resolver, each run against `59eeea064^`:

- **R1 citations.** The row cites `tools/stop_claim_gate.py:38` and `:43-46`.
  `git show 59eeea064^:tools/stop_claim_gate.py | sed -n '36,48p'` puts `CLAIM_COUNT`
  at exactly `:38` and the `CLAIM_COUNT_ORDINAL` frozenset members at exactly `:43-46`.
  Concrete output: both citations CONFIRM. R1 does not fire.
- **R2 symbols.** `CLAIM_COUNT`, `CLAIM_COUNT_ORDINAL`, `_scan` all present. Does not fire.
- **R3 counts.** The row quotes "three unbacked test counts" about a past session, not a
  figure the work depends on. Re-deriving it changes nothing about the acceptance.
- **R4 ids.** The row names exactly two ids: RM-215 (already refuted at filing, and the
  row says so) and itself. RM-217 carried NO superseding closure - it was still `OPEN`
  at pick-up and was closed BY this session. RM-396 and RM-398 are ids the row never
  names. Does not fire.
- **R5 instruments.** `tools/stop_claim_gate.py` and `ops/runtime/` exist. Does not fire.

**Nothing fires.** The finding required matching the prose "a `RETRACTED:` marker the
scanner honours" against the prose "a retraction token (a self-serve silencer, only
defensible if evidence-bearing)" - two different wordings of one mechanism, in two
rows with different ids. That is semantic equivalence over English, not a lookup.

This is the doc's own leading example of its highest-cost class, and its own gate does
not catch it.

### B - RM-420 relayed finding. CAUGHT (R3), with a caveat.

Entry 1405 records that the relay's 10 figures reproduce
`tests/test_suite_does_not_write_live_tree.py:100-166` and that RM-406 had closed the
defect at `c00b9af89`, an ancestor of HEAD.

Concrete input: 10 quoted figures arriving in prose from outside this tree. Concrete
output of R3 applied literally: none of the 10 is labelled inherited, none is derivable
from this tree at dispatch time, so dispatch is REFUSED until they are re-run. Re-running
them (the session did: tracer 0 files / 0 tests / 0 units) contradicts the relay.

**Adversarial check.** R3 fires as a REFUSAL, not as a diagnosis. The gate says "go
re-derive these 10 numbers"; re-deriving them is exactly the work RM-420 performed. So
the gate reclassifies the session from "build" to "verify" - which is a real saving,
because the alternative was building a fix for a closed defect - but it does not make
the verification free. Graded CAUGHT, not free.

Note also that R4 is structurally unable to help here: an external relay carries no RC
work-item id, so there is nothing for R4 to resolve.

### C - RM-234 pre-flight triage. CAUGHT (R2), cleanest catch in the set.

Entry 1398 lists five killed directive claims. One is mechanically decidable with no
prose reading at all: the directive proposed putting `PolledJsonFile` onto `NamedMutex`.

Concrete input: the symbol `NamedMutex`. Concrete output, run this session against the
record as it stood: `git grep -n "NamedMutex" 44877b548^ -- '*.py'` returns **empty**,
and `git show 44877b548^:ops/loop/winmutex.py | grep -n "^class \|^def "` returns exactly
`class MutexTimeout(RuntimeError)` at `:46` and `def hold(...)` at `:51`. The class the
directive proposed building on did not exist anywhere in the tree.

**Adversarial check.** R2 is a pure existence predicate over a token; no judgement.
It fires. But it fires on ONE of the five claims. Of the other four: two ("orphan-tree
wiring = RM-407", "split-form sibling scanner = RM-399, ALREADY SHIPPED") are R4-shaped
only IF the directive named those ids, which I could not verify - the directive text is
not a tracked artifact, and the ledger's id mapping may be the triage's own work rather
than the directive's wording. One (`SHARED_SHA256` pins match live bytes) is an R3-shaped
digest re-derivation and is mechanical. One (the "duplicate `/activeplayerrunes` tax")
required reading `dashboard/_state_builder.py` behaviour and is not mechanical. So the
instance is CAUGHT, but "five of five" is not a five-of-five gate result.

### D - the stale FALLBACK. CAUGHT (R4), and mechanizability is PROVEN, not argued.

Concrete input: the ids `RM-387` and `RM-388`, named in a hand-off prompt written
2026-09-11.

Concrete output, run against the record as it stood at `a74a75dc4^`:
`git show a74a75dc4^:BACKLOG.md | grep -o "RM-38[78] [A-Z-]*"` returns `RM-387 SHIPPED`
and `RM-388 SHIPPED`. `git show a74a75dc4^:docs/LEDGER.md` carries `1369. DONE
**2026-09-08e` and `1368. DONE **2026-09-08d`. The closures predate the hand-off by
three days. R4 fires.

**Adversarial check, and it strengthens rather than weakens the verdict.** The predicate
is a status-word parse with a binding rule, and RC subsequently BUILT exactly that
parser: `tests/test_roadmap_backlog_disposition_drift.py`, created `a74a75dc4`
(2026-09-11), whose docstring at `:18-19` names RM-387 and RM-388 as two of the four
rows it was built from. A resolver that has since been implemented is not a hypothesis.

**The caveat that matters operationally:** `git show a74a75dc4^:ROADMAP.md` grades both
rows `OPEN`. If R4 consults ROADMAP it returns CLEAN and the gate passes the stale
fallback through. The catch depends entirely on the resolver reading BACKLOG or LEDGER,
which is the instrument the session that was burned did NOT read.

**A second caveat about resolver 4's claimed instrument.** The doc argues every
mechanical component "already exists in this tree". For R4 that is only half true.
`tools/rm_id_registry.py` resolves ALLOCATION, not DISPOSITION - I read `main()` at
`:424-428` (`result = audit(); print(describe(result)); return 1 if result.collisions`)
and the module docstring at `:1-40`, and ran it: it prints the next-free pin (RM-424),
"Scanned 7 docs", and a collision verdict. Asked about RM-387 it says "No allocated
occurrence found - the id is free", which is not a disposition answer at all. The
disposition instrument is the RM-403 guard, and it was born from this instance rather
than existing before it.

### E - RM-386 two-thirds stale. PARTIAL.

Row at pick-up: `git show 8aa2b81f1^:ROADMAP.md` line 41, `RM-386 SECOND HALF OPEN
(filed 2026-09-08) - THREE terminal states answer a note and tell its sender NOTHING`.

Concrete refutation available at that moment: `git grep -c "_emit_bounce" 8aa2b81f1^ --
tools/inbox_responder_runner.py` returns **2**, and `git log -S"_emit_bounce"` dates its
introduction to `b291b9a72` (2026-09-08), the same day. The asserted silence was already
false on disk.

Resolver by resolver: the row names `SYSTEM_PROMPT`, `pending_notes`, `NOTE_NAME_MAX`,
`ROW_NOTE_RE`, `_sender_code` - all present, so R2 passes. It names RM-384, RM-385,
RM-387; RM-385 had NOT yet shipped at this moment (`8315ea33b` is later than
`8aa2b81f1` in the same day's log), so R4 finds no superseding closure. R5 passes.

**The only resolver with a claim on it is R3, under its literal second clause:** "THREE
terminal states" is a figure inherited from prose and is not labelled inherited, so
dispatch is refused until it is re-derived. **Downgraded to PARTIAL because the
re-derivation is not mechanical.** There is no instrument that counts "terminal states
that tell the sender nothing". Producing 1 instead of 3 required reading `_emit_bounce`'s
firing set `{exhausted, refused}` and then adjudicating that the third state was never
RM-386's but the RM-385 class. A resolver that needs that is not a gate.

The structural point: the row asserts an ABSENCE. All five resolvers are PRESENCE checks.

### F - RM-394 posed as an open decision. MISSED.

Row at pick-up: `git show 57ecfeb82^:BACKLOG.md` line 255. Its closing sentence is
"Decide instead whether the universe should be `git ls-files` ... or `os.walk` minus
everything `git check-ignore` claims. Both are defensible; neither is chosen here."

Concrete refutation available at that moment: `git ls-tree 57ecfeb82^ tests/` lists
`tests/_repo_walk.py`, and `git grep -l "_repo_walk" 57ecfeb82^ -- tests` returns six
paths - the module, its own test, and **four consumers**
(`test_poller_lane8_cycle14.py`, `test_rc_lcu_pool_default_prose_guard_rm358.py`,
`test_riot_api_cache_eviction.py`, `test_rm172_mode_modifier_seam_characterization.py`).
The decision the row asks to make had been made in code.

**Why no resolver fires:** `git show 57ecfeb82^:BACKLOG.md | sed -n '255p' | grep -c
"_repo_walk"` returns **0**. The row never names the module. R1, R2 and R5 can only
check tokens the row carries; the defect is precisely the token the row does not carry.
R4 sees RM-392 and RM-394 with no superseding closure. R3 has figures (24 orphan headers,
0 tracked files) which re-derive correctly and are not the defect.

A gate over what a row NAMES cannot catch a row whose defect is what it OMITS.

### G - RM-385's proposed disposal. MISSED.

Row at pick-up: `git show 8315ea33b^:BACKLOG.md` line 257, which proposes "REFUSE the
entry (`refused / note-shape:linked`, answered so it stops re-cycling)". Line 256 - the
line immediately above it in the same file - already reads `RM-386 SECOND HALF SHIPPED
2026-09-08 - a refusal is no longer an answer`, shipped hours earlier at `8aa2b81f1`.

Resolver by resolver: `grep -o "RM-3[0-9][0-9]"` over that row returns exactly RM-384
(x1) and RM-385 (x1). **RM-386 is never named**, so R4 has nothing to resolve. The row's
citation `tools/inbox_responder.py:174` resolves exactly - `git show
8315ea33b^:tools/inbox_responder.py | sed -n '170,178p'` puts `def pending_notes(` at
`:174` - so R1's hard half CONFIRMS and R2 passes on `pending_notes`, `Path.is_file`,
`_sender_code`. R5 passes.

**Nothing fires.** Adjacency in the file is not a resolver input, and the contradiction
("answered so it stops re-cycling" against "a refusal is no longer an answer") is a
semantic one between two English sentences.

## 3. Totals, derived this run

- Instances the doc claims: **9** ("at least nine").
- Instances the doc enumerates: **7**.
- **LOCATED with primary evidence: 7 of 7 enumerated.**
- **CAUGHT: 3** (B, C, D).
- **MISSED: 3** (A, F, G).
- **PARTIAL: 1** (E).
- **UNGRADEABLE: 2** (the two unenumerated instances).

Catch rate over the gradeable set: **3 of 7**, or 3.5 of 7 counting PARTIAL at half.

## 4. Verdict

**The back-test SUPPORTS the Q4 recommendation, but WEAKLY, and it REFUTES the framing
that presents these nine instances as the evidence for it.**

The support is real and is not a formality. Instance D is a clean, fully mechanical
catch whose predicate RC has since implemented and shipped as a guard, which is the
strongest possible answer to the sibling's acceptance criterion: not "a gate would have
caught this" but "the gate that would have caught this now exists and its docstring
names this very instance". Instance C is a one-token existence check with no judgement
in it. Instance B is a literal application of R3's inherited-figure clause.

The refutation is equally concrete. **Three of the seven, plus the one PARTIAL, are not
reachable by any of the five resolvers, and they fail for one shared structural reason:
every resolver is a PRESENCE check over tokens the row carries, and this class of defect
is an ABSENCE.** F's row does not name `_repo_walk`. G's row does not name RM-386. A's
row does not name RM-396 or RM-398. E's row asserts that something is missing which had
already been added. In every one of those four the citations resolve, the symbols exist,
the ids carry no superseding closure and the instruments are present - the gate returns
GREEN and dispatch proceeds into the rediscovery.

Worse for the proposal as written: **instance A is the doc's own lead example, presented
first and at greatest length as the archetype of the highest-cost class, and it is a
clean miss.** I verified its two citations resolve to the exact symbols it names on the
record as it stood. A reader who accepts the Q4 section's ordering as evidence would
conclude the gate catches the case it demonstrably does not.

**Strength of the support: enough to justify building R2 and R4 (the two mechanical
resolvers, both of which fired cleanly on real instances), and enough to justify R3's
refuse-unless-labelled clause. Not enough to justify the claim that this gate addresses
"the MOST EXPENSIVE class". It addresses the part of that class where the row names its
own staleness. The part where the row is silent about the thing that already exists is
untouched, and on this sample that part is the majority.**

One further caution on R1. The doc's own resolver 1 has two halves and only the first is
mechanical. `tools/citation_audit.py` says so itself: `:85` calls a MOVED/ABSENT row "a
HINT to check by hand", `:107-108` says MOVED and ABSENT are UPPER bounds and "neither
number is exact", and `:547-548` says they are heuristic and deliberately kept out of
the budget guard because "a guard built on a heuristic would go red on a prose reword
and get disabled". R1's prose half should be treated as an advisory report, never as a
dispatch refusal. On this sample R1 fired on nothing anyway: every citation I resolved
was CORRECT.

## 5. Limits - what this method could not see

1. **Two of the nine instances are never enumerated in the source.** They may be the two
   that the gate catches best, or the two it misses worst. The sample is 7, not 9, and
   the doc's own "at least nine" is unsupported by its own list.
2. **The dispatch artifact does not exist on disk for B, C and D.** A relayed inbound
   note, a loop directive and a `/done` hand-off prompt are not tracked files. I graded
   the resolvers against the ledger's account of what those artifacts claimed. For C in
   particular, whether the directive named RM-407 and RM-399 BY ID - which decides
   whether R4 fires on two of its five claims - is not recoverable from the tree.
3. **The pick-up moment is approximated as the parent of the shipping commit.** The real
   moment a session read a stale row may be several commits earlier. For every instance
   graded MISSED this is harmless (the refuting fact was already present and the
   resolvers still return clean). For the CAUGHT ones it could only help.
4. **I graded "would a resolver fire", not "would the cost have been avoided".** B shows
   the gap: the gate fires, and the work it demands is the same verification the session
   performed. A firing gate is not automatically a saved session.
5. **No resolver was executed as an integrated gate, because no such gate exists.** I ran
   each predicate by hand with `git grep`, `git show` and `sed` against historical blobs.
   A real implementation would have parse and false-positive behaviour I cannot model -
   in particular R4 needs a row-to-id binding rule, and
   `tests/test_roadmap_backlog_disposition_drift.py` says in its own docstring that the
   binding rule "is the whole difficulty" and that a naive per-line regex is wrong in
   both directions.
6. **`tools/rm_id_registry.py` cannot answer R4's question.** I ran it; it reports the
   next-free pin and collisions over 7 docs, and returns "the id is free" for ids that
   are demonstrably allocated and shipped. The doc's claim that every mechanical
   component "already exists" overstates the R4 half.
7. **I did not reconcile the window's character count.** `sed -n '71,177p' docs/LEDGER.md`
   gave me 246006 characters for entries 1406 down to 1365; the source doc states 255532.
   I did not chase the difference and it does not bear on any verdict here.
8. **Single-tree, single-window, n=7.** Every verdict above is a claim about this
   repository's 2026-09-08 to 2026-09-12 window and about nothing else.
