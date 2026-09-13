# Probe: is `correct` a vacuous field? - RC re-score, 198 events

Read-only investigation. Question: the machine tally returns `correct: YES 198, NO 0,
UNCLEAR 0`, while RC's own earlier measurement of the SAME window reported "at least 9"
refutations that were themselves wrong. Both cannot be right.

**Verdict in one line: the field is NOT vacuous and the corpus is NOT filtered. The two
measurements count DIFFERENT OBJECTS, and RC's wrong-refutation population is present in
the corpus under a different field - `fix_chain` - not missing from it.**

---

## 1. The definition, quoted exactly

From `moon_sync_inbox/2026-09-12-from-LW-REFUTATION_TAXONOMY_PIN_v1_2.md` section 5:

> ## 5. Field `correct` - was the REFUTATION right
>
> `YES` / `NO` / `UNCLEAR`, asking ONE question: **was the refutation itself
> factually correct?**
>
> NOT whether the defect was fixed, fixed in-window, or acted on. Two of LW's four
> original passes read it the second way; re-read under the pinned question, LW's
> seven raw `NO` rows contained **exactly one** refutation that was actually wrong.
> **Any tree that scored this field the second way must re-read its `NO` rows
> before its Q1 answer means anything.**
>
> Record `defect_corrected` separately as `YES` / `NO` / `UNKNOWN`. It is a useful
> fact and it is not this field.

**Can the definition return NO for the events these scorers rowed? Structurally, almost
never - and the pin's own numbers say so before RC's do.** LW applied this field to 126
of its own rows and found **exactly one** true `NO`. That is 0.8 percent. RC applying it
to 198 rows and finding zero is the SAME result at a comparable rate, not a contradiction
of it. A field whose author measured it at roughly 1 percent is a field expected to
return a uniform column on a corpus of this size.

The structural reason is row CONSTRUCTION, and it is pinned in section 6, not section 5:

> Score the event as the DEFECT, then look FORWARD at what its fix did. Do NOT
> score an event as a fix-of-a-fix because it is itself somebody's second attempt -
> that is the backward reading, and it double-counts a chain once per link.

Every row is an event whose CLAIM is a defect and whose REFUTER is what exposed it. Rows
are extracted from ledger entries, and a ledger entry records a refutation only after the
tree has ACCEPTED it. So the refutation named in the `refuter` line is, by the mechanism
that put it in the record, one that stood. `correct=NO` is reachable only in the narrow
case where the ledger records a refutation the tree has since decided was wrong AND never
re-refuted - which is self-excluding, because the act of deciding it was wrong produces
its own record.

**Where does a wrong refutation go, then? To one of two places, both of which RC's rows
actually use.** (i) It becomes the CLAIM of a later row, whose own refuter is the probe
that killed it - so `correct` grades the second-order refutation, which stood. (ii) If
the wrong refutation landed on a REMEDY rather than on a fresh claim, it becomes a
`fix_chain` link on the parent defect row. Either way the population is recorded; it is
simply never recorded in the `correct` column.

---

## 2. The sampled pattern (19 rows across all four files)

| row | entry | what the `claim` field holds | `correct` |
|---|---|---|---|
| chunk1-01 | 1375 | RM-393's own stale citations | YES |
| chunk1-02 | 1374 | this session's own docstring citations | YES |
| chunk1-03 | 1374 | a 22-site grep asserted as a bound | YES |
| chunk1-04 | 1373 | an inherited census of 115 call sites | YES |
| chunk1-11 | 1373 | the entry's own draft sentence, future act stated as done | YES |
| chunk1-12 | 1373 | "CI provisions git and chromium explicitly" | YES |
| chunk1-32 | 1370 | "note 1 was fit to deliver" | YES (`fix_chain` 2, SELF) |
| chunk1-39 | 1369 | **verifier pass 3's report that no task is registered at all** | YES |
| chunk1-40 | 1369 | "the mutant needle is stable" | YES (`fix_chain` 1) |
| chunk1-42 | 1368 | "raw note name equals its projection by construction" | YES (`fix_chain` 3) |
| chunk1-60 | 1365 | "responder runtime records were bounded" | YES (`fix_chain` 2) |
| chunk2-39 | 1385 | inherited pre-RM-400 baseline | YES |
| chunk2-40 | 1385 | **RM-400's justifying sentence** | YES (`fix_chain` 1, SELF) |
| chunk2-43 | 1386 | RM-402's filed 6-and-2 figures | YES |
| chunk2-44 | 1386 | RM-402's characterisation of the population | YES |
| chunk2-45 | 1386 | RM-402's suggested alternative | YES |
| chunk2-46 | 1386 | the narrowing slice's circular population of 6 | YES |
| chunk2-47 | 1386 | the census slice's membership | YES |
| chunk3-40 | 1388 | **"RM-204 is a fifth disposition-drift row"** | YES |

