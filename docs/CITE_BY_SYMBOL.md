# Cite by Symbol

**A citation that RESOLVES is not a citation that is RIGHT.**

This document publishes one convention and the measurements behind it. It was
requested by a sibling project on the cross-repo channel on 2026-10-01, which is
the only reason it exists as a standalone file rather than as prose scattered
across three places. Before this, the rule lived in `CLAUDE.md`'s boundary
paragraph, in the standing note in `ROADMAP.md`, and in the memory entry
`reference_cite_the_pin_by_symbol_not_by_line`. There was no single artifact to
hand anybody.

- **Status:** living.
- **Audience:** any tree that carries pointers from one file into another, and
  any agent about to write one.
- **Self-consistency note:** this document contains no `file:line` citations, by
  construction. Every pointer below names a file plus a symbol, a quoted phrase,
  or a numbered heading. The only line numbers in it are historical drift data,
  labelled as such, and they are the evidence, not the citations.

---

## 1. The rule

**Cite a pin, guard, constant or other construct by its SYMBOL, and verify it by
grepping the symbol. Never cite it by line number.**

Corollaries that fall straight out of it:

- Where a behaviour has no symbol but has distinctive words, cite a QUOTED
  phrase from the construct itself - a docstring line, an assertion message - in
  preference to a line number.
- Never cite a pinned VALUE in place of the symbol that holds it. A digest
  recited in prose is a second copy of the pin that nothing re-hashes, so it
  rots silently and invites a reader to "fix" the guard to match the prose.
- A number you did not grep this session is not a citation. It is a guess that
  happens to be formatted like a citation.

## 2. Why it binds mechanically, not as style advice

In this repository `CLAUDE.md` auto-loads into context on EVERY turn. A stale
citation in it is therefore not a document defect that someone might eventually
read - it is re-read into the working context of every single turn, by every
agent, for as long as it survives. It is believed by default, because context is
what an agent reasons from.

And nothing flags it. There is no gate in this repository that re-resolves a
`file:line` citation and reports a mismatch. The three stale cites described in
section 3 were corrected BY HAND after a reader noticed the text did not match
the claim. **Do not record this problem as solved here, and do not cite RC as
having closed it.** The convention is the mitigation; there is no detector.

The same mechanism applies to any always-loaded instruction file in any tree -
a project memory file, an agent prompt, a system preamble. The narrower the
budget and the higher the reload frequency, the worse a stale pointer is, which
inverts the intuition that short always-loaded files are the safe place for
terse citations.

## 3. The measured evidence

### 3.1 RC, 2026-09-30: sampling does not work on this failure class

Three line-number citations in ONE paragraph of `CLAUDE.md` were found stale, by
roughly 26, 97 and 140 lines.

- **Every one of the three still RESOLVED.** Each pointed at a real line of a
  real file. The text at that line was unrelated to the claim. Nothing errored,
  no tool complained, and no reader had noticed.
- Two of the three landed inside the RIGHT FILE and the WRONG CONSTRUCT, which
  is precisely the case a unique-text matcher is least able to see.
- **A FOURTH citation in the same paragraph was CORRECT.** A spot check of one
  citation would therefore have passed the rotten paragraph.

The last point is the one worth carrying: **sampling does not work on this
failure class.** Staleness is per-citation and uncorrelated within a paragraph,
so a sample tells you about the sampled pointer and nothing about its
neighbours. Recorded in `WAKEUP_NOTES.md` under the heading sentence "A CITATION
THAT RESOLVES IS NOT A CITATION THAT IS RIGHT."

The first remediation pass REFRESHED the three numbers. That was the weaker fix,
and it was weaker against doctrine the repository already carried - see 3.2.
Both paragraphs now cite by symbol.

### 3.2 RC, earlier: the same two pointers drifted three times

The cross-repo byte pin lives in the symbol `SHARED_SHA256` in
`tests/test_loop_concurrency.py`, and its parametrised consumer is the
`sorted(SHARED_SHA256)` parametrize in the same file. Cited by line number,
those two pointers drifted as follows (historical data, not citations):

- the definition site: `:474` -> `:480`
- the consumer site: `:542` -> `:548` -> `:574`

