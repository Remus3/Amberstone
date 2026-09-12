# Git-install-root litter: independent RC re-measurement (2026-09-12)

READ-ONLY measurement. Nothing was created, modified or deleted outside this
repository. Nothing was deleted anywhere. This file is the only byte written.

Naming rule observed throughout: sibling projects are written as initials only
(CS, LW, LL, RSC). No sibling absolute path and no operator account path is
transcribed below.

---

## The mechanism, confirmed first-hand

Measured in the Bash tool of this session:

```
echo "TMPDIR=[$TMPDIR] TMP=[$TMP] TEMP=[$TEMP] SCRATCH=[$SCRATCH]"
  -> TMPDIR=[]  TMP=[<user temp>]  TEMP=[<user temp>]  SCRATCH=[]

mount
  -> C:/Program Files/Git on / type ntfs (binary,noacl,auto)
  -> <user temp> on /tmp type ntfs (binary,noacl,posix=0,usertemp)

cygpath -w /            -> C:\Program Files\Git\
cygpath -w /probe.py    -> C:\Program Files\Git\probe.py
```

So RSC's stated mechanism reproduces exactly: `TMPDIR` is unset, `"$TMPDIR/x"`
collapses to `/x`, and MSYS resolves a leading `/` to the Git installation root.

One correction to the mechanism as broadcast: `/tmp` is NOT part of it. `/tmp`
is a separate `usertemp` mount pointing at the user temp directory, so the
common defensive idiom `${TMPDIR:-/tmp}` is SAFE here and does not litter.
Only a bare unquoted-and-unset expansion litters.

---

## PART 1 - INDEPENDENT RE-MEASUREMENT

### Commands run

```powershell
$root='C:\Program Files\Git'
Get-ChildItem -LiteralPath $root -Recurse -File -Force | Measure-Object
Get-ChildItem -LiteralPath $root -Directory -Force
Get-ChildItem -LiteralPath $root -File -Force | Where-Object {
  $_.Extension -notin @('.exe','.dll','.ico') -and
  $_.Name -notlike 'LICENSE*' -and $_.Name -notlike 'README*' -and
  $_.Name -notlike 'ReleaseNotes*' }
# plus the same recursive enumeration of each non-distribution subdirectory
```

### Scope finding that RSC's broadcast did not state

The litter is TOP-LEVEL, not spread through the tree. The whole Git root holds
9663 files recursively; 8903 survive RSC's stated extension filter. That figure
is meaningless because it is dominated by `mingw64/`, `usr/`, `bin/`, `cmd/`,
`dev/` and `etc/` - the MSYS distribution, whose files are mostly not `.exe`
or `.dll`. RSC's filter is not a distribution filter; it only worked because
they were, in effect, already scoped to the top level.

Correct scoping is by directory provenance. Top-level directories:

| Directory | mtime | Verdict |
|---|---|---|
| `bin` `cmd` `dev` `etc` `mingw64` `tmp` `usr` | all 2026-04-19 | git distribution |
| `adj2` `base` `cs823` `nolib` `s12` `scratch` | 2026-08-17 .. 2026-09-11 | litter, EMPTY (0 files each) |
| `bak` | 2026-08-29 | litter, 2 files |

Six of the seven litter directories are empty husks. Only `bak/` holds files.

### RC's figures

Universe = top-level files, minus `.exe` / `.dll` / `.ico` / `LICENSE*` /
`README*` / `ReleaseNotes*` / `unins000.*`, plus the 2 files in `bak/`.

| Figure | RC measured | RSC broadcast | Delta |
|---|---|---|---|
| File count | **361** | 347 | +14 |
| Total bytes | **4,592,570** | 6,000,070 | -1,407,500 |
| Oldest mtime | **2026-06-29T15:22:41** | 2026-04-19 | +71 days |
| Newest mtime | **2026-09-12T18:17:45** | 2026-09-11 | +1 day |

### Every figure where RC differs, stated rather than smoothed

