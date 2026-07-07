# CANONICAL LLM VAULT SPEC (RC_Knowledge + Sibling-A)

Status: SPEC ONLY. This session writes the doc. A budget-saver-smart (DeepSeek-pro)
or Opus session builds + tests it later, in its own session.

Style: strict 7-bit ASCII. No em/en dashes. No smart quotes. Use ' - ' for a
clause break, '-' otherwise. This rule is enforced by lint (section 7).

Scope: this is the ONE reusable vault architecture. It is built once and stood up
twice - once as the RC knowledge vault (C:\RC_Knowledge), once as the Sibling-A
vault. The two share every rule below; only the domain template layer (section 3.6)
and the seed corpus differ. Where a rule is RC-specific vs LW-specific it is marked
[RC] or [LW]; everything unmarked is shared.

---

## 0. Reconciliation - how the two source drafts were merged

Two drafts were written: Draft A (Karpathy-minimal: flat, 4 types, 4 frontmatter
fields, no Templater, no Python validator) and Draft B (structure-and-guardrails:
5+1 types, per-type folders, timestamp ids, Templater + a Python lint.py gate + a
domain template library + MOC hubs).

The operator's locked constraints decide every conflict, and they pull in BOTH
directions at once:
- The vault is READ by a local llama3.1:8b. Draft A is right that the 8B chokes on
  deep trees, rich frontmatter, many types, and vector RAG. The read surface MUST
  be minimal.
- The operator explicitly wants Templater guardrails + MOC + domain templates
  (Draft B). And the model policy MANDATES that ingest + lint run on a STRONG model,
  never the 8B. So the WRITE/LINT surface can afford structure the 8B never touches.

The resolution principle that settles every conflict: SPLIT THE SURFACES. The 8B
only ever touches the READ surface, so the read surface follows Draft A (minimal,
flat-to-read, index-first, no vector). The strong model owns the WRITE + LINT
surface, so that surface keeps Draft B's enforceable guardrails (Templater on the
human path, a Python lint.py that is the real gate, a domain template library, a
directionality law). A guardrail is KEPT only if it is enforced by the strong tier
or by a deterministic script and is INVISIBLE to the 8B at query time. A guardrail
is CUT if it forces the 8B to classify or parse structure mid-query.

Every specific conflict and its resolution is listed in section 12. Read that
section to see exactly which draft won each decision and why.

---

## 1. Vault folder layout

Vault root is its OWN top-level directory with its OWN git repo, OUTSIDE the project
repo and OUTSIDE any LLM memory dir (the Sibling-A model). This keeps
Obsidian's `.obsidian/` and the vault's `**/*.md` out of every project ripgrep /
Glob / sync sweep, so the vault never pollutes the project's doc-drift scope. This
is a hard requirement, confirmed by probe.

- [RC] root: `C:\RC_Knowledge\`
- [LW] root: a NEW separate root, NOT under `C:\Sibling-A\` (same isolation
  reason). Recommended: `C:\LW_Knowledge\`. (If the operator prefers the vault to
  ride inside the Sibling-A repo for backup, it may live at
  `C:\Sibling-A\docs\vault\` - `.obsidian/` is already gitignored there and
  the repo `.githooks` ASCII backstop then applies - but a separate root is
  cleaner and is the default recommendation.)

Canonical tree (identical for both vaults):

```
<VAULT_ROOT>\
  CLAUDE.md            # the operating contract / schema doc (section 2)
  GEMINI.md            # thin pointer to CLAUDE.md (auditor parity)
  README.md            # one-screen human orientation (NOT read on the query path)
  .gitignore
  .obsidian\           # Obsidian config, root only (git-ignored except allowlist)
  _templates\          # Templater template library (section 3, human path only)
    source.md
    note.md
    entity.md
    moc.md
    <domain>.md        # domain template: web-asset-build.md [LW]; leave absent [RC]
  notes\               # ALL knowledge notes, FLAT. type in frontmatter, not folder.
  raw\                 # captured source artifacts. IMMUTABLE. read, never edit.
  INDEX.md             # the map. Read FIRST on every query. Hand + strong-maintained.
  LOG.md               # append-only chronological op log
  tools\
    lint.py            # schema + link + ASCII validator - THE gate (section 7)
    query.py           # gated cheap-read helper (read-only, section 6)
    selftest.py        # local-8B read self-test harness (section 10)
  docs\
    INGEST.md QUERY.md LINT.md   # operator playbooks (thin; CLAUDE.md is canonical)
