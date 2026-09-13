# RC re-score tally - derived from the rows, not from the scorers' summaries

Machine tally of the four per-event row files under LW REFUTATION_TAXONOMY_PIN
v1.2. Every number below is produced by `docs/_rescore/tally.py` reading the row
files directly. No scorer-reported total was carried forward.

**Exact command used:**

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" "C:\Riot Commander\docs\_rescore\tally.py"
```

Run from `C:\Riot Commander`. Exit code 0.

---

## 1. Events parsed, against what each scorer claimed

| chunk | claimed | parsed | match |
|---|---|---|---|
| chunk1 | 60 | 60 | YES |
| chunk2 | 48 | 48 | YES |
| chunk3 | 47 | 47 | YES |
| chunk4 | 43 | 43 | YES |
| **TOTAL** | **198** | **198** | **YES** |

**ZERO discrepancies.** Every one of the four scorers' claimed counts is exactly
the number of rows the parser extracted from that scorer's file. The
mis-summarisation defect that motivated this job (78 numbered and summarised as
74, 13 rows reported as 9, 7 rows reported as 11) does NOT reproduce here.

The parser counts `## chunk<N>-<NN>` headings, not the scorers' prose. chunk4
carries one extra `##` heading, `Method`, which is prose and is reported as a
skipped non-row heading rather than silently dropped or silently counted.

### Parse problems

11 problems over 198 rows, **0 of them blocking**:

| severity | chunk | row | kind | detail |
|---|---|---|---|---|
| benign | chunk3 | chunk3-04, -08, -11, -21, -28, -30, -34, -37, -42 | SEPARATOR | markdown horizontal rule `---` between rows (9 occurrences) |
| benign | chunk4 | - | NON-ROW-HEADING | prose heading `Method (not a tally ...)` |
| benign | chunk4 | chunk4-28 | NOTE-LINE | free-text `- Note on the chain: ...` bullet carrying no field key |

Rows retained despite being malformed: 0, because 0 rows were malformed. No row
is missing a required field, no field carries a value outside the pin's legal
set, no duplicate field key, no `GATE-EXISTING` row missing `prevention_why`, no
`fix_chain >= 1` row missing `chain_kind`, no `chain_kind` on a `fix_chain: 0`
row. The parser would have counted and named any of those rather than dropping
the row.

---

## 2. Distributions

### `prevention` (pin section 2)

| value | chunk1 | chunk2 | chunk3 | chunk4 | TOTAL | pct |
|---|---|---|---|---|---|---|
| GATE-ABSENT | 20 | 10 | 18 | 17 | 65 | 32.8 |
| CONTRACT | 11 | 17 | 8 | 14 | 50 | 25.3 |
| GATE-FIRED-CAUGHT | 18 | 14 | 3 | 1 | 36 | 18.2 |
| PROXY-MEASURE | 3 | 3 | 11 | 1 | 18 | 9.1 |
| GATE-EXISTING | 5 | 1 | 3 | 8 | 17 | 8.6 |
| ADVERSARY | 3 | 3 | 3 | 1 | 10 | 5.1 |
| CONTRACT-MISFIRED | 0 | 0 | 1 | 0 | 1 | 0.5 |
| GATE-FIRED-IGNORED | 0 | 0 | 0 | 1 | 1 | 0.5 |

### `discovery` (pin section 3)

| value | chunk1 | chunk2 | chunk3 | chunk4 | TOTAL | pct |
|---|---|---|---|---|---|---|
| SELF-AUDIT | 40 | 21 | 24 | 12 | 97 | 49.0 |
| RUN | 11 | 18 | 10 | 12 | 51 | 25.8 |
| CODE-READ | 7 | 8 | 13 | 19 | 47 | 23.7 |
| SIBLING | 2 | 1 | 0 | 0 | 3 | 1.5 |
| CI | 0 | 0 | 0 | 0 | 0 | 0.0 |
| OPERATOR | 0 | 0 | 0 | 0 | 0 | 0.0 |
| RESEARCH | 0 | 0 | 0 | 0 | 0 | 0.0 |

Three legal values are unused across all 198 rows. `OPERATOR` reading zero is
worth flagging against chunk3's `pin_gap` on chunk3-47, which records an
operator-originated claim that had to be scored FRESH for want of a value in
section 4; the `discovery` axis does carry `OPERATOR` and it was not used.

### `origin_time` (pin section 4)

| value | chunk1 | chunk2 | chunk3 | chunk4 | TOTAL | pct |
|---|---|---|---|---|---|---|
| FRESH | 37 | 24 | 26 | 15 | 102 | 51.5 |
| INHERITED / BORN-WRONG | 10 | 20 | 12 | 13 | 55 | 27.8 |
| INHERITED / DECAYED | 8 | 2 | 5 | 6 | 21 | 10.6 |
| INHERITED / UNDER-PROVEN | 4 | 1 | 2 | 5 | 12 | 6.1 |
| INHERITED / OVER-GENERALISED | 1 | 1 | 2 | 3 | 7 | 3.5 |
| INHERITED / UNKNOWN | 0 | 0 | 0 | 1 | 1 | 0.5 |