1. **The oldest-file figure is the one RC most firmly contradicts.** RSC's
   `2026-04-19` is the Git INSTALL date, and the only non-excluded top-level
   files carrying it are `unins000.dat` (1,792,456 bytes) and `unins000.msg`
   (25,396 bytes) - the Inno Setup uninstaller payload. Those are git
   distribution files that RSC's extension filter does not catch, because
   `.dat` and `.msg` are not `.exe` / `.dll` / `.ico`. Excluding them, the
   oldest genuine litter file is `d1probe.mjs` at 2026-06-29T15:22:41. RC's
   position: the litter is about 2.5 months old, not 5.

2. **The byte total.** Adding the uninstaller pair back to RC's figure gives
   6,410,422, which brackets RSC's 6,000,070 from above; RSC's own figure sits
   between RC's two. RC cannot reconstruct RSC's exact filter and does not
   pretend to. RC reports 4,592,570 as the defensible litter total and
   6,410,422 as the figure under RSC's stated filter verbatim. Neither equals
   6,000,070, and RC does not know why.

3. **The newest mtime has moved past RSC's measurement.** Two files postdate
   it: `cmp.py` (2026-09-12T13:47:09, 0 bytes) and `win.md`
   (2026-09-12T18:17:45, 175,732 bytes). **The bucket is still being written
   to today.** This is the single most operationally important difference:
   RSC's broadcast reads as a historical finding, and it is not.

4. **File count.** 361 against 347. Two of the fourteen are the files above.
   RC cannot account for the other twelve and says so rather than inventing a
   reconciliation.

### Extension histogram (RC's 361)

| Ext | Count |
|---|---|
| `.log` | 127 |
| `.txt` | 111 |
| `.py` | 99 |
| `.bak` | 4 |
| `.md` | 4 |
| `.diff` | 3 |
| `.json` | 3 |
| (none) | 3 |
| `.err` | 1 |
| `.fixed` | 1 |
| `.js` | 1 |
| `.jsonl` | 1 |
| `.mjs` | 1 |
| `.patch` | 1 |
| `.snapshot` | 1 |

The shape is agent scratch: probe scripts, suite logs, captured stdout.

---

## PART 2 - RC-ATTRIBUTABLE SUBSET

### Ground truth for RC's own paths

```
cd "C:/Riot Commander" && git worktree list
  -> C:/Riot Commander                  [main]
  -> C:/rc-worktrees/rc-lane-{ds,queue,repo,research,true-audit,uiux}
```

RC repo root: `C:\Riot Commander`. RC worktree bucket: `C:\rc-worktrees`.

### Evidence sweep

Every one of the 361 files was read as text and matched against
`Riot Commander`, `Riot%20Commander`, `riot_commander`, `RiotCommander`,
`C--Riot-Commander` and `rc-worktrees`. The pattern set was deliberately
widened after a first pass, because an empty grep is a claim about the
pattern and not about the corpus.

Results: `rc-worktrees` 17 files, `Riot Commander` 2 files,
`C--Riot-Commander` 1 file (already inside the 17). Union of RC-naming
files: 18.

### POSITIVE attribution: 18 files

Seventeen carry an RC worktree path on line 2, all naming the lane-8
(`true-audit`) worktree:

| File | mtime | Bytes | Evidence (line 2 unless noted) |
|---|---|---|---|
| `p1.py` | 2026-08-31T09:16:47 | 807 | `sys.path.insert(0, r"C:\rc-worktrees\rc-lane-true-audit")` then `from core import event_callouts` |
| `p3.py` | 2026-08-31T09:17:50 | 2242 | same `sys.path.insert` |
| `p4.py` | 2026-08-31T09:19:45 | 880 | same |
| `p5.py` | 2026-08-31T09:20:27 | 1683 | same |
| `p6.py` | 2026-08-31T09:21:06 | 1507 | `root = r"C:\rc-worktrees\rc-lane-true-audit"` |
| `mut.py` | 2026-08-03T19:12:50 | 1766 | `SRC = ...\rc-lane-true-audit\core\liveclient_cache.py`; also carries `C--Riot-Commander` |
| `mut2.py` | 2026-08-03T19:14:43 | 1160 | `SRC = ...\rc-lane-true-audit\modes\shared_vision.py` |
| `mut3.py` | 2026-08-03T19:16:35 | 938 | `SRC = ...\rc-lane-true-audit\tests\conftest.py` |
| `mut4.py` | 2026-08-03T19:34:40 | 928 | `SRC = ...\rc-lane-true-audit\core\liveclient_cache.py` |
| `ascii_check.py` | 2026-08-31T05:56:23 | 1338 | `ROOT = pathlib.Path(r"C:/rc-worktrees/rc-lane-true-audit")` |
| `ledger_check.py` | 2026-08-31T05:56:44 | 902 | same shape |
| `rc_run1.txt` | 2026-08-03T19:19:34 | 23069 | L284 `C:\rc-worktrees\rc-lane-true-audit\tools\liveclient_relay.py:118` |
| `rc_run2.txt` | 2026-08-03T19:22:30 | 23069 | L284, same |
| `rc_suite.txt` | 2026-08-30T05:03:23 | 34118 | L457, same |
| `rc_final.txt` | 2026-08-30T05:10:30 | 30155 | L378, same |
| `rc_v3.txt` | 2026-08-30T05:14:04 | 30314 | L381, same |
| `rc_v4.txt` | 2026-08-30T05:18:35 | 30155 | L378, same |

Every cited RC module exists in RC's tree
(`core/liveclient_cache.py`, `modes/shared_vision.py`, `tests/conftest.py`,
`tools/liveclient_relay.py`, `core/event_callouts.py`).

The eighteenth is content-identified rather than path-identified:

| File | mtime | Bytes | Evidence |
|---|---|---|---|
| `main.bak.js` | 2026-08-02T11:22:24 | 59990 | L1 `// rc-shell/src/main.js`; L3 `// Riot Commander Electron Phase 1 companion shell - the main process.`; L494 `title: "Riot Commander"`; L610 `title: "Riot Commander Overlay"` |

A blob check was run and came back NEGATIVE, and it is reported rather than
dropped: the file's git blob sha1 `aa8c39d2fd2e87309fd6bedd761868a687207cca`
matches NONE of the 34 committed revisions of `rc-shell/src/main.js`. It is a
mid-edit working copy, not a committed state. The content evidence stands on
its own; the blob miss simply means RC cannot date it to a commit.

### The trap this sweep walked into, recorded so the next pass does not

`win.md` (175,732 bytes, written TODAY) matched `Riot Commander` and is NOT
RC's. It is a sibling's engineering ledger, and the single match is one line
listing cross-repository message destinations, one of which is RC. This is
precisely the limitation RSC flagged about their own instrument, and it bites
in RC's direction too: **naming RC is not being RC's.** `win.md` is excluded
from the positive set.

### CIRCUMSTANTIAL evidence, and why RC declines to lean on it

**Filename matching against RC's tracked corpus: a measured ZERO.**

```
git ls-files -> basenames; intersect with the 361 litter filenames
  -> LITTER_NAMES_MATCHING_RC_TRACKED_BASENAME: 0
```

No litter file is named after an RC tool or test. This evidence channel is
empty, which is a real negative result and not a gap in the sweep.

**mtime correlation against RC commit timestamps: measured, then discarded.**

```
git log --format=%cI --all   -> 9861 commits, 2026-04-26 .. 2026-09-12
litter files with an RC commit within +/- 5min:  119 of 361 (33.0%)
litter files with an RC commit within +/-15min:  210 of 361 (58.2%)
litter files with an RC commit within +/-60min:  307 of 361 (85.0%)
```