```

Decisions baked into this tree (conflict resolutions, full rationale in section 12):

- FLAT `notes/`, not per-type folders. RESOLUTION: Draft A wins on the READ surface.
  Per-type folders (Draft B) would force the 8B to know a directory map before it
  can locate a note, and force the ingester to make a folder-classification decision.
  The `type` frontmatter field carries the same information without a tree. Draft B's
  one benefit of per-type folders - "Templater fires the right template by folder,
  and lint asserts folder==type" - is preserved differently: Templater folder-maps
  can target subfolders of a single `notes/` tree IF the human wants them, but the
  canonical build uses ONE folder-map keyed on a `type` prompt at creation (section
  3.2), and lint asserts `type in enum` directly. No per-type folder is required.

- Kebab-slug filenames (`notes/laplace-smoothing.md`), NOT timestamp ids.
  RESOLUTION: Draft A wins. Timestamp ids (`20260706143012--slug.md`, Draft B) are
  a rename-safety mechanism for humans who reorganize constantly. This vault is
  machine-maintained and small; a kebab slug that MATCHES the wikilink is far more
  legible to an 8B (`[[laplace-smoothing]]` -> `laplace-smoothing.md` is obvious;
  `[[20260706143012]]` is not). Rename safety is instead provided by lint check A
  (dangling-link detection) plus the ingest rename-and-regrep rule (section 5).
  Consequence: there is NO `id` frontmatter field; the slug IS the id.

- `raw/` is the ONE folder split that earns its place: raw artifacts are immutable
  provenance the ingester reads but never edits; a physical boundary makes "do not
  touch raw" enforceable (lint check G).

---

## 2. Vault CLAUDE.md - the operating contract (content outline)

`<VAULT_ROOT>\CLAUDE.md` is the schema layer of Karpathy's three-layer model (raw /
wiki / schema). It is the single file the driving model reads at session start, and
the file lint.py and the auditor both cite - co-locating the contract makes drift
between "what the model does" and "what lint checks" impossible. It is deliberately
SHORT (a long manual is itself context bloat for the 8B on the query path). Write it
verbatim as this content. This is the exact text for the build session to emit.

```markdown
# <VAULT_NAME> - Vault Operating Contract

This is a personal knowledge vault maintained by an LLM: a flat set of markdown
notes with an index. It is NOT the project codebase and NOT project operational
memory - it links out to those, it does not duplicate them.

## Non-negotiables
- 7-bit ASCII only. No em/en dashes, no smart quotes. ' - ' for a clause break.
- One idea per note. Every note must read standalone.
- Every note has valid frontmatter (section below) and a type in the enum.
- Intra-vault links are [[kebab-slug]] wikilinks that RESOLVE. No dangling links.
- Relationships live in the note BODY under a `## Links` heading, NOT in frontmatter.

## Layout
- notes/    all knowledge notes, flat. filename = kebab-slug of the title.
- raw/      captured source artifacts. IMMUTABLE. read, never edit.
- INDEX.md  the map. Read this FIRST on every query. Never vector-search.
- LOG.md    append-only op log. One line per ingest/query/lint/self-test.

## Note types (frontmatter `type:`)
- source  one captured external artifact (one per source). Has source_url.
- note    one self-contained idea or claim, in your own words. Absorbs both a
          single-source claim and a multi-note synthesis (link count shows which).
- entity  the one canonical page for a recurring thing (a tool, person, concept).
          A LEAN hub, not a dump. Resolve against existing entities before creating.
- moc     a hand-curated map of one topic: grouped [[links]] with connective prose.

## Frontmatter (required on every note)
title, type, created, tags. `source` adds source_url. Nothing else is required.

