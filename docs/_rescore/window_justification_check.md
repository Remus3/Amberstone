# Window justification check - RC entries 1365-1406

Adversarial re-test of the GRANULARITY reason given at
`docs/REFUTATION_COST_MEASUREMENT_2026-09-12.md:40-43` for drawing the
refutation-cost window at ledger entry 1365. Read-only. Every figure below comes
from a command run in this session; the commands are shown.

**VERDICT: the granularity justification FAILS.** There is no structural
discontinuity at entry 1365. The one-row-per-entry shape is the ledger's dominant
form back to its first entry (325, 2026-06-06), and the 42 entries immediately
before the window carry adversarial verdicts at an EQUAL-OR-HIGHER rate with MORE
refutation markers per entry, not fewer. The second reason RC gave for the
boundary is wrong in both of its halves.

---

## 1. Numbering and ordering (verified, not assumed)

```
python: read docs/LEDGER.md, match ^(\d+)\. , keep n >= 325
```

- 1083 entries, numbered **1412 down to 325**, strictly descending: **newest-first
  confirmed**.
- Numbers 6-324 are absent because items 1-324 were relocated to
  `docs/history_notes.md`; the file's own preamble says so.
- Three apparent low-numbered "entries" (1, 2, 3 at lines 429-433 and 451-453) are
  markdown ORDERED-LIST items INSIDE entries 1351 and 1350, not entries. They were
  excluded by the `n >= 325` filter.
- There are **no `##` headings in the body** (`grep -c "^## " docs/LEDGER.md` -> 0).
  The unit is the numbered row, delimited by `---`. So "entries per heading" is
  1:1 by construction in BOTH sets, and the question reduces to whether one
  numbered row carries one item or several - measured in section 3.

Entry blocks were cut from each `NNNN. ` line to the line before the next one,
with trailing blanks and the `---` rule stripped.

## 2. Shape: lines and characters per entry

```
python: nonblank line count and character count per entry block
```

| set | n | one-row entries | chars/entry median | chars/entry mean |
|---|---|---|---|---|
| WINDOW 1365-1406 | 42 | **42 / 42 = 100.0%** | 5846 | 5853 |
| PRE-42 1323-1364 | 42 | **25 / 42 = 59.5%** | 8974 | 9862 |
| PRE-40b 1283-1322 | 40 | 16 / 40 = 40.0% | 9472 | 9654 |
| PRE-82 1283-1364 | 82 | 41 / 82 = 50.0% | 9324 | 9761 |

Taken alone this looks like support for RC. It is not, and the next table is why.

## 3. The one-row shape is NOT new at 1365

Widening the same measurement over the whole file:

| entry range | one-row | share |
|---|---|---|
| 325-699 | 300 / 374 | 80.2% |
| 700-999 | 280 / 298 | 94.0% |
| 1000-1282 | 273 / 281 | **97.2%** |
| 1283-1364 | 41 / 82 | 50.0% |
| 1365-1406 | 42 / 42 | 100.0% |
| whole file | 942 / 1083 | 87.0% |

The window's 100 percent does not begin a regime. It **returns** to the regime that
already held at 97.2 percent across entries 1000-1282. The dip to 50 percent at
1283-1364 is the anomaly, and it is localised to four calendar days, not to
"everything before 1365":

```
python: one-row fraction grouped by the entry's own date stamp
```

```
2026-07-16 .. 2026-08-15   100% on every date except 07-27 (95%), 07-30 (93%), 08-01 (94%)
2026-08-16   4/5    80%
2026-08-29   3/3   100%
2026-08-30   4/22   18%   <- burst of multi-paragraph lane entries
2026-08-31   7/17   41%   <- same
2026-09-01   5/5   100%
2026-09-02   2/2   100%
2026-09-03   2/3    67%
2026-09-04   9/9   100%
2026-09-05   6/6   100%
2026-09-06   6/20   30%   <- same
2026-09-07   3/5    60%
2026-09-08  7/7  09-09 12/12  09-10 5/5  09-11 11/11  09-12 14/14   all 100%
```

The lowest-numbered one-row entry is **325, dated 2026-06-06** - the first entry in
the file. Immediately before the window, entries **1324-1344 are 21 consecutive
one-row entries** (2026-09-04 to 2026-09-06) and **1361-1364 are four more**
(2026-09-07 to 2026-09-08). A boundary that claimed to separate "one row per entry"
from "multi-row session wraps" would have to fall somewhere around 2026-06-06, and
even then it would be describing a majority tendency with sporadic exceptions, not a
change of regime.

**The date the structure actually changed: it did not.** The form is continuous
across the whole ledger. What varies is which lane wrote the entry.

## 4. Inline adversarial verdicts, and the countability predicate

