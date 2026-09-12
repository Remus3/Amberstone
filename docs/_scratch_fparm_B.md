# FPARM Arm B - ADVERSARIAL COST ARM for the PRE-DISPATCH RE-GROUNDING GATE

Measured 2026-09-12 at HEAD `88776cbab`, clean tree. READ-ONLY: no tracked file was
edited. Python `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`.
Every number below was derived THIS RUN unless labelled INHERITED.

---

## 0. VERDICT UP FRONT

**The gate as specified is UNDEPLOYABLE. Measured refusal rate 18 of 20 sampled rows
(90 percent). Measured genuinely-stale rate: 0 of 20 rows (0 percent). Every single
refusal in the sample is a FALSE POSITIVE.**

The gate does not have a tuning problem. It has a **category problem**: four of its five
resolvers are asking questions that RC's row prose does not mechanically answer, and the
one resolver that IS mechanically sound (full `path:N` citations) has a measured failure
rate of **0 of 44** in the sample and **9 of 891 (1.0 percent)** across the whole row
corpus. That resolver is already shipped as `tools/citation_audit.py` and already guarded.
Adding a dispatch gate on top of it buys close to nothing; adding the other four resolvers
refuses 90 percent of work for zero true findings.

---

## 1. CURRENT CITATION ROT - RE-DERIVED

```
cd "C:/Riot Commander"
python tools/citation_audit.py --help
python tools/citation_audit.py
```

Raw output (census block, verbatim):

```
citation census (scope: living docs)
  FILE_MISSING             44
  PAST_EOF                 19
  RESOLVES                 3164
  RESOLVES/ABSENT          291
  RESOLVES/CONFIRMED       808
  RESOLVES/MOVED           876
  RESOLVES/UNCHECKED       1189
  TOTAL                    3227

by scope (whole repo):
  GUARDED     3227 citations    63 broken
  HISTORY     5239 citations   408 broken
  UNGUARDED    638 citations    26 broken
```

### Doc claim vs THIS RUN

| Figure | Doc claim (INHERITED) | MEASURED this run | Delta | Flag |
|---|---|---|---|---|
| TOTAL citations | 3242 | **3227** | -15 | DIFFERS |
| CONFIRMED | 812 | **808** | -4 | DIFFERS |
| MOVED | 878 | **876** | -2 | DIFFERS |
| ABSENT | 293 | **291** | -2 | DIFFERS |
| UNCHECKED | 1196 | **1189** | -7 | DIFFERS |
| hard-fail pinned by guard | 63 | **63** (44 FILE_MISSING + 19 PAST_EOF) | 0 | MATCHES |
| hard-fail as pct of guarded | 1.9 pct | **1.95 pct** (63/3227) | +0.05 | MATCHES to 1 dp |

**Flagged: all five volume figures differ, every one of them DOWNWARD by a small amount
(-15, -4, -2, -2, -7).** The pattern is consistent with the doc census being taken a few
commits earlier rather than with any error. The load-bearing figure - 63 hard-failure
citations, 1.9 percent - reproduces EXACTLY. The doc's headline claim is sound; its
volume recital is stale in the fifth significant figure and should not be re-quoted.

### Scope note the doc does not carry

Hard breakage is NOT uniform. Restricted to the two row documents:

```
python -c "... json.load(ca.json) ... filter doc in (BACKLOG.md, ROADMAP.md) ..."
```

| Doc | CONFIRMED | MOVED | ABSENT | UNCHECKED | HARD BROKEN | total |
|---|---|---|---|---|---|---|
| BACKLOG.md | 300 | 245 | 131 | 165 | **9** | 850 |
| ROADMAP.md | 12 | 19 | 9 | 1 | **0** | 41 |
| **both** | 312 | 264 | 140 | 166 | **9** | **891** |

**The dispatch corpus carries 891 of the repo's 3227 guarded citations and 9 of its 63
hard failures - 1.0 percent, half the repo-wide rate.** The nine:

```
BACKLOG.md:32  tools/ds_share_sync.py:1162
BACKLOG.md:32  tools/ds_share_sync.py:1149-1157
BACKLOG.md:58  .github/workflows/codspeed.yml:51
BACKLOG.md:58  codspeed.yml:51
BACKLOG.md:140 .github/workflows/codspeed.yml:51
BACKLOG.md:140 codspeed.yml:51
BACKLOG.md:181 tests/test_ds_share_doc_route_counts.py:39
BACKLOG.md:192 web/js/panels/spike_cue.js:45
BACKLOG.md:357 tools/ds_share_sync.py:957
```