Every INHERITED row carries the required sub-value. None is bare.

### `correct` (pin section 5)

| value | chunk1 | chunk2 | chunk3 | chunk4 | TOTAL | pct |
|---|---|---|---|---|---|---|
| YES | 60 | 48 | 47 | 43 | 198 | 100.0 |
| NO | 0 | 0 | 0 | 0 | 0 | 0.0 |
| UNCLEAR | 0 | 0 | 0 | 0 | 0 | 0.0 |

All 198 refutations were scored factually correct. Pin section 5 warns that a
tree which read this field as "was the defect fixed" must re-read its `NO` rows;
RC has no `NO` rows to re-read, and all four scorers' files show the pinned
question being answered (`defect_corrected` is recorded separately, either as
its own field in chunk4 or inside the `correct` parenthetical in chunks 1 to 3).
A field that comes back 100 percent one way carries no discriminating power and
should be read as such, not as a strong result.

### `fix_chain` (pin section 6)

| value | chunk1 | chunk2 | chunk3 | chunk4 | TOTAL | pct |
|---|---|---|---|---|---|---|
| 0 | 47 | 41 | 45 | 41 | 174 | 87.9 |
| 1 | 10 | 7 | 2 | 2 | 21 | 10.6 |
| 2 | 2 | 0 | 0 | 0 | 2 | 1.0 |
| 3 | 1 | 0 | 0 | 0 | 1 | 0.5 |

`chain_kind` over the 24 rows with `fix_chain >= 1`:

| chain_kind | count | in ratio |
|---|---|---|
| SELF | 19 | yes |
| SIBLING-SURFACE | 3 | yes |
| INTRODUCED | 2 | yes |
| INHERITED-SHARED | 0 | yes |
| SAME-ARTIFACT | 0 | **no** |

All four scorers applied the FORWARD direction, and each says so explicitly in
its own preamble. That is the field pin section 0 names as the fatal v1
underspecification, so the agreement is load-bearing and was checked in the
source text rather than assumed.

### Fix-of-a-fix rate, both numbers

| numerator | events | of 198 | rate |
|---|---|---|---|
| `fix_chain >= 1`, SAME-ARTIFACT **included** | 24 | 198 | **12.1 pct** |
| `fix_chain >= 1`, SAME-ARTIFACT **excluded** (the pinned ratio) | 24 | 198 | **12.1 pct** |

**The two numbers are identical because RC has zero SAME-ARTIFACT rows.** The
pin's exclusion is therefore inert on this corpus and cannot be the source of any
divergence between RC's figure and a sibling's. Stated positively: SAME-ARTIFACT
rows are OUT of the numerator, as pinned, and removing them changes nothing.

Total chain links (sum of `fix_chain` over in-ratio kinds): 28 across 24 events.

### `uncertain` and `pin_gap`

| field | chunk1 | chunk2 | chunk3 | chunk4 | TOTAL | pct |
|---|---|---|---|---|---|---|
| `uncertain` | 24 | 10 | 12 | 10 | 56 | 28.3 |
| `pin_gap` | 6 | 5 | 9 | 4 | 24 | 12.1 |

28.3 percent of events carry an explicit scorer reservation about their own
value, and 12.1 percent name a place the pin does not resolve. Pin section 0
asks a re-scoring tree to report underspecifications rather than resolve them
silently; these 24 `pin_gap` rows are that report, and they are not aggregated
here because they are free text.

---

## 3. The fleet-comparable figure

| family | events | pct of 198 |
|---|---|---|
| GATE family (GATE-EXISTING + GATE-ABSENT + GATE-FIRED-IGNORED + GATE-FIRED-CAUGHT) | 119 | 60.1 |
| CONTRACT | 50 | 25.3 |
| **GATE + CONTRACT combined** | **169** | **85.4** |
| CONTRACT-MISFIRED (distinct pin value, shown separately) | 1 | 0.5 |
| GATE + CONTRACT + CONTRACT-MISFIRED | 170 | 85.9 |

**RC's comparable figure is 85.4 percent**, against the other trees' 73.8, 78.5,
80.3 and 83.3 percent. RC sits highest of the five.

`CONTRACT-MISFIRED` is a separate value in pin section 2 and means a contract was
correctly applied and still produced the wrong outcome, which is the opposite of
"a contract would have prevented it". It is not folded into CONTRACT. The
variant including it is given so a sibling that folded them can compare like with
like; the difference is one event.

Composition matters more than the headline. RC's GATE family is 60.1 percent, but
36 of those 119 (18.2 percent of all events) are `GATE-FIRED-CAUGHT` - events
where the tooling WORKED. A tree that scored its gate family unsplit would report
those inside the same bucket as gate failures. If a sibling's 73.8 to 83.3 was
produced without the four-way split, the figures are not directly comparable and
RC's 85.4 should not be read as a worse tree.