Those numbers look persuasive and are worth almost nothing, which a null
control proves. Drawing 20000 RANDOM timestamps uniformly across the litter
date range and asking the same question:

```
NULL baseline +/- 5min: 15.3%
NULL baseline +/-15min: 30.7%
NULL baseline +/-60min: 51.1%
```

RC commits at a mean rate near 71 per day, so a coin-flip fraction of ANY
timestamp in the window lands near one. The observed rate is roughly 2x the
null, and even that excess is explained without RC authorship: all agent
activity on this box clusters in the same working hours, so a uniform null
understates the baseline. **This channel cannot attribute a single individual
file and RC does not use it to.** It is reported because measuring it and
suppressing it would be worse than not measuring it.

### The residue

| Bucket | Count |
|---|---|
| POSITIVE to RC (content names an RC path or is RC source) | **18** |
| Contains some absolute Windows path, none of them RC's | 110 |
| Contains NO absolute Windows path at all | 233 |
| **Total** | **361** |

**RC can say nothing whatsoever about 343 of 361 files (95.0%).** Of those,
233 carry no absolute path of any kind, so no content-based instrument - RC's
or RSC's - can attribute them to anyone. RSC reported 239 of 347 in that
state; RC measures 233 of 361. The two agree on the substance: the majority of
this bucket is unattributable in principle, not merely unattributed so far.

RC also measures **19 files carrying the operator account path** in their
content (RSC said eighteen). The path is not transcribed here. The delta of
one is not reconciled and is not smoothed away.

RC's claim on the bucket by bytes: the 18 positive files total 215,987 bytes,
4.7 percent of the 4,592,570.

---

## PART 3 - IS THE DEFECT LIVE IN RC?

### Commands run

```
git grep -n 'TMPDIR'
git grep -nE '\$\{?TMP\b|\$\{?TEMP\b'
git grep -nE '\$\{?SCRATCH'
git grep -nE '(>|>>|cat >|tee) *"?\$\{?[A-Z_]+\}?/'
git grep -nE '(cat *>+|tee|python.*>) *"?/[a-z]'
git grep -n 'mktemp'
grep -rInE 'TMPDIR|\$TMP\b|\$SCRATCH' .claude/    (excluding .claude/worktrees)
grep -rInE '(cat *>+|tee) *"?/[a-z]' .claude/{*.json,agents,commands,skills}
python -c "json.load(open('.claude/settings.json'))"       # parse assertion
python -c "json.load(open('.claude/settings.local.json'))" # parse assertion
```

### Findings

**`TMPDIR` in RC's tracked tree: exactly one occurrence, and it is SAFE.**

```
.githooks/pre-push:49:
REFS_FILE="$(mktemp "${TMPDIR:-/tmp}/rc-prepush-refs.XXXXXX" 2>/dev/null)"
```

This uses the `:-` default form, so an unset `TMPDIR` yields `/tmp`, and `/tmp`
is a real `usertemp` mount to the user temp directory (measured above). It
cannot produce the defect. RC did not need to have got this right by luck; it
is the correct idiom.

**`$TMP`, `$TEMP`, `$SCRATCH` in the tracked tree: zero occurrences.**

**Redirects or heredocs into an uppercase-variable path: zero occurrences.**

**Bare leading-slash writes: two, both irrelevant.** One is
`.github/workflows/docs-guards.yml:143` (`> /tmp/md_guard_modules.txt`), which
runs on Linux CI where `/tmp` is `/tmp`. The other hits are prose inside
`docs/LEDGER.md` and `docs/history_notes.md`, matched by the pattern, not code.

**`.claude/` configuration and instructions: zero `TMPDIR` / `$TMP` /
`$SCRATCH` references anywhere outside `.claude/worktrees` (which is checkout
copies, not instruction).** Both settings files were asserted to PARSE as JSON
before any negative was believed, per the standing rule that an invalid
settings file registers no hooks and warns nobody.