**The pattern is uniform and it is the one the contract asks for.** In every row the
`claim` is the thing that turned out false and the `refuter` is what proved it false.
Three of the sampled rows (bolded) have a claim that is ITSELF A REFUTATION - a verifier's
assertion, a build's justifying sentence, a parser's drift finding. Those are exactly RC's
"wrong refutations". The scorers did not drop them. They rowed them with the polarity
inverted: the wrong refutation sits in the `claim` slot, so the `correct` field grades the
probe that killed it, and that probe was right.

`defect_corrected` is genuinely bimodal in the same corpus - 99 YES, 6 NO - which is the
control proving the scorers were answering section 5's pinned question and not the
second-way question section 5 warns about. A tree that had collapsed the two would show
`correct` tracking `defect_corrected`, and RC's does not.

---

## 3. The five named cases, located

All five of RC's earlier-named instances are IN the window and IN the corpus.

| # | case, as the earlier report describes it | LEDGER entry | row status |
|---|---|---|---|
| 1 | a verifier's sweep produced a fifth drift row, then refuted it unprompted as its own parser artifact | **1388** | **ROWED** as `chunk3-40`. `claim` = "RM-204 is a fifth disposition-drift row"; `refuter` = hand inspection; `correct: YES`. Carries a `pin_gap` note arguing exclusion 4 does not cleanly cover it. |
| 2 | a verifier reported a scheduled task "is not registered at all"; two machine probes return it, disabled | **1369** | **ROWED** as `chunk1-39`. `claim` = "verifier pass 3's report that no scheduled responder task is registered at all"; `refuter` = re-probing with a task query and a PowerShell cmdlet returning it Disabled; `correct: YES`. |
| 3 | a correction to a metrics figure that was itself false, said so in the entry's own headline | **1371** (headline: `THE CORRECTION WAS FALSE TOO, WHICH IS THE MORE USEFUL HALF`) | **ROWED** as the entry-1371 block. The defect ("a rotation that archives 40 rows of another agreement") carries `correct: YES` and `fix_chain: 1 (SELF)`. The wrongness of the CORRECTION is the `fix_chain` link, not a `correct` value. Two sibling rows in the same entry carry the same shape (`fix_chain: 1`, with the free-text naming the correction's own defect). |
| 4 | a "positive control" claim refuted once where the correction was ALSO wrong, the real object being a pytest summary hard-wrapped across three physical lines | **1386** (the double correction) against the claim shipped in **1385** | **ROWED** as `chunk2-40`, filed under entry **1385** rather than 1386. `fix_chain: 1 (SELF)` with the free-text reading "the correction called that session a LIVE POSITIVE CONTROL for the summary-line fence, and LEDGER 1386 refuted that too by reading the raw tool result". Note the six rows filed under entry 1386 itself do NOT include this - the chain is attributed to its origin entry, correctly under the forward reading. |
| 5 | a chain reaching a third correction - an account of one's own prior error, itself wrong in the opposite direction, corrected again | **1370** into **1371** ("re-paid RM-389's second rider in full: an account of your own prior error is a claim too, and mine was wrong twice - once on a number and once on a logical direction") | **ROWED** as `chunk1-32` (entry 1370, `fix_chain: 2`, SELF, free-text: "note 2, the correction, shipped three new false sentences, and note 3's draft was caught pre-delivery"). The deepest chain in the corpus is `chunk1-42` at `fix_chain: 3`. |

**Zero UNLOCATED.** Every case the earlier report named concretely resolves to an entry
number and to a row.

**Corpus completeness check.** 198 rows span 40 of the 42 in-window entries. Entries
**1382** and **1405** carry zero rows. That matches the earlier report's own statement
that exactly two of the 42 entries are clean, so the two gaps are accounted for and are
not evidence of dropped rows.

---

## 4. Diagnosis

Testing the four candidate explanations against the located cases:

**SELECTION - REFUTED.** The hypothesis was that scorers rowed only refutations that
stood, so wrong refutations never became events. Cases 1, 2 and 4 falsify it directly: a
verifier's false machine-state report, a parser's false drift finding, and a build's false
justifying sentence are all IN the corpus as rows. The corpus is not filtered. This matters
most, because it was the worst of the four outcomes.