## 4. INHERITED split, DECAYED against BORN-WRONG

| measure | value |
|---|---|
| INHERITED, all sub-values | 96 of 198 = 48.5 pct |
| BORN-WRONG | 55 |
| DECAYED | 21 |
| **BORN-WRONG : DECAYED** | **2.62 : 1** |

RC could not produce this split before; it can now. The sibling reports 3.11 to
1 toward BORN-WRONG. RC measures 2.62 to 1 - the same direction, same order of
magnitude, and it confirms the pin's central claim in section 4 that scoring
inheritance as decay alone measures the scorer rather than the corpus. On this
corpus, re-grounding against HEAD would reach at most 21 of 96 inherited events.

RC's overall inherited share of 48.5 percent is below LW's 62.9 percent. Counting
all five sub-values, not only the two named above, INHERITED covers 96 events
against 102 FRESH.

---

## 5. Sanity checks

**1. Every `entry` value falls in 1365-1406: PASS.** 198 of 198 rows carry an
entry inside the window. No out-of-window value.

**2. No duplicate `id`: PASS.** 198 distinct ids over 198 rows.

**3. Per-chunk entry ranges do not overlap: PASS.** All six pairwise comparisons
are disjoint.

| chunk | entry range | distinct entries carrying events |
|---|---|---|
| chunk1 | 1365-1375 | 11 |
| chunk2 | 1376-1386 | 10 (of 11 in range) |
| chunk3 | 1387-1396 | 10 |
| chunk4 | 1397-1406 | 9 (of 10 in range) |

**4. Union of entries covered: 40 of the 42 entries in the window.** Two entries
carry zero events, and **both were flagged deliberately by their scorer**:

- **1382 - flagged by chunk2.** Its preamble states that the LEDGER 1382
  deletion of the own-origin push carve-out is folded as `fix_chain` on the 1381
  row rather than emitted as its own row, because emitting it would be the
  backward reading pin section 6 forbids. Confirmed in the row text: chunk2's
  1381 row carries `fix_chain: 1 (SELF)` and names 1382 as the refutation of that
  remedy. This is the pin working as designed, not a gap.
- **1405 - flagged by chunk4**, in a dedicated Method bullet headed "Entry 1405
  yields ZERO rows". It applies pin section 7 exclusions 2 (external-origin
  claims never adopted), 5 (cross-repo falsification) and 4 (a hypothesis opened
  by the probe that cleared it), and notes claim 3 was confirmed rather than
  refuted.

Neither zero is an extraction miss. Events per entry ranges from 1 to 15, median
5; the heaviest are 1373 (15 events), 1406 (11) and 1393 (10).

---

## 6. LIMITS

1. **This is a tally of what four scorers wrote, not an independent re-reading of
   the ledger.** It re-derives every count from the per-event rows, which fixes
   the mis-summarisation defect it was built for, and it fixes nothing else. If a
   scorer read an entry wrongly, mis-attributed a claim, or assigned a legal but
   incorrect value, this tally reproduces that error faithfully and reports it as
   a clean number.
2. **It cannot detect a shared misreading.** Four scorers converging on the same
   wrong interpretation of a pin field looks identical here to four scorers being
   right. Agreement between passes is not evidence. The one place this was
   actively checked is `fix_chain` direction, because pin section 0 names it as
   the field where two readers of one tree returned disjoint sets: all four RC
   preambles state FORWARD explicitly and the statements were read, not inferred.
   Every other field was taken as written.
3. **The extraction and the scoring were not independent of each other.** Pin
   section 8 item 1 asks whether the party that extracted the events also
   bucketed them. For RC, each scorer both extracted and scored its own chunk, so
   RC's re-score carries the same defect LW's original census did and LW's
   re-score does not. This tally does not remedy that; a tally cannot.
4. **Every count here is a FLOOR**, per pin section 8 item 3. The corpus is the
   RC ledger, authored by the party being measured, and a refuted pass is what an
   author is least likely to write down. Events absent from the ledger are absent
   from these rows.
5. **The `correct` field returned 100 percent YES and carries no information.**
   It is reported because the pin asks for it, not because it discriminates.
6. **The window boundary is inherited, not verified here.** This tally checks
   that every row falls inside 1365-1406 and that 40 of 42 entries are covered.
   It does NOT verify that 1365-1406 is the right window, nor that the events
   inside each entry were exhaustively extracted - only that what the scorers
   emitted is internally consistent.
7. **56 rows (28.3 percent) carry an `uncertain` note and 24 (12.1 percent) a
   `pin_gap`.** Those are free text and are counted, not read, by this tally. A
   reader who wants to know how stable the distributions are should read those 56
   notes; several propose a different legal value for the same row.