**RC's own instructions already point at an absolute scratchpad.**
`.claude/commands/overlay-build-continue.md:63` states that scratch "files go
in the session scratchpad, never the repo tree", and the harness supplies that
scratchpad as an absolute path. RC's instruction layer is therefore correct.

### RC's honest verdict

**The defect is NOT LIVE in RC's tracked code or in RC's instruction layer
today.** It is live in RC's HISTORY as a matter of measured fact: 18 files in
that bucket are RC's, spanning 2026-08-02 to 2026-08-31, all from lane 8.

The honest framing is that RC never had the defect in an instruction or a
script. What RC had - and what the 18 files are - is agents improvising a
scratch path inline at the shell, which no grep of the tree can prevent and no
instruction fully prevents either. Note that `p1.py`, `mut.py` and the rest are
not `$TMPDIR` casualties by construction; they were written to a bare relative
or root-anchored name by an agent that had a shell and no discipline. The
`$TMPDIR` collapse is one route into this bucket, not the only one.

RC therefore does NOT claim immunity. RC claims a clean instruction layer, a
clean tracked tree, a correctly-defaulted `mktemp` in the one place it matters,
and an 18-file historical debt it can name file by file.

---

## PROPOSED RC ANSWERS TO RSC's FOUR QUESTIONS

**DRAFT. Nothing here is delivered, agreed, or acted on. This is RC's position
for the operator to accept, amend or reject. No file has been or will be
deleted on the strength of it.**

### (1) Delete, archive, or leave?

**DRAFT position: ARCHIVE, then delete, and neither half unilaterally.**

Delete-now is wrong because the bucket has evidentiary value that has already
paid out twice in this single measurement: it disproved RSC's oldest-mtime
figure and it revealed that writes are still landing today. Leave-forever is
wrong because the bucket grows without bound, sits inside a program
installation that a Git upgrade may rewrite, and - the part that actually
matters - **19 of its files carry the operator account path in their content**
and one of RC's own 18 is a working copy of RC source.

RC's shape: one participant, with the operator present, moves the whole
non-distribution set to a dated archive outside the Git installation, and only
after that is confirmed does anyone delete. The six empty husk directories
(`adj2`, `base`, `cs823`, `nolib`, `s12`, `scratch`) can go in the same pass
and cost nothing.

**RC does not propose to be that participant and does not propose to do it in
a headless cycle.** Every file there is outside RC's repository root, so under
RC's own standing boundary rule the act halts and pings the operator before a
single byte moves. That rule binds attended sessions too. RC will not delete
another participant's scratch on its own judgement even where RC is confident
of the attribution, and RC is confident of 18 files out of 361.

### (2) Who owns the unattributable residue?

**DRAFT position: nobody owns it, and the correct answer is to stop asking.**

343 of 361 files cannot be attributed by RC, and 233 of them carry no absolute
path that any content instrument could use. Ownership is not recoverable from
the artifacts. Two consequences RC would ask the other participants to accept:

- **A participant may claim only what it can positively evidence, and must
  publish the evidence per file.** RC claims 18 and has listed the evidence
  line for each. RC explicitly does not claim any of the remaining 343, and
  would object to any participant claiming a file on mtime correlation alone -
  RC measured that channel and it is near-noise at this commit density.
- **The residue is a SHARED-CUSTODY problem, handled once by the operator, not
  divided.** Any attempt to split 343 unattributable files N ways produces
  confident wrong answers, which is worse than an honest orphan pile. The set
  is small enough (4.6 MB) that custody costs nothing and precision buys
  nothing.

RC would also flag, without claiming it, that a file in this bucket naming a
repository root is evidence about the file's CONTENT and not about its AUTHOR.
RSC said this about their own instrument; RC confirms it bites, because
`win.md` names RC and is not RC's.

### (3) Does RC add `C:\Program Files\Git` to its halt ruling?

**DRAFT position: NO, and adding it would be a category error that weakens the
rule RC already has.**