**EXCLUSION - REFUTED as the cause, though one near-miss exists.** No section 7 exclusion
removes wrong refutations. Exclusion 4 (a hypothesis opened by a probe whose stated purpose
was to test it) comes closest and `chunk3-40` flags it explicitly as a `pin_gap` - the
scorer rowed the event anyway rather than excluding it, and said why. The exclusions
removed nothing from this population.

**GENUINE - REFUTED.** The earlier "at least 9" figure is not wrong. It is corroborated by
an independent count from the same rows: **24 of 198 rows (12.1 percent) carry
`fix_chain >= 1`** - 17 at 1, 4 at 1 with inline notes, 2 at 2, 1 at 3. Those are remedies
subsequently refuted, the dominant habitat of a wrong refutation. 24 is larger than 9 and
the same sign, so the two measurements agree.

**DEFINITIONAL - SUPPORTED, and it is the whole explanation.** The earlier report asked
"how often was a refutation in this window later shown to be wrong?" - a question about
the POPULATION OF REFUTATIONS. The pin's `correct` asks "was THIS ROW'S refuter right?" -
a question about ONE refutation, selected by the row-construction rule in section 6 that
makes it the terminal, accepted one. A wrong refutation is never a row's `refuter`; it is
a row's `claim`, or a link in a row's `fix_chain`. The two measurements are orthogonal,
and the pin's own data confirms the shape: LW found 1 true `NO` in 126 rows.

**Apportionment: DEFINITIONAL 100 percent. No other mechanism is operating.**

**Secondary finding, already self-reported by RC's own pin audit.** `pin_audit.md` FATAL-4
independently reached the adjacent defect from the other direction: `fix_chain` counts a
refutation of a remedy with NO correctness filter, so a remedy refuted by a refutation that
was itself WRONG scores `1` on the literal reading and `0` on the pin's own gloss ("`0`
means the first remedy stood"), and the pin discriminates neither. Its cited test case is
case 3 above. So the `fix_chain` column - the place the wrong-refutation population
actually lives - is itself unpinned on exactly this question. That is the real defect this
probe surfaces, and it is a defect in section 6, not section 5.

---

## 5. What RC must tell the fleet

1. **`correct` is not vacuous, but it is near-degenerate by construction and should not
   be reported as a result.** Under the section 6 forward reading, a row's `refuter` is
   always the accepted, terminal refutation. `NO` is reachable only for a refutation the
   record has repudiated and never replaced. LW measured 1 in 126; RC measured 0 in 198.
   Both are the same finding. **Do not report "100 percent of RC's refutations were
   correct."** Report that the field has no discriminating power on a ledger-derived
   corpus and say why.

2. **RC's 198-event corpus is NOT FILTERED. It IS COMPARABLE.** Wrong refutations are
   present as rows. A sibling that "rowed wrong refutations" and RC have both captured the
   same population - the sibling may simply have placed it in the `correct` column by
   applying the BACKWARD reading section 6 explicitly bans. **That is the comparability
   hazard to raise, and it runs in the opposite direction to the one suspected:** a tree
   whose `correct` column has `NO` rows on a ledger-derived corpus has very likely emitted
   fix-of-a-fix rows as their own events, which section 6 says double-counts the chain
   once per link, inflating BOTH its event total and its `correct=NO` count. Before any
   two trees compare Q1 answers, each must state which slot it put a wrong refutation in.

3. **The population RC measured at "at least 9 / 5.2 percent" survives re-scoring and is
   larger, not smaller: 24 of 198 rows, 12.1 percent, carry `fix_chain >= 1`.** The
   earlier prose figure and the re-score agree in sign and the re-score is the higher
   floor. Nothing was lost.

4. **Propose section 6 FATAL-4's repair to LW alongside this.** A `fix_chain` link should
   count only when the refutation OF THE REMEDY was itself correct. Without that filter
   the compounding ratio - the number the whole exercise exists to produce - is unpinned
   on precisely the events RC has the most of.

5. **Two limits stand on RC's re-score independently of this probe, both already recorded
   in `tally_report.md`:** each scorer both EXTRACTED and SCORED its own chunk, which is
   the producer-grades-own-work defect pin section 8 item 1 asks every tree to disclose
   (LW's re-score does not carry it; RC's does); and every count is a FLOOR, because the
   corpus is the ledger and the ledger is authored by the party being measured.