So the repository had already watched the identical drift twice before the
2026-09-30 incident, and had already written down the cure: the standing note in
`ROADMAP.md` (the archived "three small lanes" row) says to cite the pin by
SYMBOL, never the digest value and never a line number. The 2026-09-30 incident
is what a tree gets for refreshing numbers instead of applying its own rule.
Both of those pointers resolve correctly today when grepped by symbol, and the
symbol has not moved in the sense that matters: there is still exactly one
definition site.

### 3.3 A sibling tree, 2026-10-01: uniqueness is not correctness

A sibling project measured its own register of pointers independently and
reported: **16 of 16 sampled pointers resolved to a line that was NOT the
construct named**, three of them hand-verified at +5, +18 and +439 lines off.

The same tree had earlier reported a scanner that re-resolves a citation by
locating the cited TEXT and treating a UNIQUE hit as a resolution. That is the
trap in its purest form: uniqueness is a property of the pattern, not of the
pointer, so "16 of 16 resolve uniquely" is a far weaker statement than it reads.
A +439 miss can resolve uniquely all day.

Two trees, separate subjects, separate evidence, same conclusion. That is not
treated here as agreement - agreement between two parties is not evidence - but
the two measurements are independent, and each stands on its own.

### 3.4 The general form

**A CITATION THAT RESOLVES IS NOT A CITATION THAT IS RIGHT.**

A line number is an offset into a mutable sequence. Any edit above it shifts it,
and the shifted pointer remains syntactically valid, so the failure is
SILENT by construction: the citation keeps working and stops being true. Every
weaker remedy - refreshing the numbers, sampling a few, re-resolving by unique
text - attacks the symptom and leaves that property in place. Citing a construct
by its own name removes the offset from the pointer entirely.

## 4. The no-symbol case

This is the hard part, and it is the part that decides whether this document is
useful to anyone outside a codebase. Section 1 is trivially right where a symbol
exists. The requester's subject is a 12,159-line plan whose constructs are prose
SECTIONS, not symbols, so "cite the symbol" is simply unavailable, and they are
mitigating with a register of line numbers. Their own framing is the honest one:
that register makes staleness AUDITABLE rather than IMPOSSIBLE.

**Be clear about what this repository has and has not solved.** RC's subjects are
code with symbols. RC has NOT solved per-section citation into a long prose
document. What follows is a ranked set of real options with the cost of each
stated, plus the two partial precedents RC actually runs.

### 4.1 Insert a stable anchor that is itself content (strongest)

Put a named marker INTO the subject at the construct, and cite the marker. The
citation then points at something that MOVES WITH THE TEXT, because it is part
of the text.

Shapes, roughly in order of robustness:

- **An explicit named marker line or comment**, e.g. a line reading
  `ANCHOR: joint-repin-round` placed at the section. Greppable, unique,
  survives arbitrary reordering, and survives rewording of the surrounding
  prose. In HTML-tolerant Markdown an invisible `<a id="...">` or a comment
  achieves the same with no visible change to the rendered document.
- **An explicit heading id**, where the renderer supports it - the same
  mechanism with the anchor fused to the heading.
- **A quoted unique phrase** from the construct. No edit to the subject is
  needed, which is its whole appeal, but it is the weakest of the three: it
  breaks on rewording, and it is exactly the mode the sibling measured at 16 of
  16 wrong when the matcher treated a unique hit as a correct resolution. A
  quoted phrase is a good citation and a bad verifier.

**Costs, stated plainly.** This modifies the SUBJECT, which is not always yours
to modify, and a 12,159-line plan may be under change control, byte-pinned, or
jointly owned - in which case inserting anchors is itself a negotiated act.
Anchors also need to be unique, so they need a naming discipline, and an anchor
that gets copy-pasted with a block becomes a duplicate that breaks the
exactly-one-definition-site check in section 5. The markers are visible clutter
unless the format supports invisible ones.

**This is the only option on the list that CURES rather than mitigates**, because
it is the only one that gives the construct a name.

### 4.2 Cite a heading path rather than a line

Cite `## 9. The joint re-pin round` or the path
`6. Review conventions > Filename grammar table` instead of a line number.

- **Better than a line number** in one specific and important way: when it goes
  wrong it tends to go wrong LOUDLY. A deleted or renamed heading makes the
  citation fail to resolve at all, which is the opposite of the silent failure
  in section 3.4. A grep for a heading path that returns zero hits is a report.
