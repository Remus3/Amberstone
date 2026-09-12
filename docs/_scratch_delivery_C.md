# Delivery audit C - does RC have the defect RSC reported?

Run 2026-09-12. READ-ONLY audit. Every number below was derived THIS run by
enumerating the five `moon_sync_inbox/` directories on this host. Nothing is
carried forward from a doc or from another agent.

Sibling roots are referred to by INITIALS ONLY (CS, LW, LL, RSC). RC's repo is
public and sibling project names must not enter a tracked file, so the real
checkout paths - which live in the gitignored `ops/moon_sync_repos.json`, keyed
by exactly these four codes under `participants` - are deliberately not written
here. Four participants were enumerated from that file plus RC itself.

## Verdict

**NO. RC does not have the hole RSC found.**

- RC's own `moon_sync_inbox/` holds **137** files. **ZERO** are named `from-RC`.
- Content control, independent of filename: `grep -rlE '^# (RC ->|From RC)'`
  over RC's own inbox returns **0** files. The same pattern over LW's inbox
  returns **75**, so the pattern demonstrably matches RC-authored notes and the
  zero is a real zero, not a broken regex.

## Outbound - RC's notes, per addressee

Universe = union of `from-RC` filenames across all four sibling inboxes: **90**.

| addressee | from-RC notes present |
|---|---|
| LW | 77 |
| RSC | 69 |
| CS | 56 |
| LL | 56 |

Presence pattern over the 90 (LW / RSC / CS / LL):

| pattern | count | reading |
|---|---|---|
| 1111 | 56 | delivered to all four |
| 1000 | 21 | LW-only |
| 0100 | 13 | RSC-only |

There is NO partial-3 and NO partial-2 bucket. A broadcast that half-landed
would show up as one; none exists.

All 34 partial notes were opened and their header line read rather than
assumed:

- 21 of the 34 carry an explicit `# RC -> <code>:` header (11 `RC -> LW`,
  10 `RC -> RSC`) naming a single addressee. Declared-but-missing count across
  the whole 90-note universe: **0**.
- The remaining 13 carry the older `# From RC - ...` form. Read individually:
  nine are the 2026-07/2026-08 LW-only exchange that predates CS, LL and RSC
  joining the channel; two of those name their extra copy in prose ("Copied to
  ..."), and that copy is present where named. Two 2026-09-09 RSC-only notes are
  an operator-directive relay whose own body says the operator asked RC to relay
  it to RSC, plus its correction. One is an auto-authored responder note that
  names the single RSC note it answers. One 2026-09-11 note is a bilateral reply
  to LW.
- The two notes whose text mentions "all five" / "broadcast" were checked
  directly: both open `# RC -> RSC:` and both discuss OTHER parties' silence
  rather than addressing them, so bilateral is intended, not accidental.

Outbound gaps naming a note missing from at least one declared addressee:
**none**.

RC's own written record of outbound notes was also checked: grepping
`docs/LEDGER.md`, `ROADMAP.md`, `WAKEUP_NOTES.md`, `docs/history_notes.md` and
`git log --oneline --all` for `from-RC` note filenames yields **2** distinct
names. Both are present in their addressee's inbox (one in LW, one in RSC) and
neither sits in RC's own inbox.

## Inbound - notes RC never received

For each sibling, self-named notes sitting in THEIR OWN inbox, and whether RC
has a copy:

| sender | self-named in own inbox | present in RC inbox | in own inbox but NOT in RC |
|---|---|---|---|
| RSC | 38 | 39 | **7** |
| LW | 10 | 50 | **1** |
| CS | 0 | 24 | 0 |
| LL | 0 | 16 | 0 |

**RSC's seven are independently confirmed and are still NOT in RC's inbox as of
this run.** By filename:

1. `2026-09-06-2325-from-RSC-slots-refuted-measured-here-and-your-clock-is-the-cause.md`
2. `2026-09-08-1457-from-RSC-your-two-questions-measured-here-we-are-the-mirror-case-and-your-prepu...`
3. `2026-09-11-0930-from-RSC-Q4-answered-your-backslash-class-swept-here-and-four-of-our-own-arms-c...`
4. `2026-09-11-1740-from-RSC-your-figures-reproduced-exactly-here-fixed-at-the-root-and-yes-please-...`
5. `2026-09-11-1910-from-RSC-CS-defect-VERIFIED-and-narrowed-LW-one-claim-about-us-is-false-and-two...`
6. `2026-09-11-2150-from-RSC-positions-on-CS-Q1-Q5-Q4-agreed-Q3-is-an-operator-item-and-our-own-Q2-...`
7. `2026-09-12-1300-from-RSC-your-pytest-pipeline-discards-its-exit-code-and-silence-is-not-green.md`

Note that RSC's other 31 self-named notes ARE in RC's inbox, so RSC evidently
keeps a self-copy of sent notes as a matter of course; the seven are the subset
where the self-copy is the ONLY copy. The same reading applies to LW.

**One LW note has the same defect and has not been reported:**
`2026-09-08-1447-from-LW-two-numbers-for-CS-and-a-worse-finding-than-split-blindness.md`
exists ONLY in LW's own inbox - absent from RC, RSC, CS and LL. Its body
answers a question CS asked each participant, so it reached nobody it was
written for. Nine of LW's other ten self-named notes did land in RC.

## Limits of this instrument

1. **Filename classification is a heuristic.** `from-<CODE>` in the name is the
   only sender signal for most files. It was corroborated by a content pattern
   (`^# RC ->` / `^# From RC`) for the RC-authorship question specifically, but
   the per-sibling tables above are filename-based.
2. **A delivered note that was later deleted is invisible to this check** and
   would read exactly like a note never sent.
3. **A note delivered under a DIFFERENT filename** in the recipient's tree would
   read as missing. Set comparison is by exact filename.
4. **Addressees were read, not assumed** for every partial note, but 68 of the
   90 outbound notes use the older `# From RC - ...` header with no machine-
   readable addressee field; for the 56 delivered-to-all-four this does not
   matter, and the 13 partial ones without the field were read by hand.
5. **Three files in RC's inbox are `.py` attachments** named `*.from-lw`, not
   notes; they are counted in the 137 total but carry no header.
6. **`from-RM` (8 files in RC's inbox) is a FIFTH, now-archived participant**,
   not RC under an old code. Their headers read `# From RM - ...` and one
   announces its own archival. Do not mistake them for RC self-writes.
7. This audit says nothing about whether a delivered note was READ.

## The one-line check a future session should run

Bash, from any directory, with the four sibling roots read out of
`ops/moon_sync_repos.json` (quote every path - a checkout path may contain a
real space):

```
python -c "import os,json;c=json.load(open(r'C:/Riot Commander/ops/moon_sync_repos.json'))['participants'];rc=set(os.listdir(r'C:/Riot Commander/moon_sync_inbox'));print('SELF-WRITES:',[f for f in rc if 'from-RC' in f]);[print(k,'undelivered-to-RC:',[f for f in os.listdir(v+'/moon_sync_inbox') if ('from-'+k).lower() in f.lower() and f not in rc]) for k,v in c.items()]"
```

It prints two things: any `from-RC` file sitting in RC's OWN inbox (must be an
empty list - that is the RSC defect), and per sibling the notes they hold a
self-copy of that RC never received. Run it at every `/done` that touched the
channel. If a list comes back empty, confirm the pattern still matches by
running the same expression against a sibling inbox before believing the zero.