The phrase "separably countable" hides a judgement, so two predicates were stated
in advance and both were control-tested before any count was reported.

- **EV (marker occurrence)** - case-insensitive regex
  `(refut|adversar|verifier|adjudicat)`. An OCCURRENCE is one separably countable
  refutation event marker.
- **VER (shouted inline verdict)** - case-SENSITIVE
  `(VERIFIER|REFUTE|REFUTED|REFUTATION|ADVERSARIAL|ADJUDICAT)`, i.e. the
  capitalised verdict form this ledger uses when it records an adjudication inline.

Controls (an empty grep is a claim about the pattern):

- positive: the literal string `VERIFIER: REFUTE on the first pass`, taken from
  entry 1350, matches both predicates; EV finds **2** occurrences in it.
- negative: `nothing here at all` matches neither.
- non-vacuity on real data, both directions: EV returns **zero** for window entries
  **1375, 1387, 1401** and for pre-window entries **1328, 1329, 1330, 1356, 1359**.
  The predicate can and does return zero, so a high hit rate is a finding rather
  than a tautology.

| set | n | any EV | shouted VER | EV occurrences | EV median/entry | EV mean/entry |
|---|---|---|---|---|---|---|
| WINDOW 1365-1406 | 42 | 39 (92.9%) | **29 (69.0%)** | 209 | **4.0** | 4.98 |
| PRE-42 1323-1364 | 42 | 37 (88.1%) | **32 (76.2%)** | 231 | **5.0** | 5.50 |
| PRE-40b 1283-1322 | 40 | 37 (92.5%) | 30 (75.0%) | 182 | 4.0 | 4.55 |
| PRE-82 1283-1364 | 82 | 74 (90.2%) | 62 (75.6%) | 413 | 4.0 | 5.04 |

**This is the half of RC's claim that fails hardest.** RC asserted that before 1365
"individual refutation events are not separably countable without archaeology into
commit history". Measured, the pre-window entries record their adversarial verdicts
inline MORE often (76.2 vs 69.0 percent shouted) and carry MORE refutation markers
each (median 5 vs 4, total 231 over 42 entries vs 209 over 42).

Opening the multi-row entries by hand confirms the direction. Entry 1350 (26
nonblank lines, 19064 chars, 15 EV hits) contains the line
`**VERIFIER: REFUTE on the first pass, and it caught a BLOCKER that would have
corrupted this file.**` followed by an explicitly **numbered list of three refuted
claims** plus a fourth defect class named in the next paragraph. Those events are
not merely countable, they are pre-enumerated by the author. The multi-row entries
are single items with MORE internal structure - the extra rows are sub-bullets of
one item, not separate items - and that structure makes the events EASIER to count,
not harder. Multi-row does not mean multi-item.

## 5. The boundary excludes a same-day, same-shape entry

The published window says "2026-09-08 through 2026-09-12 inclusive". Entry **1364
is dated 2026-09-08**, is **one row**, is 9524 chars, and carries **4 EV hits**. It
is excluded anyway. Applied literally, the stated date range gives n = 43, not 42.

```
grep -nE "^136[3-6]\. " docs/LEDGER.md
```

So the boundary is not the stated date range either. 1365 is simply where the count
was started.

## 6. Does reason 1, PROTOCOL HOMOGENEITY, survive on its own?

Partly, and it does not rescue this boundary.

```
git log --follow --format='%h %ad' --date=short \
  -S "Session Default (was: Subagent-First Protocol)" -- CLAUDE.md
  -> 17b5422d7 2026-07-30

git log -p --follow -- CLAUDE.md | grep -E "Standing operator directive \(2026"
  -> +**Standing operator directive (2026-07-30). The default shape of EVERY session
     is orchestrated + multi-agent + self-adjudicating + self-adversarial.**  (17b5422d7)
  -> +Standing operator directive (2026-06-20): ALWAYS use subagents for substantive
     design / build / research work ...                                       (d27dd11a9)
```

The directive RC names was adopted **2026-07-30**, superseding a weaker 2026-06-20
version. Counting entries whose own date stamp is on or after 2026-07-30:

```
python: count entries with a date stamp >= 2026-07-30
  -> 291 entries, numbered 1412 down to 1120
```

**The homogeneity reason picks out entry 1120 onward, not 1365.** It justifies a
window roughly seven times larger. As a reason to stop at 1365 it is not merely
weak, it points elsewhere.

It is also not clean INSIDE the window. The standing orders changed five times
during it:

```
git log --format='%h %ad %s' --date=short --since=2026-09-08 -- CLAUDE.md
  d0dcfb03d 2026-09-09  docs(adr): ADR-015 ...
  24bde4623 2026-09-09  docs(directives): subagent-first ALWAYS ...
  396e0b81d 2026-09-09  docs(directives): the headless loop halts before any byte leaves the tree
  12fec7a75 2026-09-09  docs(directives): the halt-before-any-byte boundary binds EVERY session ...
  8facd08d4 2026-09-09  docs(directives): the push half gates on DIFF CONTENT, not destination ...
  2f1ad6f7a 2026-09-10  feat(gate): RM-399 SHIPPED - RC's sibling-name sweep ...
```

Four directive edits on 2026-09-09 and an armed gate on 2026-09-10, all of them
mid-window. So the window is homogeneous only at the coarse grain at which
1120-1412 is equally homogeneous. Reason 1 survives as a reason to EXCLUDE
pre-2026-07-30 entries. It does not survive as the reason for THIS boundary.

## 7. What the honest justification would be

State it as what it is. Three candidates, in decreasing honesty:

1. **"The last five days of work, chosen because the corpus is hand-openable at
   full text and recent enough to reflect current tooling."** That is reason 3
   (hand-openability) plus recency, and both are defensible on their own terms. It
   makes no structural claim and needs none. A census of a convenience window is
   still a census; it is just not a natural unit.
2. **"Entries 1120-1412, every entry produced under the 2026-07-30 directive."**
   This is the boundary reason 1 actually implies. It is a natural unit. It costs
   roughly seven times the reading.
3. What was published. Reasons 1 and 2 both assert a natural boundary at 1365.
   Reason 1 points at 1120. Reason 2 is refuted outright.

The window should be described as **RECENT AND HAND-SIZED**, not as **NATURAL**.

## 8. Consequence for the published numbers - stated without inflation

What this does **NOT** undermine:

- The **173 events** and the **139 / 173 = 80.3 percent** preventable share are
  counts over a corpus that exists and was read. Nothing here says any event was
  miscounted or misbucketed. This check did not re-audit the bucketing at all.
- The doc's own headline finding - that RC already owns gates that did not fire,
  and that MOVING existing checks beats ADDING new ones - is a claim about the
  content of the events, not about where the window starts. It is untouched.
- The doc's explicit self-limitation ("a count from one tree is a claim about that
  tree", "do not quote these as a fleet-wide rate") is unaffected and remains
  correct.

What this **DOES** undermine:

- The claim that the window is a **natural unit of analysis**. It is not. It is a
  recent five-day slice whose boundary coincides with neither a structural change
  in the ledger nor the adoption date of the directive cited to justify it.
- Reason 2 as written, which should be **withdrawn**, not softened. Its factual
  content is false in both halves: the one-row form predates 1365 by three months,
  and the earlier multi-row entries enumerate their refutation events more
  explicitly, not less.
- Any implicit claim of **representativeness**. Because the boundary is
  convenience, the 80.3 percent cannot be defended as unbiased for the directive
  era without either widening to 1120 or showing that 1365-1406 does not differ
  from the rest of that era. Neither has been done. Note the one measured
  difference points the OTHER way from the convenient direction: the window has a
  LOWER inline-verdict rate than the 42 entries before it (69.0 vs 76.2 percent),
  so if anything the window under-samples recorded adjudication rather than
  cherry-picking a refutation-rich patch. That is a mitigation, not a defence.

The correct repair is one paragraph: delete reason 2, restate reason 1 as an
exclusion criterion rather than a boundary, and label the window recent and
hand-sized. The numbers stay.

## Appendix - commands, in order

```
wc -l docs/LEDGER.md
head -60 docs/LEDGER.md
grep -c "^## " docs/LEDGER.md
grep -nE "^[0-9]+\. " docs/LEDGER.md        (indexed to line/number pairs)
sed -n '445,470p' docs/LEDGER.md
grep -nE "^136[3-6]\. " docs/LEDGER.md
ls docs/REFUTATION_COST_MEASUREMENT_2026-09-12.md
sed -n '28,52p' docs/REFUTATION_COST_MEASUREMENT_2026-09-12.md
git log --follow --format='%h %ad' --date=short -S "Session Default (was: Subagent-First Protocol)" -- CLAUDE.md
git log -p --follow --format='COMMIT %h %ad' --date=short -- CLAUDE.md | grep -E "^COMMIT|Standing operator directive \(2026"
git log --format='%h %ad %s' --date=short --since=2026-09-08 -- CLAUDE.md
```

Plus five `python - <<EOF` passes over `docs/LEDGER.md` (no writes) computing, in
order: numbering/ordering validation; per-entry nonblank-line and character stats
by range; per-entry date extraction; one-row fraction by date and by range; and the
EV/VER predicate counts with their positive, negative and non-vacuity controls.

`pytest` was not run. No tracked file was read for modification and none was
modified; this document is the only file written.