- **Costs.** Headings are not guaranteed unique - repeated sub-headings under
  different parents are common in long plans, and a bare heading cite then
  resolves ambiguously, which puts you back in the resolves-but-wrong regime.
  Numbered headings fix uniqueness and introduce a new rot mode: inserting a
  section renumbers every later one, so every outstanding citation to them goes
  stale AND still resolves. Unnumbered headings avoid renumbering and lose
  uniqueness. Pick which failure you prefer; there is no option without one.
- Granularity is the real limit. Headings exist where the author put them. If
  the construct you need to point at is one paragraph inside a 400-line section,
  a heading path gets you to the section and no further, and the remaining
  distance is where the sibling's +439 lived.

### 4.3 Invert the dependency so the subject registers itself

Instead of an external register pointing INTO the subject, have the subject
EMIT its own index, generated from its own content, and have the citing document
reference entries in the generated index.

- Staleness becomes a build-time or test-time fact rather than a reading-time
  one: regenerate, and a citation to a vanished entry is a missing key, which is
  an error rather than a wrong answer.
- **Costs.** It needs a generator and somewhere to run it, so it is the most
  expensive option here, and it is only worth it when the subject is long-lived
  and heavily cited - which a 12,159-line plan plausibly is. It also only moves
  the problem: the generated index must be keyed on something stable in the
  subject, which means the subject still needs 4.1-style anchors or at minimum
  unique headings. **It is a distribution mechanism for a cure, not a cure.**

### 4.4 Keep a register of line numbers (last resort, and honest about it)

If none of the above is available, a register of line numbers plus a periodic
re-resolution pass is a real mitigation and better than nothing. Two conditions
make it worth running:

1. **Re-resolve ALL of it, never a sample.** Section 3.1 is the reason. A sample
   is close to worthless on this failure class.
2. **Re-resolution must assert the CONSTRUCT, not the presence of the text.** A
   presence test under a unique-hit rule reports uniqueness, which is not
   correctness - section 3.3. The predicate has to be "the line at N is the
   construct named", which in practice means the register has to record
   something ABOUT the target that can be checked, not just where it was.

It remains a mitigation. It makes rot auditable. It does not make rot
impossible, and a document that claims otherwise is overclaiming.

### 4.5 What RC actually runs, and what it does not

Two partial precedents, offered as evidence of what these options cost in
practice rather than as a claim to have solved the case:

- **A marker inserted into a prose subject.** `docs/CHANNEL.md` carries a
  `CHANNEL_VERSION` marker line near its top, and `tests/test_channel_doc_pin.py`
  greps it with the `_VERSION_RE` pattern and compares it against the symbol
  `CHANNEL_PIN`. That is option 4.1 working in production on a prose document.
  **Its granularity is the WHOLE DOCUMENT**, not a section: it answers "which
  version of this file is this" and cannot answer "where is the re-pin rule".
  A per-section version of the same mechanism is the untried step, not a shipped
  one.
- **Heading-path citation.** `docs/CHANNEL.md` uses numbered headings
  (`## 0. Roster` through `## 9. The joint re-pin round`), and
  `docs/PORTABLE_PROJECT_CONVENTIONS.md` cites its own sections by number in
  prose - "Refresh protocol in section 18", and "Section 4 and section 11 exist
  for this". Both resolve today. Both carry the renumbering exposure described
  in 4.2, and neither is guarded.

**What RC does NOT have:** any gate that re-resolves a citation of any kind. The
convention in section 1 is applied by discipline at authoring time. Treat every
claim in this section as describing a practice, not an enforcement.

## 5. Procedure

### What to write

- Name the FILE by path, and the CONSTRUCT by its SYMBOL. Example form, which is
  also the form `CLAUDE.md` now uses for the two cross-repo pins:
  "`ops/loop/slots.py` and `ops/loop/winmutex.py`, pinned by `SHARED_SHA256` in
  `tests/test_loop_concurrency.py`".
- For a behaviour with no symbol, quote a distinctive line of it - for instance
  the NEEDLE-arm runner in `tools/sibling_name_sweep.py`, whose own docstring
  reads "Never matches a code on its own". The quote carries the claim; the
  symbol or function name carries the location.
- Never recite the pinned VALUE. Cite `SHARED_SHA256`, not the digest it holds.
- For prose, use 4.1 or 4.2 above. State which, so a later reader knows what
  kind of failure to expect.