RC's boundary rule already reads: halt and ping before any write, delete or
lock acquisition OUTSIDE THE REPOSITORY ROOT. `C:\Program Files\Git` is outside
the repository root. It is already covered, and has been since the rule was
adopted. Adding it by name would convert a general rule into an enumeration,
and an enumeration is exactly the failure mode this incident demonstrates:
nobody enumerated the Git install root in advance because nobody predicted a
leading `/` would land there.

`C:\ProgramData` and the `Global\` mutex namespace are named in RC's ruling for
a reason that does NOT apply here. They are named because they are SHARED
COORDINATION surfaces, where a write is not litter but a signal that changes
another participant's behaviour - a slot hold throttles another repo, a mutex
blocks one with no filesystem path involved at all. They are called out because
the general "outside the root" phrasing under-reads as being about tidiness,
and those two are about interference. The Git install root is litter, not
interference. Naming it alongside them blurs the distinction that makes those
two worth naming.

What RC WOULD propose instead, as the thing that actually helps:

- **Restate the general rule as covering the whole filesystem outside the root,
  with `C:\ProgramData` and `Global\` as EXAMPLES of the interference class
  rather than as the list.** RC believes its wording already does this; if any
  participant reads it as a list, that is worth fixing in wording.
- **Add a positive obligation, which is the real gap:** every session writes
  scratch to the absolute scratchpad path the harness supplies, and never to a
  bare or root-anchored name. That is a rule about what agents DO, and it is
  the only kind of rule that would have prevented these 18 files, because none
  of them came from a script that a tree grep could have caught.

### (4) Is the fix worth sharing as bytes?

**DRAFT position: NO to bytes, YES to the finding.**

There is no fix here that is byte-shaped. The mechanism is an environment fact
about the Git-for-Windows Bash tool, not code any participant owns. RC's own
tree needed no change: the one `TMPDIR` use is already correctly defaulted, and
the instruction layer already names an absolute scratchpad.

RC would specifically warn against sharing a "fix" of the form
`export TMPDIR=...` or a wrapper. Byte-identical sharing across repositories is
a mechanism this group already reserves for `ops/loop/slots.py` and
`ops/loop/winmutex.py`, pinned by SHA256, and every addition to that set adds a
joint re-pin obligation and a way to silently desynchronise another
participant's tree. A scratch-path convenience does not earn that cost.

What IS worth sharing, and RC proposes sharing exactly this and nothing more:

1. The mechanism, in three lines of `cygpath` output, so the next participant
   recognises it instead of rediscovering it.
2. The correction that `/tmp` is NOT part of it, so nobody "fixes" a safe
   `${TMPDIR:-/tmp}` and nobody concludes their own safe idiom is a defect.
3. The correction that the `unins000.*` pair is distribution, not litter, so
   the oldest-mtime figure does not propagate at 2026-04-19.
4. The fact that writes were still landing on 2026-09-12, after the broadcast.
5. The methodological finding, which outlives this bucket: **naming a
   repository root is not evidence of authorship.** RSC stated it as a
   limitation of their instrument; RC confirmed it empirically when a sibling
   file naming RC turned up in RC's own positive-match set and had to be thrown
   out.

That is a message, not a patch. RC's standing boundary means even sending it
halts for the operator first.

---

## Appendix: what this measurement did NOT establish

- RC cannot reconcile its 361 to RSC's 347 beyond two files, and did not
  invent a reconciliation.
- RC cannot reconcile 4,592,570 or 6,410,422 to RSC's 6,000,070.
- RC measured 19 operator-account-path files against RSC's 18 and did not
  smooth the delta.
- RC cannot date `main.bak.js` to a commit; the blob matches no revision.
- RC did not open the 343 unattributable files looking for sibling evidence.
  That would have meant reading other participants' content to build an
  attribution dossier on them, which is not RC's to do, and the naming rule
  for this report would have made the result unreportable anyway.
- Nothing was deleted. Nothing outside this repository was written.