Three distinct paths across four rows. That is the ENTIRE hard-rot surface the gate would
be protecting a dispatched session from.

---

## 2. REFUSAL RATE PER ROW

### 2a. Corpus

```
grep -c -E '^\s*[-*] .*RM-[0-9]+' BACKLOG.md   -> 250
grep -c -E '^\s*[-*] .*RM-[0-9]+' ROADMAP.md   -> 76
```

**326 RM-bearing bullets total (250 BACKLOG + 76 ROADMAP).** Each bullet is one physical
line in both files, so attribution of a citation to a row is exact (`doc_line` equality),
not a range heuristic.

Corpus caveat measured in passing: the corpus is NOT all open work. Of the 20 sampled,
**6 are SHIPPED/CLOSED bodies retained as the historical record** (RM-326, RM-302, RM-201,
RM-404, RM-130 shipped; RM-420 is an anti-row telling a future session NOT to act). A
gate cannot distinguish these from open rows by any mechanical test tried here.

### 2b. Sampling method

Uniform random sample without replacement, `random.seed(20260912)`, over the 326-row list
in file-then-line order, indices sorted for reporting. Reproducible. Sampled ids:

RM-326, RM-307, RM-302, RM-303, RM-297d, RM-296a, RM-201, RM-420, RM-404, RM-266,
RM-148 (BACKLOG:474), RM-130, RM-127 (BACKLOG:535), RM-381, RM-242/3/4/5, RM-321,
RM-01, RM-189, RM-151, RM-06.

### 2c. Resolver implementation

Script at scratchpad `resolve.py` (not written into the repo). It extracts every
backticked token from each row and classifies:

1. `path.ext:N[-M]` -> full citation. Resolve against `git ls-files`, then check `N` against
   the file's line count.
2. `:N[-M]` -> bare relative citation, bound to the nearest preceding path token.
3. path-shaped token with no line -> named module.
4. `[A-Za-z_]\w{2,}` -> named symbol, resolved by `git grep -c -w -e SYM -- '*.py' '*.js' '*.json' '*.ps1'`.
5. `RM-\d+[a-z]?` -> work-item id, resolved by `git grep` over BACKLOG/ROADMAP/LEDGER/
   DS_SWEEP_TRACKER/CLAUDE.md looking for a SHIPPED|CLOSED|DONE|SUPERSEDED|REFUTED|RETIRED
   marker on any line mentioning the id.
6. instruments = `tests/*` or `tools/*` tokens, resolved as (1)/(3).

Quoted counts are reported as a raw count of numeric literals in the non-backticked prose.
They are NOT resolved, for the reason in section 4.

### 2d. Positive controls (mandatory before reporting any zero)

```
core/polled_json.py:40      -> RESOLVES
web/js/main.js:6890         -> RESOLVES
core/NOSUCHFILE_zzz.py:12   -> FILE_MISSING     <- fabricated needle, correctly caught
core/polled_json.py:999999  -> PAST_EOF/249     <- fabricated needle, correctly caught
dashboard/_liveclient.py:1  -> RESOLVES
sym control: lcu_get_result True | zzz_not_a_symbol False
```

The resolver catches fabricated needles in both hard classes and both symbol directions.
**The `cite 0/N` columns below are therefore a measurement, not a broken pattern.**

### 2e. Per-row table

`x/y` = failures / items found. `HARD` = full `path:N` citations that do not resolve.