### How a reader verifies one

1. Grep the symbol across the tree.
2. **Confirm exactly ONE definition site.** Anchor the pattern to do it - an
   unanchored grep matches every mention, including mentions inside test
   fixtures and inside prose ABOUT the symbol.
3. Read the construct and confirm it supports the claim that cited it. Location
   is not substance; a correct pointer to the wrong construct is still wrong.

Measured in this tree on 2026-10-02, as a worked example of why step 2 needs the
anchor:

| pattern | hits |
|---|---|
| `SHARED_SHA256` anywhere, `*.py` | 17 across 9 files |
| `SHARED_SHA256 =` anywhere, `*.py` | 4 |
| `^SHARED_SHA256`, `*.py` | 1 |

Only the anchored pattern isolates the definition site. The other three hits of
the unanchored assignment pattern are all in `tests/test_loop_executor.py`: two
are synthetic `SHARED_SHA256 = "<digest>"` strings spliced together inside
f-strings as test fixture text, and one is a comment ABOUT how the live pins are
spelled. None of the three is a pin. `CHANNEL_PIN` behaves the same way: 9
mentions in `*.py`, exactly one anchored definition site, in
`tests/test_channel_doc_pin.py`.

**An empty grep is a claim about your PATTERN, not about the tree.** If the
symbol does not appear, suspect the pattern before concluding the construct is
gone - case, underscores treated as word characters, and a renamed symbol all
present as zero hits.

## 6. What this does not cover

- **Enforcement.** There is no detector in this repository for a stale
  citation of any kind. Everything above is authoring discipline. If your tree
  builds a detector, the hard part is section 3.3: a re-resolver that treats a
  unique text hit as a correct resolution will report a clean sweep over a
  register that is 16 of 16 wrong.
- **Per-section citation into a long prose document.** Section 4 gives options
  and their costs. It does not give a solved mechanism, and RC does not have one
  running at that granularity.
- **Citations to things outside your tree** - another repository, an upstream
  project, a URL, a vendored dependency. The symbol may exist and still move
  without any edit of yours. Treat these as unpinned by default.
- **Whether the cited construct is CORRECT.** This convention makes a pointer
  durable. It says nothing about whether the thing pointed at is true, current,
  or load-bearing. Those are separate audits.
- **Counts, dates, percentages and digests recited in prose.** A recited number
  is a second copy of a fact with no link back to its source, and it rots the
  same way a line number does but without even resolving. Different failure,
  different fix, not covered here.
- **Code that cites itself.** Internal cross-references inside one file, and
  imports, are handled by the language and its tooling. This convention is about
  pointers written in PROSE that cross a file boundary.

---

## Provenance

Every pointer below was grepped and confirmed on 2026-10-02 in this tree. They
are listed by symbol or quoted phrase, in keeping with section 1.

- `CLAUDE.md` - boundary paragraph, which names the pinned artifacts "BY SYMBOL
  only, never by line number".
- `ROADMAP.md` - the archived "three small lanes" row, carrying the standing
  CITE THE PIN note and the `:474` -> `:480` drift.
- `BACKLOG.md` - row RM-499, the request this document answers.
- `tests/test_loop_concurrency.py` - symbols `SHARED_SHA256` (one definition
  site) and the `sorted(SHARED_SHA256)` parametrize.
- `tests/test_channel_doc_pin.py` - symbols `CHANNEL_PIN` and `_VERSION_RE`.
- `docs/CHANNEL.md` - the `CHANNEL_VERSION` marker line and the numbered
  headings `## 0.` through `## 9.`.
- `docs/PORTABLE_PROJECT_CONVENTIONS.md` - "Refresh protocol in section 18" and
  "Section 4 and section 11 exist for this", against its `## 18.` heading.
- `tools/sibling_name_sweep.py` - the NEEDLE-arm docstring "Never matches a code
  on its own".
- `WAKEUP_NOTES.md` - "A CITATION THAT RESOLVES IS NOT A CITATION THAT IS
  RIGHT." and the 26 / 97 / 140-line staleness figures.
- Memory `reference_cite_the_pin_by_symbol_not_by_line` - the consolidated
  statement of the class.
- The sibling's channel note of 2026-10-01 - the 16 of 16 measurement, the +5 /
  +18 / +439 hand-verifications, the 12,159-line prose subject, and the request
  for this document.
