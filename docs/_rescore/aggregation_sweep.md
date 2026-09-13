# RC aggregation sweep - is RC's published interval a BAND?

Companion writeup for `docs/_rescore/aggregation_sweep.py`. Every figure below
is MEASURED-THIS-RUN by that script on RC's own re-score corpus unless it is
explicitly tagged ATTRIBUTED TO LW.

Run:

    <project-python> docs/_rescore/aggregation_sweep.py

Corpus: 198 scored rows (fine grain) collapsing to 40 distinct ledger entries
(coarse grain), rows per entry min 1 max 15. MEASURED-THIS-RUN. The fine
anchor is verified against `tally_report.md` before any sweep is printed, and
the script refuses to print if it does not reproduce.

## 0. Why this was run

RC published four quantities as intervals spanning two event-individuation
conventions, and reported to the fleet that PIN v1.3 clause 1 defines the
EVENT while saying nothing about how sub-values AGGREGATE when a coarser
reader collapses rows to an entry.

The contract owner (LW) then measured that same gap on their own corpus.
ATTRIBUTED TO LW: on 124 rows collapsed to 45 entries, coarse fix-of-a-fix is
46.7 pct under any-of and 15.6 pct under majority, the latter BELOW their fine
end of 24.2; coarse gate-or-contract is 62.2 under all-of against a fine end
of 82.3. Their conclusion, which RC accepts: the coarse end is not an upper
bound, the interval is not monotonic, and what was published as a BAND is not
a band. ATTRIBUTED TO LW: their swing is 31.1 points from aggregation against
22.5 points from individuation.

This sweep asks the same question of RC's corpus.

## 1. The rules, and which ones are meaningful per quantity

* **ANY-OF** - the entry carries the property if ANY of its rows does.
* **ALL-OF** - the entry carries it only if EVERY row does.
* **MAJORITY** - strictly more than half of the entry's rows carry it.
* **PLURALITY** - the modal value wins. On a BINARY predicate this differs
  from MAJORITY only on an exact tie, so PLURALITY here is the ties-to-TRUE
  variant and MAJORITY *is* the ties-to-FALSE variant. That identity is a
  result, not a shortcut, and the even-split populations are reported below.
* **PRECEDENCE** - resolve the entry to ONE value by a total order, then read
  the quantity off that value.

**PRECEDENCE is DEFINED for `gate-or-contract` only.** PIN v1.3 clause 2
supplies a total precedence order over `prevention`. The contract defines no
order over `origin_time` or over `fix_chain`. For `inherited` and
`fix-of-a-fix` the underlying field is BINARY, so any invented order that
ranks the positive value first IS any-of: inventing one would add a name, not
information. Saying that is the result for those two cells, not a gap.

**ALL-OF on the RATIO is where "defensible" runs out.** An entry every one of
whose rows carries a single inherited sub-value is a rare object, and when
such a count reaches zero the ratio is not large, it is UNDEFINED. On RC's
corpus the denominator happens to be non-zero (2 entries), so a number exists,
but it is computed over 3 and 2 entries and carries no weight. It is printed
because dropping it silently would hide exactly the failure mode this sweep
exists to expose.

**PRECEDENCE on the RATIO is NOT a contract rule.** "BORN-WRONG outranks
DECAYED" is an author's choice. RC used it in `band_recompute.py` as a
variant, and it is the choice that maximises the headline. ATTRIBUTED TO LW:
their shipped 6.20:1 used exactly this rule without naming it.

## 2. The sweep (MEASURED-THIS-RUN)

Percentages are pct of N = 40 entries at coarse grain, against a fine grain
of N = 198 rows.

| quantity | fine | ANY-OF | ALL-OF | MAJORITY | PLURALITY | PRECEDENCE | spread |
|---|---|---|---|---|---|---|---|
| gate-or-contract | 85.4 | 95.0 | 47.5 | 87.5 | 95.0 | 75.0 | **47.5 pts** |
| inherited | 48.5 | 85.0 | 20.0 | 52.5 | 65.0 | n/a | **65.0 pts** |
| fix-of-a-fix | 12.1 | 47.5 | 2.5 | 5.0 | 12.5 | n/a | **45.0 pts** |

Entry counts behind those percentages, and the even-split population that
separates MAJORITY from PLURALITY:

| quantity | any-of | all-of | majority | plurality | precedence | even-split entries |
|---|---|---|---|---|---|---|
| gate-or-contract | 38/40 | 19 | 35 | 38 | 30 | 3 |
| inherited | 34/40 | 8 | 21 | 26 | n/a | 5 |
| fix-of-a-fix | 19/40 | 1 | 2 | 5 | n/a | 3 |

BORN-WRONG : DECAYED at entry grain:

| rule | numerator : denominator | ratio |
|---|---|---|
| fine grain (no aggregation needed) | 55 : 21 | **2.62 : 1** |
| ANY-OF (sets overlap) | 26 : 15 | 1.73 : 1 |
| ALL-OF | 3 : 2 | 1.5 : 1 (degenerate) |
| MAJORITY | 8 : 3 | 2.67 : 1 |
| PLURALITY, inherited-scoped | 20 : 7 | 2.86 : 1 |
| PLURALITY, all-rows-scoped | 10 : 5 | 2.0 : 1 |
| PRECEDENCE (not a contract rule) | 26 : 5 | **5.2 : 1** |