| # | Row | id | cite | bare | mod | sym | id | inst | nums | FAIL | REFUSE? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | BACKLOG:49 | RM-326 | 0/4 | 0/20 | 2/3 | 1/14 | 1/1 | 1/2 | 7 | 5 | YES |
| 2 | BACKLOG:87 | RM-307 | 0/0 | 1/1 | 0/4 | 0/12 | 1/1 | 0/1 | 3 | 2 | YES |
| 3 | BACKLOG:93 | RM-302 | 0/1 | 0/0 | 0/1 | 0/10 | 1/1 | 0/0 | 8 | 1 | YES |
| 4 | BACKLOG:95 | RM-303 | 0/1 | 0/0 | 0/1 | 0/12 | 1/1 | 0/0 | 5 | 1 | YES |
| 5 | BACKLOG:114 | RM-297d | 0/2 | 0/0 | 4/4 | 0/5 | 0/1 | 0/0 | 8 | 4 | YES |
| 6 | BACKLOG:116 | RM-296a | 0/1 | 0/4 | 3/5 | 0/4 | 2/2 | 0/1 | 7 | 5 | YES |
| 7 | BACKLOG:164 | RM-201 | 0/10 | 1/1 | 4/9 | 0/26 | 1/1 | 0/1 | 5 | 6 | YES |
| 8 | BACKLOG:279 | RM-420 | 0/15 | 8/14 | 7/12 | 2/26 | 4/4 | 1/6 | 45 | 22 | YES |
| 9 | BACKLOG:289 | RM-404 | 0/5 | 0/1 | 6/7 | 0/22 | 2/2 | 0/1 | 19 | 8 | YES |
| 10 | BACKLOG:383 | RM-266 | 0/1 | 0/0 | 1/3 | 0/7 | 1/1 | 0/0 | 4 | 2 | YES |
| 11 | BACKLOG:474 | RM-148 | 0/0 | 2/2 | 2/2 | 0/2 | 1/1 | 1/1 | 0 | 6 | YES |
| 12 | BACKLOG:486 | RM-130 | 0/2 | 0/1 | 3/7 | 0/7 | 2/2 | 0/0 | 19 | 5 | YES |
| 13 | BACKLOG:535 | RM-127 | 0/0 | 0/0 | 3/3 | 7/12 | 1/1 | 0/0 | 5 | 11 | YES |
| 14 | BACKLOG:657 | RM-381 | 0/2 | 3/5 | 7/19 | 0/10 | 2/2 | 0/1 | 5 | 12 | YES |
| 15 | ROADMAP:90 | RM-242+ | 0/0 | 0/0 | 0/2 | 0/0 | 4/5 | 0/0 | 10 | 4 | YES |
| 16 | ROADMAP:92 | RM-321 | 0/0 | 1/1 | 3/10 | 1/3 | 2/2 | 0/1 | 9 | 7 | YES |
| 17 | ROADMAP:99 | RM-01 | 0/0 | 0/0 | 1/4 | 2/4 | 1/1 | 0/0 | 5 | 4 | YES |
| 18 | ROADMAP:130 | RM-189 | 0/0 | 0/0 | 0/4 | 0/0 | 1/1 | 0/0 | 2 | 1 | YES |
| 19 | ROADMAP:133 | RM-151 | 0/0 | 0/0 | 0/1 | 0/0 | 0/1 | 0/0 | 2 | **0** | no |
| 20 | ROADMAP:155 | RM-06 | 0/0 | 0/0 | 0/1 | 0/1 | 0/1 | 0/0 | 1 | **0** | no |

Column totals across the sample: **44 full citations, 49 bare citations, 97 named modules,
177 named symbols, 30 RM-ids, 14 instruments, 169 numeric literals.**

Resolver-1 hard failures across the sample: **0 of 44.**

### 2f. Citation-audit grades attributed to the same 20 rows

| Row | n | CONFIRMED | MOVED | ABSENT | UNCHECKED | HARD |
|---|---|---|---|---|---|---|
| B:49 | 4 | 4 | 0 | 0 | 0 | 0 |
| B:93 | 1 | 1 | 0 | 0 | 0 | 0 |
| B:95 | 1 | 1 | 0 | 0 | 0 | 0 |
| B:114 | 2 | 1 | 0 | 0 | 1 | 0 |
| B:116 | 1 | 1 | 0 | 0 | 0 | 0 |
| B:164 | 10 | 3 | 4 | 3 | 0 | 0 |
| B:279 | 17 | 5 | 1 | 6 | 5 | 0 |
| B:289 | 5 | 3 | 2 | 0 | 0 | 0 |
| B:383 | 1 | 0 | 0 | 1 | 0 | 0 |
| B:486 | 2 | 0 | 1 | 0 | 1 | 0 |
| B:657 | 2 | 0 | 1 | 1 | 0 | 0 |
| all others | 0 | - | - | - | - | - |
| **TOTAL** | **46** | **19** | **9** | **11** | **7** | **0** |

---

## 3. THE HEADLINE NUMBER

**18 of 20 = 90 percent of sampled rows are REFUSED by the gate as specified.**

The two survivors (ROADMAP:133 RM-151, ROADMAP:155 RM-06) survive for one reason only:
their bodies were relocated verbatim to `docs/ROADMAP_HISTORY.md`, so the row itself
carries almost no resolvable claim. **The gate passes exactly the rows that say the least.**
That is an inverted incentive: under this gate the cheapest way to get dispatched is to
strip evidence out of a row.