## Links
Intra-vault: [[kebab-slug]] wikilinks. To reference project operational memory, use
a PLAIN MARKDOWN file link, NEVER a wikilink, e.g.
[operator profile](file:///C:/Users/Administrator/.claude/projects/C--Riot-Commander/memory/user_operator_profile.md)
Never add the memory/ dir (or any external dir) as a vault folder - it would write
.obsidian junk there.

## MODEL POLICY (HARD)
- INGEST and LINT run on a STRONG model only (budget-saver-smart / DeepSeek-pro,
  or Opus). Atomicity, entity dedup, correct linking, and no hallucinated
  relationships are the hard part - the 8B gets them wrong.
- QUERY/READ runs on the LOCAL 8B (budget-saver) only, via tools/query.py, with a
  narrow prompt and tiny context. The cheap model NEVER creates, edits, links, or
  lints a note. It reads and answers.

## INGEST (strong model only) - see docs/INGEST.md
1. Save the raw artifact verbatim to raw/<slug>.md (immutable).
2. Create notes/<slug>.md, type: source, source_url set, short summary.
3. Extract each distinct idea into its own type: note file, in your own words,
   readable standalone, with ## Links -> [[source-slug]] + related notes.
4. For each recurring thing mentioned, create or UPDATE its type: entity note.
   One canonical entity per thing - resolve against existing titles first.
5. Wire [[wikilinks]] among the new notes under each ## Links heading.
6. Update INDEX.md: add every new note under its section with a one-line gloss.
7. Append to LOG.md: `## [YYYY-MM-DD] ingest | <source title> | +N notes`.
8. Run tools/lint.py; fix every hard-fail BEFORE declaring the ingest done.
A single source may touch 5-15 notes. That is expected.

## QUERY (local 8B, narrow) - see docs/QUERY.md
1. Read INDEX.md. Find the notes relevant to the question.
2. Open ONLY those notes and the ones they [[link]] to (one hop, maybe two). Do NOT
   read the whole vault. Do NOT embed or vector-search - there is no vector index.
3. Answer from what you read; cite the note titles you used.
4. NEVER write. If the answer is reusable, emit a proposed note for a strong session
   to file. Append to LOG.md: `## [YYYY-MM-DD] query | <question>`.

## LINT (strong model only) - see docs/LINT.md
Run tools/lint.py. It is a CONSISTENCY pass only (broken links, orphans,
frontmatter, duplicates, index/log drift, raw immutability, ASCII). It is NOT a
correctness gate; its output is advisory. Never auto-delete on its say-so. Re-run
lint.py yourself before trusting an auditor "all clear". Append to LOG.md:
`## [YYYY-MM-DD] lint | <n> issues found`.
```

GEMINI.md is a two-line pointer: "This vault's operating contract is CLAUDE.md. As
auditor you run a CONSISTENCY pass only (section: LINT). You do NOT judge whether a
claim is true. Never over-trust your own all-clear; re-run lint.py."

---

## 3. Frontmatter schema per note type

RESOLUTION: Draft A's minimal 4-field core wins for the READ surface (the 8B parses
the least YAML possible). Draft B's per-type REQUIRED extras are CUT from frontmatter
and expressed instead as body wikilinks - EXCEPT the two that are genuinely needed
for machine lint and are cheap: `source_url` on sources, and (domain only) the
web-asset manifest fields. Draft B's `id / updated / extracted_from / composed_of /
confidence / entity_kind / aliases / canonical / scope / status` are all cut from the
required set (see 3.3 for where each goes). Enums stay CLOSED (Draft B) so the graph
stays queryable, but the only enum the 8B ever sees is the 4-value `type`.

### 3.1 Shared frontmatter - every note, lint hard-fails if missing

```
---
title: Human Readable Title
type: source | note | entity | moc
created: 2026-07-06
tags: [topic-a, topic-b]
---
```

- `title` - human label, mutable. Mirrors the filename slug but need not match
  byte-for-byte.
- `type` - EXACTLY one of four values (section 4). The only classification the
  reader ever sees.
- `created` - ISO date. One date field only. NO `updated` field (it churns the diff
  on every touch and the 8B never queries it; git records mtime).
- `tags` - flat kebab list, present but may be `[]`. The strong model uses tags to
  group INDEX.md sections; the 8B does not query tags, it reads the index.

### 3.2 Per-type additions

- `source` adds EXACTLY ONE field:
  ```
  source_url: https://...        # or: local | conversation | manual
  ```
  (Draft B's source_type / author / retrieved are optional prose in the note body,
  not required frontmatter - the 8B never queries them and lint would only add
  friction. The build session MAY include them as OPTIONAL keys if the human wants
  Dataview facets, but lint does not require them.)

- `note` adds nothing. It is the graph core; its relationships are body wikilinks.

- `entity` adds nothing in the base schema. (Draft B's entity_kind / aliases /
  canonical are cut from the required set: dedup is enforced by lint check D on
  title/slug collision, not by a `canonical: true` flag the ingester must remember.)

- `moc` adds nothing. Its status (curated topic map vs mechanical index) is
  self-evident: INDEX.md is the mechanical root map; a `type: moc` note in `notes/`
  is a curated topic map with prose.

- `<domain>` [LW] - the web-asset-build note is an `entity` note that ADDS a fixed
  manifest block (section 3.6). This is the one place per-type extra frontmatter is
  required, because those fields mirror real pipeline_state keys and lint validates
  them.

### 3.3 Where each cut Draft-B field went (so nothing is lost, only relocated)

- `id` -> the filename kebab-slug IS the id.
- `updated` -> git history.
- `extracted_from` / `composed_of` -> `[[wikilinks]]` in the note BODY under
  `## Links` (human-legible, not a frontmatter array the 8B must parse).
- `confidence` / `status` -> prose. An uncertain claim opens with `Unverified:`.
  Prose is readable by an 8B; a `confidence: speculative` YAML key is one more thing
  to get wrong.
- `entity_kind` / `aliases` / `canonical` -> entity dedup is a lint check
  (title/slug collision, D), not a flag; the entity's kind is obvious from its prose.
- `scope` -> the MOC's first prose line states its scope.

### 3.4 Compatibility with project LLM memory [RC]

The vault reuses the SAME 4-value `type`-enum SEMANTICS as RC memory/ (user /
feedback / project / reference map loosely to source / note / entity / moc) but is a
SEPARATE store. Do NOT duplicate MEMORY.md. The vault holds DURABLE RESEARCH /
KNOWLEDGE; memory/ holds RC OPERATIONAL rules. The vault MOC/INDEX may link OUT to
memory files via plain markdown file links (section 2 Links rule); it never absorbs
them and memory/ is never a vault folder.

### 3.5 Enum discipline

`type` is a CLOSED set of exactly four values. lint rejects any note whose `type` is
outside it. This is the single enum the 8B sees, and keeping it closed is what lets
the cheap tier trust every note's classification without re-reading the body.

### 3.6 Domain template - web-asset-build [LW only]

`_templates/web-asset-build.md` is an `entity` note specialized for one pipeline
image asset. It mirrors REAL pipeline_state / manifest keys (probe-confirmed) so
notes never invent shape. It is the one required per-type frontmatter extension.

```
---
title: <asset title>
type: entity
created: 2026-07-06
tags: [sibling_a, image-asset]
source_url:          # recovery provenance (DeviantArt etc.) or manual
slug:                # canonical pipeline id (e.g. dark-cosmic-ahri or 1341679)
state:               # FIRST_DONE / CLEANING / ... (matches pipeline_state.json)
stage_folder:        # e.g. "2.First Pass Done"
champion:            # splash subject, optional
recovery_via:        # saucenao | deviantart | manual
upscale_model:       # IllustrationJaNai | ncnn
gates_passed:        # [G0,G1,...]
metrics:             # {msssim:, lpips:, lap_ratio:, halo_pct:, band_delta:}
defect_axes:         # [mid-detail, halo, ...]
delivered_as:        # ###.png if finalized
sha256:
---
# <asset title>
## Identity
## Pipeline history
## Links
- stage: [[<stage-slug>]]   gate: [[<gate-slug>]]   model: [[<model-slug>]]
```

HARD RULE for this template: NEVER embed image bytes or absolute personal paths
(privacy boundary - the same reason Sibling-A gitignores images/** and
recovery caches). Store manifests / metadata + `[[links]]` only. lint enforces the
ASCII + no-absolute-path rule.

Note this template still carries the 4 shared fields, so the READ surface is
unchanged - the 8B reads `type: entity` and the prose sections; the manifest block
is metadata the strong ingester and lint care about, and the human queries via
Dataview if desired. Companion entity notes for the LW domain (created as plain
`entity` notes, no special frontmatter): pipeline stage (first/clean/final/last),
gate (G0-G4), quality metric (msssim/lpips/lap_ratio/halo_pct/band_delta), upscale
model, inpaint/detector tool. These are lean hubs; the asset notes link to them.

---

## 4. Note taxonomy + linking rules

RESOLUTION: FOUR types (Draft A), not five (Draft B). The atomic-vs-molecule split
is CUT because it forces the 8B to classify mid-query for zero query-time benefit,
and it forces the ingester to decide "is this one claim or a synthesis" (a
wrong-classification failure mode). Draft B's directionality LAW is KEPT but
simplified to what four types need - the strong ingester and lint enforce it; the 8B
never reasons about it.

Four `type` values:

1. `source` - one captured external artifact. Provenance anchor. Has `source_url`.
   The ingester mines ideas from it; it is never where synthesis happens. It is an
   extraction LEAF: notes link INTO it, it links out to nothing.

2. `note` - one self-contained idea/claim in your own words. This single type
   absorbs Draft B's `atomic` (a claim from one source) AND `molecule` (a synthesis
   across several). A synthesis note simply links to more notes under `## Links`; the
   link count is self-evident, no type split needed. Every note must read standalone.

3. `entity` - the one canonical page for a recurring thing (tool, person, concept,
   champion, pipeline stage, gate, metric). A LEAN hub, not a dump - durable facts
   live in `note` files that link to the entity; the entity curates and points. One
   canonical entity per thing; the ingester resolves against existing entity titles
   before creating (lint check D catches duplicates).

4. `moc` - a hand-curated map of one topic: grouped `[[links]]` with a sentence of
   connective prose per group (prose is what separates a MOC from an index).
   INDEX.md is the mechanical, exhaustive root map (auto-maintained); a `type: moc`
   note is a curated, opinionated, deliberately-incomplete topic map (Nick Milo:
   gather / develop / navigate). Both are markdown link lists the 8B reads top-down.

Linking rules (the link law - enough for an 8B to never violate, enforced by lint):

- `note` -> `source` (a note links to the source it came from). Body wikilink.
- `note` <-> `note` (associative links - the core of the graph). Body wikilinks.
- `note` -> `entity` (a note links to the entity it is about). Body wikilink.
- `moc` -> everything (a MOC gathers links downward to notes, entities, sub-MOCs).
- `source` -> NOTHING (immutable leaf; notes link INTO it, never the reverse).
- Notes do NOT link UP to their MOC in body edges (the backlink panel surfaces
  membership); this keeps hubs from being pointed at by the whole graph.

All links live in the note BODY as `[[kebab-slug]]` wikilinks under `## Links`.
There is NO frontmatter link graph to maintain, so there is nothing for the ingester
to desync. Optional semantic edge tags in the body are allowed but NOT required
(`supports:: [[slug]]`, `contradicts:: [[slug]]`, `see-also:: [[slug]]`) - they help
the strong model's lint heuristics; the 8B ignores them.

---

## 5. Ingest pipeline + EXACT model policy

Ingest is the HARD part and is STRONG-model-only. It runs from a
`budget-saver-smart.ps1` session (ANTHROPIC_MODEL=rc-deepseek-pro) or a full Opus
session. It NEVER runs on the local 8B.

```
INGEST(artifact):   [profile: budget-saver-smart (rc-deepseek-pro) or Opus]
  0. GUARD: read state.json; if profile is the local tier (rc-main/rc-local), REFUSE
     and tell the operator to relaunch under budget-saver-smart. A single source
     touching 5-15 notes is exactly the relationship-heavy work the 8B mishandles.
  1. raw/<slug>.md      <- artifact verbatim, immutable (provenance frozen).
  2. notes/<slug>.md    <- type: source, source_url set, short summary.
  3. for each distinct idea in the source:
        notes/<idea-slug>.md   type: note, own words, standalone-readable,
                               ## Links -> [[source-slug]] + related notes.
  4. for each recurring thing mentioned:
        resolve against existing entity notes (title + prose match);
        create or UPDATE notes/<entity-slug>.md   type: entity (lean hub).
  5. wire [[wikilinks]] among the new notes (## Links sections).
  6. INDEX.md   <- add every new note under its section, one-line gloss each.
  7. LOG.md     <- append `## [YYYY-MM-DD] ingest | <source title> | +N notes`.
  8. run tools/lint.py; fix every hard-fail before declaring the ingest done.
  RENAME RULE: if a note title changes, rename the file, grep the vault for inbound
  [[old-slug]] links, update them, and re-run lint check A.
```

EXACT model policy (this is the crux; it is enforced three ways):

| Op    | Profile             | ANTHROPIC_MODEL | Backing model                    | Writes vault |
|-------|---------------------|-----------------|----------------------------------|--------------|
| INGEST| budget-saver-smart  | rc-deepseek-pro | DeepSeek v4 pro (cloud reasoning)| YES          |
| LINT  | budget-saver-smart  | rc-deepseek-pro | DeepSeek v4 pro                  | YES (advisory)|
| QUERY | budget-saver        | rc-main         | llama3.1:8b local via LiteLLM    | NO (read+propose)|

Enforcement:
1. The vault CLAUDE.md states the policy in plain language (the driving model reads
   its own manual - primary guard).
2. The ingest playbook's step 0 GUARD reads `state.json.profile` and refuses on the
   local tier. Opus is an allowed override.
3. query.py (section 6) has NO write path, so the 8B on the query path physically
   cannot create/edit notes through it. If the 8B goes off-script via raw filesystem
   tools, the next lint pass catches the frontmatter/link drift - the auditor is the
   backstop, not the gate.

Default supervision: ONE source at a time, human in the loop (Karpathy's
recommendation). Batch ingest is allowed but ONLY on the strong tier and only when
the operator explicitly asks for a batch.

---

## 6. Query / read protocol

This is the 8B's ONLY job and it is deliberately mechanical. It runs from a
`budget-saver.ps1` session (ANTHROPIC_MODEL=rc-main -> local llama3.1:8b), driven by
`tools/query.py` so context stays tiny and the prompt is exacting.

```
QUERY(question):   [profile: budget-saver (rc-main / local 8B)]
  1. Read INDEX.md (one file). It is the map.
  2. Pick the notes whose gloss matches the question.
  3. Open ONLY those notes + the notes they [[link]] to (one hop, maybe two). Keep
     total context under LOCAL_CTX_BUDGET (24000) so no rc-deepseek escalation fires.
  4. Answer from what was read. Cite the note titles/slugs used. No claim without a
     citation.
  5. Do NOT read the whole vault. Do NOT embed. Do NOT vector-search. No vector
     index exists - by design.
  6. query.py is READ-ONLY. It has no write path. If the answer is good and
     reusable, emit a DEFERRED proposal (append to a proposals queue file); the
     actual note creation is an INGEST op only the strong tier may run.
```

WHY no vector/embedding RAG (the load-bearing choice, both drafts agree):
- An embedding index is a separate subsystem the 8B cannot reason about, goes stale
  silently, and fails in ways an 8B cannot detect.
- An index FILE the model reads top-to-bottom is fully legible and human-debuggable.
- At this scale (tens to low hundreds of notes) Karpathy reports the index-file
  approach works well and avoids the need for embedding RAG. We are inside that
  envelope.
- Index + one-hop links keeps the 8B's context tiny (index + 3-6 notes), exactly
  what a 32k-ctx local model needs to not degrade.

Escalation: if the 8B reads the relevant notes and still cannot answer confidently,
it SAYS SO and defers to a strong-model session. It does NOT widen its own read to
the whole vault (that path drowns the 8B - the exact failure LEAN exists to prevent).
On a question the vault cannot answer, the correct 8B behavior is "not in vault" plus
a deferred proposal, NOT invention.

Optional future CLI (NOT built now): if the vault ever outgrows the single-index
approach, add `qmd` (local markdown search, BM25 + vector + LLM rerank, CLI + MCP)
as a shell-out FOR THE STRONG MODEL. Explicitly deferred; at current scale the index
file alone is enough.

---

## 7. Lint / adversarial-auditor checklist + cadence

RESOLUTION: Draft B's Python `lint.py` gate is KEPT - it is the linchpin that lets
the strong tier be trusted and the cheap tier be safe (a model self-report of
"looks consistent" is unreliable; a script's exit code is ground truth). Draft A's
"lint is advisory, never a correctness gate, never over-trusted, never auto-deletes"
framing is KEPT and layered on top: lint.py's HARD-FAIL checks block an ingest from
being declared done, but no check ever asserts a claim is TRUE, and nothing is
auto-deleted on lint's say-so.

`tools/lint.py` runs at the END of every ingest and on a schedule. It is a SCHEMA +
CONSISTENCY validator, NOT a correctness oracle. Exit code is ground truth.

HARD-FAIL checks (block "ingest done"):
```
A. BROKEN LINKS  - every [[slug]] resolves to notes/<slug>.md. Dangling = fail.
B. FRONTMATTER   - every note has title, type, created, tags; type in the 4-enum;
                   source notes have source_url. Missing/malformed = fail.
C. ASCII         - strict 7-bit ASCII across every tracked .md (no em/en dash, no
                   smart quotes). Non-ASCII byte = fail.
D. DUPLICATE     - no two notes share a title/slug; no two entity notes cover the
                   same thing (title/slug collision, entity dedup). = fail.
E. INDEX DRIFT   - every notes/*.md appears exactly once in INDEX.md, and every
                   INDEX.md entry points to a real file. Both directions = fail.
F. SOURCE LEAF   - no source note has an outbound [[link]] under ## Links (sources
                   are extraction leaves). = fail.
G. RAW IMMUTABLE - raw/ files unchanged since their add commit (git check). Any
                   post-add edit to raw/ = fail.
H. [LW] MANIFEST - web-asset entity notes carry the required manifest keys (3.6) and
                   NO absolute personal path / image byte. = fail.
```

WARN checks (report, do NOT block):
```
- ORPHANS   - a note with no inbound link that is not a source and not listed in
              INDEX.md or a MOC.
- MISSING-ENTITY - a thing named across >=3 notes with no entity note yet.
- LOG DRIFT - LOG.md lines that do not parse `## [YYYY-MM-DD] <op> | ...`.
- STALE     - notes a newer source contradicts (heuristic over contradicts:: edges).
```

Adversarial auditor: a CONSISTENCY pass ONLY, run by the GEMINI.md read-only auditor
or a second strong-model pass. It re-runs lint.py's logic independently and reports
the same classes. What it MUST NOT claim:
- It must NOT claim any note's content is TRUE or FALSE. It judges well-formedness
  only, never correctness.
- It must NOT be over-trusted. A "0 issues" result is NOT proof of correctness - it
  only means no STRUCTURAL drift. A flagged issue is a candidate for human review,
  NOT an auto-fix, and NEVER an auto-delete.
- Before believing an auditor "all clear", re-run lint.py yourself (deterministic
  exit code is the ground truth, not the auditor's prose). This mirrors the standing
  project rule "never over-trust a generated report; re-verify against ground truth."

Cadence: lint after every ingest (blocking) and on a schedule / on demand (advisory).
Checks A-H are grep-able / git-able and cheap, so run often. The lint op appends
`## [YYYY-MM-DD] lint | <n> issues found` to LOG.md.

---

## 8. Exact Obsidian plugin list + .gitignore

RESOLUTION: Draft B's plugins (Templater + Dataview + Linter) are KEPT because the
operator explicitly asked for Templater guardrails, and CRUCIALLY every one of them
touches only the HUMAN + Obsidian path - none is on the 8B's read path (the 8B reads
files via the filesystem MCP, not Obsidian). So they add guardrails without taxing
the 8B. Draft A's "near-zero plugins" concern is honored by keeping the set to
exactly three and rejecting all churn-prone plugins.

INSTALL (exactly three):
- Templater - REQUIRED for the human creation path. Template folder = `_templates/`.
  Enable "Trigger Templater on new file creation" + "Folder Templates". Because
  `notes/` is flat, use ONE folder-map: `notes/` -> a dispatcher template that
  prompts for `type` (tp.system.suggester over source/note/entity/moc) and writes
  the matching frontmatter, OR keep four simple templates the human picks via the
  Templater command palette. CRITICAL NOTE: Templater fires ONLY for notes created
  inside Obsidian; Write-tool files (the model path) BYPASS it - lint.py is the
  backstop there. Keep template frontmatter byte-identical to what lint.py expects so
  both paths converge. [LW] add the `web-asset-build.md` template to `_templates/`.
- Dataview - REQUIRED for the human. Powers optional live index tables from
  frontmatter (`TABLE ... FROM "notes" WHERE type = "entity"`). The 8B still reads
  INDEX.md, never Dataview output. Use stable DQL, never DataviewJS (git-friendly,
  easier for the model to reason about).
- Linter (community) - RECOMMENDED. Normalizes frontmatter key order on save so
  human- and model-authored notes diff cleanly. Configure it to NOT reorder keys in
  ways that fight the schema.

DO NOT INSTALL (bloat / git-churn / fights the design):
- Obsidian Git - the driving model commits via the git CLI. Two committers on one
  branch = noise/conflicts. One committer of record (the model).
- Any sync plugin (Obsidian Sync, Remotely Save) - plain git IS the sync.
- Excalidraw / Kanban / Canvas-heavy - large JSON/embedded-image blobs bloat diffs.
- Calendar / Periodic Notes - no daily-note workflow here.
- Disk-caching "database" plugins, auto-tag/auto-link plugins that rewrite bodies on
  open - per-device churn.
- Heavy theme / CSS-snippet packs - keep them out of tracked config or they churn.
Rule: a plugin is safe here IFF its output is deterministic Markdown/YAML and it
writes NO per-device state into tracked files.

Web Clipper (official browser extension, separate from plugins) is OPTIONAL: point
its default template at `raw/` with schema-matching frontmatter so web sources land
in raw/ ready for the strong ingester to process into notes/.

`.gitignore` at the vault root (kills the two real noise sources - per-device UI
state and plugin secrets; tracks the rest so a fresh clone comes up configured):

```
# Obsidian per-device UI state (churns every session)
.obsidian/workspace.json
.obsidian/workspace-mobile.json
# Local caches / derived state
.obsidian/cache
.obsidian/graph.json
.obsidian/*.log
# Plugin secrets - never commit auth tokens (Web Clipper, any sync/git plugin)
.obsidian/plugins/*/data.json
# Obsidian trash
.trash/
# OS cruft
.DS_Store
Thumbs.db
```

After a normal Obsidian session, `git status` must show ONLY note changes - no
`workspace.json`, no `data.json`. If it shows those, the ignore lines are wrong.
Obsidian writes `.obsidian/` ONLY at the vault root; no external dir (memory/,
project repo) is ever a vault folder, so nothing is written outside the root.

Git bring-up: `git init` at the vault root; add the `.gitignore` above; first commit
the seed notes + INDEX.md + LOG.md + CLAUDE.md + GEMINI.md + tools/ + _templates/.
Own repo (Sibling-A model), may share the same API keys as the project. If
pushed to a remote, use a NEW repo, never the project repo.

---

## 9. budget-saver vs budget-saver-smart usage per task

The two launch profiles map exactly onto the two-model policy. Neither script needs
modification; the policy is carried by (a) the vault CLAUDE.md manual, (b) which
launcher the operator opens for which op, and (c) query.py being read-only + the
ingest step-0 guard.

| Task                         | Launcher              | Backing model            |
|------------------------------|-----------------------|--------------------------|
| Ingest a source              | budget-saver-smart.ps1| rc-deepseek-pro (DeepSeek)|
| Lint / audit the vault       | budget-saver-smart.ps1| rc-deepseek-pro          |
| Hard/large ingest override   | plain Opus session    | Opus                     |
| Query / read / answer        | budget-saver.ps1      | rc-main -> llama3.1:8b   |
| Local read self-test         | budget-saver.ps1      | rc-main -> llama3.1:8b   |

Two build-session BLOCKERS flagged by the probes (specs-only; the build session
resolves them, they are NOT vault changes but the query path depends on them):

1. All three local aliases (rc-main / rc-local / rc-background) map to `llama3.1:8b`
   in `ops/budget_saver/config.yaml`, but Ollama currently has only
   `llama3-groq-tool-use:8b` pulled. Local QUERY 404s until EITHER
   `ollama pull llama3.1:8b` OR the three config.yaml model lines are edited to the
   pulled model. Resolve BEFORE the local self-test (section 10).

2. Obsidian's `obsidian.json` currently registers ONE vault at `C:\Riot Commander`
   (the RC repo root). The build session must register the NEW vault root
   (`C:\RC_Knowledge` [RC] / the LW vault root [LW]) as a SEPARATE vault and must NOT
   reuse the RC-root registration (locked decision A).

Filesystem access: the current `lean-mcp.json` scopes the filesystem MCP to
`C:\Riot Commander` only. A vault session needs the vault root in scope. Either add
the vault root to a COPY of lean-mcp.json for vault sessions, or use plain
Read/Edit/Write tools scoped to the vault root. One-line MCP config addition the
build session makes; NOT a change to the RC lean config.

---

## 10. Concrete local-model self-test

`tools/selftest.py` is the acceptance gate the build session runs LAST, from a
`budget-saver` (local 8B) session, to prove the vault is real and the cheap-read path
works end to end. It runs against a tiny seed corpus the strong model ingests first.
PASS = all checks green.

Seed corpus (ingested by the STRONG model before the test, lint-clean):
- 3 `source` notes, 6 `note` notes, 2 `entity` notes, 1 `moc`, all wired with
  `[[links]]`, all listed in INDEX.md.
- [RC] seed ABOUT this very method: a `source` for the Karpathy gist; `note` notes
  for "index-file beats vector RAG at small scale", "one idea per note", "strong
  model ingests, cheap model reads"; `entity` notes for "Obsidian" and "LiteLLM"; a
  `moc` for "llm-wiki-method".
- [LW] seed ABOUT the pipeline: a `source` for the ADR-003 state machine; `note`
  notes for "single upscale only", "G1 is the upscale gate", "SAFE-MOVE is
  copy+fsync+hash+delete"; `entity` notes for "IllustrationJaNai" and "LaMa"; one
  `web-asset-build` entity for a real asset slug; a `moc` for "cleaning-stage".

The self-test (run each check, record PASS/FAIL):

```
SELF-TEST (from a budget-saver / 8B session, via tools/query.py):

T1 REACHABLE   - Enumerate notes/*.md. Assert count == INDEX.md entry count.
                 PASS if the 8B can list the vault and the numbers agree.

T2 INDEX READ  - Read INDEX.md ONLY. Answer a fixed question with a known-correct
                 note ([RC]: "which note explains why this vault uses an index file
                 instead of vector search?"; [LW]: "which note defines the upscale
                 gate?"). PASS if the 8B names the correct note WITHOUT reading every
                 file.

T3 LINK HOP    - Open that note, follow its [[links]] one hop, answer "what source is
                 that claim drawn from?" PASS if the 8B lands on the correct source
                 note VIA the link, not by scanning the whole vault.

T4 NO-VECTOR   - Confirm T2/T3 were answered by reading INDEX.md + named notes only
                 (inspect which files were opened). PASS if NO embedding/vector search
                 was attempted and the 8B did NOT read all notes.

T5 CITATION    - The T2/T3 answers each cite the note title(s)/slug(s) used. PASS if
                 citations are present and point to real files.

T6 CTX BUDGET  - Total context for T2/T3 stayed under LOCAL_CTX_BUDGET (24000), so no
                 rc-deepseek escalation fired. PASS by asserting against the router /
                 usage log (no fallback to rc-deepseek).

T7 WRITE-GUARD - Ask the 8B to add a fact. Expected: query.py has no write path, so
                 the 8B REFUSES to write and instead emits a proposed note for a
                 strong session. PASS if NO file was created/edited by the 8B and a
                 proposal was emitted.

T8 NEGATIVE    - Ask something the seed cannot answer. PASS if the 8B says "not in
                 vault" and files a deferred proposal rather than inventing an answer
                 or a fake [[slug]].

ALL PASS => the vault is built correctly and the cheap-read / strong-write split
holds. Append to LOG.md: `## [YYYY-MM-DD] self-test | 8/8 PASS`.
Any FAIL => fix and re-run before declaring the build done. If the local tier keeps
failing T2-T6, fall back to running QUERY on the smart tier until the fixture passes
(the local-model 404 blocker in section 9 is the most likely first cause).
```

WHY these checks: T1 proves the vault exists and INDEX.md is complete (the map is
trustworthy). T2 proves the 8B navigates by reading ONE file (the core query design).
T3 proves the link graph is traversable one-hop. T4 proves the no-vector design holds
under a real 8B. T5 proves answers are cited/grounded. T6 proves the cheap tier stays
cheap (no silent escalation). T7 proves the read-only guard holds at the point it
matters. T8 proves the 8B refuses to fabricate on an unanswerable question - the
empirical proof behind the strong-ingest / cheap-read bet.

---

## 11. Build order (for the executing budget-saver-smart / Opus session)

1. Strong session: `mkdir <VAULT_ROOT>`, `git init`, write `.gitignore` (8),
   `CLAUDE.md` (2), `GEMINI.md` (2), empty `INDEX.md` + `LOG.md`, `README.md`.
2. Strong session: implement `tools/{lint.py, query.py, selftest.py}`; unit-test
   lint.py against a deliberately-broken fixture (dangling link, bad enum, non-ASCII,
   duplicate) and confirm each hard-fail fires. (Subagents that generate these files
   MUST run ruff/lint before reporting done.)
3. Strong session: register the vault as a NEW Obsidian vault root (9 blocker 2);
   put the vault root in the filesystem MCP scope or use plain Read/Edit/Write (9);
   resolve the local-model 404 (9 blocker 1) BEFORE the self-test.
4. Strong session: install Templater + Dataview + Linter; wire the `_templates/`
   folder-map; [LW] add web-asset-build.md.
5. Strong session: INGEST the seed corpus (section 10 seed) - source + note + entity
   + moc, wired, indexed, logged.
6. Strong session: run `tools/lint.py`. Fix every hard-fail A-H. Commit the seed vault.
7. 8B session (budget-saver): run `tools/selftest.py` (section 10). Record 8/8.
8. On 8/8 PASS: commit, append the self-test LOG line, declare the build done. Any
   FAIL: fix, re-run. Then do ONE real ingest end-to-end on the smart tier, lint
   green, log appended, to prove the live pipeline.

The build is reusable: to stand up the LW vault, repeat steps 1-8 with the [LW] root,
the [LW] domain template (3.6), and the [LW] seed corpus (10). Everything else is
identical.

---

## 12. Conflict-resolution table (every A-vs-B decision, explicit)

| # | Conflict | Draft A (minimal) | Draft B (guardrails) | RESOLUTION | Why |
|---|---|---|---|---|---|
| 1 | Folder layout | flat `notes/` | per-type folders | Draft A (flat `notes/`) | Per-type folders tax the 8B read surface (must know a tree) and force ingester folder-classification. `type` frontmatter carries the same info. |
| 2 | Filenames / id | kebab-slug (slug = id) | `{timestamp-id}--slug.md` + `id` field | Draft A (kebab-slug, no id field) | Timestamp ids aid legibility for humans, hurt it for an 8B resolving `[[links]]`. Rename safety moved to lint A + ingest regrep rule. |
| 3 | Note types | 4 (source/note/entity/moc) | 5 (adds atomic vs molecule) | Draft A (4 types) | atomic-vs-molecule forces mid-query classification for zero query-time benefit and adds an ingester wrong-classification mode. A synthesis is just a note with more `## Links`. |
| 4 | Frontmatter size | 4 core + source_url | 6 shared + many per-type | Draft A core + Draft B enums closed | Every extra required field is a field the ingester fills wrong, lint checks, and the 8B skips. Cut fields relocated to body wikilinks / prose (3.3). The one `type` enum stays closed (B). |
| 5 | Templater | skip it | REQUIRED | Draft B (install) | Operator explicitly wants it. It touches only the human/Obsidian creation path, never the 8B read path, so it adds a guardrail with no 8B tax. lint.py is the model-path backstop. |
| 6 | Python lint.py gate | optional helper | REQUIRED, THE gate | Draft B (required gate) | A model self-report of "consistent" is unreliable; a script exit code is ground truth. It runs on the strong tier only, invisible to the 8B. |
| 7 | Lint authority | advisory, never over-trusted, no auto-delete | hard-fail blocks "done" | BOTH (layered) | lint hard-fails block an ingest from being declared done (B), but no check judges truth and nothing auto-deletes (A). Structural gate + advisory-on-correctness. |
| 8 | Directionality matrix | simple 5-rule list | full 5x5 matrix + 6 checks | Draft A's simpler list, enforced by lint (B) | Four types need only the 5-rule list; the strong ingester + lint enforce it; the 8B never reasons about it. |
| 9 | Domain template | none | web-asset-build (LW) | Draft B (LW only) | The one required per-type frontmatter extension; mirrors real pipeline_state keys so LW notes never invent shape. RC needs no domain template. |
| 10| Plugins | none (+ optional Dataview) | Templater + Dataview + Linter | Draft B's three, Draft A's churn-rejection | All three touch only the human path; keep the set to exactly three and reject every churn-prone plugin (A). |
| 11| MOC vs index | INDEX.md is the root MOC | separate index\ dir of auto-MOCs | Draft A (INDEX.md + curated `type: moc` notes) | One mechanical INDEX.md the 8B reads first + hand-curated MOC notes. No separate auto-generated index dir to keep the tree flat. Dataview gives the human live tables optionally. |
| 12| Self-test size | 6 checks | 5 criteria + negative probe | MERGED to 8 checks | T1-T5 from A, T6 ctx-budget + T7 write-guard + T8 negative-probe from B. Covers navigation, no-vector, citation, cost, read-only, and refusal-to-fabricate. |

END OF SPEC.