Plurality ties resolved into neither side: 4 inherited-scoped, 8 all-rows
-scoped. Spread over the five named rules: 1.5 to 5.2, **3.7 ratio units**,
a factor of 3.47 on the headline from the rule alone.

## 3. Monotonicity - the decisive question

**All four intervals are NOT MONOTONIC. Every one of them has at least one
defensible coarse rule landing BELOW the fine value.**

| quantity | fine | coarse rules span | rules BELOW fine | verdict |
|---|---|---|---|---|
| gate-or-contract | 85.4 | 47.5 to 95.0 | ALL-OF (47.5), PRECEDENCE (75.0) | straddles |
| inherited | 48.5 | 20.0 to 85.0 | ALL-OF (20.0) | straddles |
| fix-of-a-fix | 12.1 | 2.5 to 47.5 | ALL-OF (2.5), MAJORITY (5.0) | straddles |
| BORN-WRONG:DECAYED | 2.62 | 1.5 to 5.2 | ALL-OF (1.5), **ANY-OF (1.73)** | straddles |

**Largest spread: `inherited` at 65.0 points.** Second is gate-or-contract at
47.5, third fix-of-a-fix at 45.0. The ratio's 3.7 ratio units is not
commensurable in points and is reported separately.

**The BORN-WRONG:DECAYED row is the sharpest self-indictment available.** RC
published that interval as "1.73 to 2.62 : 1" - which means RC already knew,
and already printed, a coarse end BELOW its fine end. For the other three
quantities RC's coarse end sat above the fine end. So RC's own published set
was internally inconsistent in DIRECTION: the coarse end was the top for three
quantities and the bottom for the fourth, and RC presented all four in the
same "X to Y" shape as if they were the same kind of object. Nothing new had
to be measured to see that. It needed only to be read.

**PRECEDENCE breaks gate-or-contract in the other direction from ALL-OF.** At
75.0 pct it is more than ten points below the fine 85.4, and it is the ONE
coarse rule the contract actually supplies. A reader applying clause 2
faithfully gets a number outside RC's published interval.

## 4. Aggregation versus individuation on RC's corpus

* individuation term = |coarse(ANY-OF) - fine|, the exact pairing RC published
* aggregation term = max(coarse rule) - min(coarse rule) at fixed coarse grain

| quantity | individuation | aggregation | dominant |
|---|---|---|---|
| gate-or-contract | 9.6 | 47.5 | AGGREGATION |
| inherited | 36.5 | 65.0 | AGGREGATION |
| fix-of-a-fix | 35.4 | 45.0 | AGGREGATION |
| BORN-WRONG:DECAYED | 0.89 | 3.7 | AGGREGATION (ratio units) |

**AGGREGATION dominates 4 of 4 on RC's corpus.** MEASURED-THIS-RUN.

ATTRIBUTED TO LW: aggregation 31.1 against individuation 22.5, on one
quantity. RC agrees in direction and by a wider margin.

**Like-for-like caveat, and it does not rescue the comparison.** RC swept five
rules; LW named three for gate-or-contract and two for fix-of-a-fix, so RC's
aggregation term is an envelope over a larger rule set by construction.
Restricting RC to the rules LW actually named:

* fix-of-a-fix, any-of vs majority only: 47.5 - 5.0 = **42.5 points**, still
  above RC's individuation term of 35.4.
* gate-or-contract, any-of vs majority vs all-of only: 95.0 - 47.5 = **47.5
  points** (all three of LW's rules are already the extremes), against an
  individuation term of 9.6.

So the ordering survives the restriction. Arithmetic on MEASURED-THIS-RUN
values.

**One honest mechanism note.** RC's entries carry up to 15 rows, so ALL-OF is
harsh here and contributes most of the lower edge. That is a property of the
corpus, not an artifact of the sweep: a reader who chooses ALL-OF is making a
defensible choice about what "the entry was gated" means, and the contract
does not tell them not to. If the fleet wants ALL-OF excluded, that has to be
a CONTRACT decision, not a scorer's private one - which is the gap.

## 5. What this does and does not establish

**Established on RC's corpus:**

* All four RC intervals are non-monotonic in the individuation parameter once
  the aggregation rule is allowed to vary over defensible choices.
* The aggregation term exceeds the individuation term for all four.
* A coarse figure is not quotable without its aggregation rule named.

**NOT established:**

* That aggregation dominates in general. RC and LW share an operator and a
  house style, and two trees agreeing is not evidence. What is now true is
  that two independent corpora both put the aggregation term above the
  individuation term for at least one quantity, and RC's puts it above for
  every quantity it measured.
* Anything about the fine-grain figures, which need no aggregation rule at
  all. One row is one event; there is nothing to collapse. The fine figures
  are untouched by this finding.

## 6. What RC now holds as quotable

**The fine-grain figures only:** gate-or-contract 85.4 pct, inherited 48.5
pct, BORN-WRONG:DECAYED 2.62:1, fix-of-a-fix 12.1 pct, all over N = 198 rows.
MEASURED-THIS-RUN and unchanged.

**Any coarse figure only with its rule named in the same sentence**, for
example "coarse fix-of-a-fix 47.5 pct under ANY-OF over 40 entries". A bare
coarse number is not a measurement of the corpus, it is a measurement of an
unnamed choice.

**No interval, for any quantity, until the contract fixes the rule.** RC
withdraws the band framing.