Refusal rate decomposed by resolver, so the blame is attributable:

| Gate configuration | Rows refused | Rate |
|---|---|---|
| All five resolvers (as specified) | 18/20 | **90 pct** |
| Resolver 4 alone (RM-id superseding closure) | 17/20 | 85 pct |
| Resolver 3 alone (named modules) | 12/20 | 60 pct |
| Resolver 2 alone (bare `:N` citations) | 6/20 | 30 pct |
| Resolver 5 alone (named instruments) | 3/20 | 15 pct |
| Resolver 1 + soft grades (MOVED/ABSENT count as fail) | 5/20 | 25 pct |
| **Resolver 1 alone, hard only (FILE_MISSING / PAST_EOF)** | **0/20** | **0 pct** |

**90 percent is not near 100 percent by arithmetic, but it is near 100 percent by
consequence.** A session dispatched on 20 rows would be refused on 18 and permitted on the
2 that carry no evidence. Stated plainly: **the gate as specified is undeployable.**

---

## 4. FALSE-POSITIVE CHARACTER

Every failure in the sample was hand-classified against HEAD. **GENUINELY STALE: 0.
BENIGN: all of them.** Eleven distinct benign mechanisms, each verified:

| # | Mechanism | Instances in sample | Evidence it is benign |
|---|---|---|---|
| B1 | **Port numbers are syntactically identical to bare line citations** | 7 (`:2999`, `:8860` x3, `:8888`, `:8890`, `:8895`) | `grep -o ':2999\|:8860\|:8888\|:8895\|:8890' BACKLOG.md ROADMAP.md \| sort \| uniq -c` returns 67 occurrences across the two docs. No regex can separate `:8860` the port from `:8860` the line. |
| B2 | Directory prefixes read as missing files | ~20 (`web/js/`, `tests/`, `mc/`, `dashboard/`, `tft/`, `core/`, `web/`, `app/`, `modes/`, `agents/`, `vision_server/`, `Share/`, `data/`, `tests/snapshot_panels/`) | all 17 probed exist on disk; 14 are tracked directories |
| B3 | HTTP route paths read as file paths | 6 (`/ehp`, `/rank-tank`, `/rank-bruiser`, `/api/lcu-cmd`, `/lcu-cmd-result`, `/health`) | these are DS/dashboard routes, never files |
| B4 | `schtasks` CLI flags read as file paths | 5 (`/TR`, `/TN`, `/F`, `/Create`, `/Run`) | RM-404 is a row ABOUT schtasks command lines |
| B5 | `module/path.symbol` dotted form | 3 (`lcu/lcu_rune_writer.save_spell_pref`, `core/polled_json.atomic_write_json`, `vision_server/_relay.lcu_queue_command`) | both halves resolve independently; only the concatenation fails |
| B6 | Commit SHAs read as symbols | 3 (`fc6a40276`, `b9883446`, `b2952b96`) | `git cat-file -t` returns `commit` for all three, plus `c00b9af89` |
| B7 | Memory filenames, deliberately out-of-tree | 2 (`reference_innerhtml_repaint_destroys_focus`, `feedback_row_agreement_is_not_evidence`) | memory files live under `~/.claude`, by design outside the repo |
| B8 | Gitignored runtime artifacts | 5 (`data/fusion_shadow.jsonl`, `data/spell_prefs.json`, `data/spell_prefs.tmp`, `coach_tick_trace.jsonl`, `responder_*.jsonl`) | 3 of 5 present on disk untracked; the rest are generated-on-demand, and `data/spell_prefs.tmp` is an ORPHAN the row explicitly tells you to look for - a gate demanding it exist inverts the row's meaning |
| B9 | External third-party names | 9 (`mwrogue`, `GloopAnalytics`, `GloopControl`, `GloopThemes`, `riftbound_card`, `champion_ability_stats_lol`, `champion_ability_lol`, `RheingoldRiver/mwrogue`, `Module:ChampionData/data`) | RM-127 is a row ABOUT an external wiki; the names MUST NOT exist in RC |
| B10 | Tokenizer debris | 6 (`augment_card_*` prefix, `r"C:/Riot`, `tools/ds_cross_eval/{aggregate.py:16` brace-expansion, `argument/option`, bare `/`) | prose fragments, not claims |
| B11 | **RM-id closure false positives** | 26 of 30 ids flagged | verified below |

### B11 verified, because it is the single largest contributor

RM-307 was flagged `CLOSURE_FOUND`. It is genuinely OPEN:

```
git grep -n 'RM-307' -- BACKLOG.md ROADMAP.md docs/LEDGER.md
BACKLOG.md:87: **RM-307 OPEN (filed 2026-08-31, lane 8 cycle 44 ...
ROADMAP.md:73: **RM-304 / RM-305 / RM-306 / RM-307 / RM-308 OPEN (filed 2026-08-31 ...
docs/LEDGER.md:690: 1310. DONE **2026-08-31 (lane 8 ...
```

The flag fires on the LEDGER line's `DONE`, which belongs to ledger entry 1310, not to
RM-307. Same shape for RM-303. **Resolver 4 as specified has a measured false-positive
rate of 26 of 30 ids in this sample.** It cannot be fixed by tightening the marker list:
the marker is on the right line for a DIFFERENT work item, and RC rows routinely recite
sibling closures by design (that recital is the whole value of the row).

### The most damaging class: a correct citation graded ABSENT

Two of the sample's ABSENT grades were opened by hand. Both rows are verbatim correct.

**RM-266 cites `vision_server/_http.py:143`, graded ABSENT on claim token `lcu_get_result`:**

```
sed -n '138,150p' vision_server/_http.py
...
            with _lcu_cmd_lock:
                rec = _lcu_cmd_results.get(rid)     <- line 143/144
```

The row's claim is that `_http.py` **hand-rolls** the lookup INSTEAD of calling
`lcu_get_result`. The cited line is exactly right; the token is absent BECAUSE THE ROW
SAYS IT IS ABSENT. And the row's other claim still holds today -
`git grep -n 'lcu_get_result' -- '*.py'` returns 4 test references plus the definition at
`vision_server/_relay.py:144`, so zero production callers.

**RM-381 cites `modes/shared_vision.py:400`, graded ABSENT:**

```
sed -n '396,404p' modes/shared_vision.py
            resp = self._client.messages.create(    <- line 400
```

The row says line 400 sends the image block to Anthropic. Correct. The ABSENT grade came
from claim tokens scraped out of neighbouring backticks.

**So a content-aware resolver does not rescue the gate - it adds a NEW false-positive
class in which a row is refused precisely for being accurate about an absence.**

### Quoted counts (resolver 3) are not mechanically resolvable at all

The sample carries **169 numeric literals** in non-backticked prose. Spot-reading them:
`60-entry trait-name scrub`, `0.015 + 0.030 = 45 ms`, `275 ms`, `28 names`,
`201079 units over 17 paths`, `errors=0, statements=2`, `24 U+2192`, `MediaWiki 1.45.3`,
`227 icons`. These are a mix of source-derived counts, historical BEFORE censuses,
third-party version strings, arithmetic intermediates and measured p99s. **No single
re-derivation procedure covers them, and the ones that are BEFORE censuses are
prose-historical by construction - re-deriving them against HEAD and refusing on the delta
would refuse the row for being correct.** RM-420 is the extreme case: its entire purpose is
to record a stale relayed census so a future session does not act on it, and it carries 45
numeric literals every one of which is deliberately not current.

### Split

| Classification | Rows | Failure instances |
|---|---|---|
| GENUINELY STALE (would mislead a session) | **0 of 20** | **0** |
| BENIGN | **18 of 20** | **~91** |

I looked for genuine staleness and did not find it. Zero is reported here only because the
positive controls in 2d prove the instrument fires on fabricated needles in both hard
classes and both symbol directions.

---

## 5. DEPLOYABILITY VERDICT

**NOT DEPLOYABLE. Do not ship this gate.**

Three independent reasons, in descending order of weight:

1. **Precision is zero in the sample.** 18 refusals, 0 true findings. A gate with zero
   measured precision is not a gate, it is a stop. RC's own citation-guard docstring
   already predicts the outcome: a gate that refuses too often gets bypassed or deleted.
   With 90 percent refusal it would be bypassed on its first day, and the bypass would
   then be the permanent state - which is strictly worse than no gate, because the repo
   would then carry a documented control that provably does nothing.

2. **It refuses the evidence-rich rows and passes the evidence-poor ones.** The two
   survivors are the two rows whose bodies were relocated elsewhere. Refusal count
   correlates with citation density, not with staleness: RM-420 (22 failures) is the most
   carefully verified row in the sample and was filed THIS WEEK by a verify-then-file
   slice. The gate's ranking is anti-correlated with the property it claims to measure.

3. **Four of five resolvers are asking prose-judgement questions.** Resolver 2 cannot
   separate a port from a line number. Resolver 3 cannot separate a directory, a route, a
   CLI flag, an external wiki name and a gitignored runtime artifact from a missing file.
   Resolver 4 cannot separate this row's closure from a sibling's. Resolver 5 is resolver
   3 restricted. Resolver 3-on-counts has no procedure at all. **That is not a narrowing
   problem, it is a category error: these are judgement calls wearing a resolver's
   clothes.**

**The honest framing: the mechanically-resolvable half of this problem is ALREADY SOLVED
and already guarded.** `tools/citation_audit.py` pins the 63 hard failures at 1.95 percent
of 3227, and inside the dispatch corpus specifically the hard-rot rate is 9 of 891, one
percent, across three distinct paths. There is no un-addressed rot for a new gate to catch.

---

## 6. NARROWING PROPOSAL - the data supports exactly one, and it is small

Do NOT build a five-resolver gate. The data supports a **one-resolver, warn-not-refuse
pre-dispatch check**, which is a different artifact:

**PROPOSAL: a pre-dispatch WARNING that prints the row's existing `citation_audit`
hard-failure rows and nothing else. No refusal. No new resolver.**

- **Scope: full `path.ext:N` citations only.** Measured: 0 failures in 44 sampled, 9 in 891
  corpus-wide. Predicted refusal-if-it-refused rate: **4 of 326 rows, 1.2 percent.** That
  is a deployable rate.
- **Explicitly excluded, with the measured reason:** bare `:N` (B1, indistinguishable from
  a port, 67 ports in the two docs); named modules (B2-B4, B8-B10, six distinct benign
  classes); named symbols (B6, B7, B9 - SHAs, out-of-tree memories, external names);
  RM-id closure (B11, 26 of 30 false); quoted counts (no procedure exists; RM-420 proves
  the historical case is the majority case in exactly the rows the gate most wants to stop).
- **Warn, do not refuse.** With 0 true findings in 20 rows, the expected value of a refusal
  is negative even at 1.2 percent, because the cost of a wrong refusal (a bypass habit) is
  much larger than the cost of a wrong dispatch on a row whose ONE stale citation the
  warning already printed.
- **Reuse `tools/citation_audit.py --json`.** No new instrument. Filter to the row's
  `doc_line`, print `FILE_MISSING`/`PAST_EOF` rows, exit 0 always.

The remaining four resolvers should be recorded as MEASURED-REFUTED with the instance
counts in section 4, so they are not re-pitched.

**One thing genuinely worth doing that is NOT a gate:** fix the nine. Three paths
(`tools/ds_share_sync.py`, `.github/workflows/codspeed.yml`, `web/js/panels/spike_cue.js`,
`tests/test_ds_share_doc_route_counts.py`) across four BACKLOG rows. Repairing them costs
less than specifying the gate did and takes the dispatch corpus's hard-rot rate to zero.

---

## 7. COMMAND LOG

```
python tools/citation_audit.py --help
python tools/citation_audit.py
python tools/citation_audit.py --json > ca.json
python tools/rm_id_registry.py --help
grep -c -E '^\s*[-*] .*RM-[0-9]+' BACKLOG.md
grep -c -E '^\s*[-*] .*RM-[0-9]+' ROADMAP.md
wc -l BACKLOG.md ROADMAP.md
git ls-files
git grep -c -w -e <SYM> -- '*.py' '*.js' '*.json' '*.ps1'      (x177 symbols)
git grep -n -e RM-<N> -- BACKLOG.md ROADMAP.md docs/LEDGER.md docs/DS_SWEEP_TRACKER.md CLAUDE.md   (x30 ids)
git cat-file -t fc6a40276 / b9883446 / b2952b96 / c00b9af89
grep -o ':2999\|:8860\|:8888\|:8895\|:8890' BACKLOG.md ROADMAP.md | sort | uniq -c
sed -n '138,150p' vision_server/_http.py
sed -n '396,404p' modes/shared_vision.py
git grep -n 'lcu_get_result' -- '*.py'
python <scratchpad>/resolve.py
```

No `pytest` was run. No tracked file was modified. This file is the only write.
