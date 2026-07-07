# RC_KNOWLEDGE_VAULT - Build Spec

Status: SPEC ONLY (this session writes the doc; budget-saver-smart executes + tests it later in its own session).
Author model policy: this spec was drafted by a strong model. Ingest + lint run on a strong model (budget-saver-smart / DeepSeek, or Opus). Gated read/query runs on the local 8B (budget-saver) only.
Style: strict 7-bit ASCII. No em/en dashes. No smart quotes. ' - ' for a clause break, '-' otherwise.

Design bias: KARPATHY-MINIMAL. Flat. Low ceremony. Fewer folders, fewer plugins, less frontmatter. Every folder / field / plugin below had to earn its place against the question "does an 8B reader or a strong ingester actually need this to not fail." If it did not, it is not here.

---

## 0. Why minimal is not a preference here - it is a correctness requirement for a local 8B

The whole reason budget-saver and LEAN_CLAUDE.md exist is that a llama3.1:8b at num_ctx 32768 drowns when you hand it 150 memory files of context. This vault is READ by that same 8B (query op). So the vault's structure IS part of the 8B's context budget, and every ounce of ceremony is a tax the 8B pays on every query. Concretely:

1. Deep folder trees force the reader to hold a directory map in working memory before it can even locate a note. Flat + one index note = the 8B reads ONE file to know where everything is. A tree = the 8B guesses paths and hallucinates.
2. Rich frontmatter (10+ fields per note) burns tokens on YAML the 8B mostly ignores, and every optional field is a field the ingester can fill wrong and the linter must check. Fewer fields = fewer hallucinated relationships, smaller diffs, cheaper lint.
3. Many note TYPES force the 8B to reason about taxonomy ("is this atomic or molecule or entity") mid-query. It gets this wrong. A near-flat type set means the reader never has to classify - it just reads.
4. Vector/embedding RAG is a whole subsystem (index build, staleness, a similarity model) that the 8B cannot reason about and that fails silently. An index file it reads top-to-bottom is legible, debuggable, and free.
5. Karpathy's own stated result: the index-file approach "works surprisingly well at moderate scale (~100 sources, ~hundreds of pages) and avoids the need for embedding-based RAG." We are FAR under that scale. Building the heavy version first is premature complexity that fights the 8B.

Rule of thumb enforced throughout: if a feature helps a frontier model but confuses an 8B, it is cut. The strong model does the hard part (ingest, lint); the 8B does the easy part (read index, follow links, answer). The structure is optimized for the WEAKEST reader, not the strongest writer.

---

## 1. Folder layout (flat, 3 real dirs + 2 files)

Vault root: `C:\RC_Knowledge\` (its OWN top-level dir, its OWN git repo, OUTSIDE `C:\Riot Commander\` and OUTSIDE the memory/ dir - mirrors the Sibling-A pattern). Rationale for a separate root (from probe 3): keeping it out of the RC repo tree means no RC ripgrep/Glob/sync-skill ever pulls vault notes into RC's doc-drift scope, and Obsidian's `.obsidian/` config never lands inside the RC repo. This directly protects the LEAN goal.

```
C:\RC_Knowledge\
  INDEX.md              <- the map. Hand + strong-model maintained. Read FIRST on every query.
  LOG.md                <- append-only chronological record of ingest/query/lint ops.
  CLAUDE.md             <- the schema/operating manual (section 3). Vault-local, NOT RC's.
  notes\                <- ALL knowledge notes live here, flat. No sub-folders.
  raw\                  <- captured source artifacts (pasted text, clipped pages). Immutable.
  .obsidian\            <- Obsidian config (git-ignored except an allowlist; section 8).
  .gitignore
  README.md             <- one-screen human orientation (not read by the query op).
```

That is the whole tree. Three content dirs (`notes/`, `raw/`) plus two operating files (`INDEX.md`, `LOG.md`) plus the schema (`CLAUDE.md`).

WHY flat `notes/` and not entity/concept/source sub-folders:
- Karpathy's gist is deliberately silent on directory layout and calls the structure "intentionally abstract... optional and modular." There is no canonical folder tree to copy.
- Sub-folders would force the ingester to CHOOSE a folder per note (a classification decision it can get wrong) and force the reader to know the tree. A flat `notes/` with a `type` field in frontmatter carries the same information WITHOUT the reader needing to walk directories. The `type` field is queryable; the folder is not (cheaply, for an 8B).
- `raw/` is separate only because raw artifacts are immutable provenance that the ingester reads but NEVER edits - a physical boundary makes "do not touch raw" enforceable. This is the one folder split that earns its place.

Filenames: `notes/kebab-title.md`. Human-readable kebab-case slug, no timestamp prefix. WHY not timestamp-id filenames (the zettelkasten convention): timestamp ids are a rename-safety mechanism for humans who reorganize constantly. This vault is machine-maintained and small; a kebab slug that matches the wikilink is far more legible to an 8B (`[[laplace-smoothing]]` resolving to `laplace-smoothing.md` is obvious; `[[20260706143012]]` is not). If a title must change, the ingester renames the file AND greps the vault for inbound links AND updates them - a lint check covers dangling links regardless.

---

## 2. Frontmatter schema (4 required fields, everything else optional)

Every note in `notes/` carries exactly this frontmatter, and nothing is required beyond it:

```
---
title: Human Readable Title
type: source | note | entity | moc
created: 2026-07-06
tags: [topic-a, topic-b]
---
```

- `title` - human label, mutable. Mirrors the filename slug but need not match byte-for-byte.
- `type` - one of exactly FOUR values (section 4). This is the ONLY classification the reader ever sees.
- `created` - ISO date. One date field only. NO `updated` field - it churns the diff on every touch and the 8B never queries on it; git already records mtime.
- `tags` - flat kebab list, optional-but-present (may be `[]`). Used by the strong model to group INDEX.md sections; the 8B does not query tags, it reads the index.

Source notes (`type: source`) add EXACTLY ONE more field:

```
source_url: https://...        # or: local | conversation | manual
```

That is the entire frontmatter surface. Compare to the maximal zettelkasten schema (id, type, title, created, updated, tags, extracted_from, claim, confidence, composed_of, thesis, entity_kind, aliases, canonical, scope, status ...). Every one of those extra fields is a field the ingester can fill wrong, the linter must validate, and the 8B must skip past. We cut them all. WHY this is safe:
- `id` -> the filename slug IS the id.
- `updated` -> git.
- `extracted_from` / `composed_of` -> expressed as `[[wikilinks]]` in the note BODY under a `## Links` heading, where they are human-legible, not as frontmatter arrays the 8B has to parse.
- `confidence` / `status` / `canonical` / `scope` -> if a claim is uncertain, the note says so in prose ("Unverified:" prefix). Prose is readable by an 8B; a `confidence: speculative` YAML key is one more thing to get wrong.

The linter (section 6) rejects any note missing the 4 core fields or carrying a `type` outside the enum. It does NOT invent required fields beyond these.

---

## 3. The vault's own CLAUDE.md (the operating manual / schema)

This file lives at `C:\RC_Knowledge\CLAUDE.md`. It is the schema layer in Karpathy's three-layer model (raw / wiki / schema). It tells whichever model is driving how to ingest, query, and lint. It is deliberately short - a long manual is itself context bloat for the 8B on the query path. Write it verbatim as below.

```markdown
# RC_KNOWLEDGE - Vault Operating Manual

This is a personal knowledge vault maintained by an LLM. It is a flat set of
markdown notes with an index. It is NOT the RC codebase and NOT RC operational
memory - it links out to those, it does not duplicate them.

## Style
Strict 7-bit ASCII. No em/en dashes, no smart quotes. Use ' - ' for a clause
break, '-' otherwise. One idea per note. Notes must read standalone.

## Layout
- notes/    all knowledge notes, flat, filename = kebab-slug of the title.
- raw/      captured source artifacts. IMMUTABLE. Read, never edit.
- INDEX.md  the map. Read this FIRST on every query. Never vector-search.
- LOG.md    append-only op log. One line per ingest/query/lint.

## Note types (frontmatter `type:`)
- source  a captured external artifact (one per source). Has source_url.
- note    one self-contained idea or claim, in your own words.
- entity  the canonical page for one recurring thing (a tool, person, concept).
- moc     a hand-curated map of one topic, with connective prose + links.

## Frontmatter (required on every note)
title, type, created, tags. `source` adds source_url. Nothing else is required.
Relationships go in the note BODY as [[wikilinks]] under a `## Links` heading,
not in frontmatter.

## Links
Intra-vault links are [[kebab-slug]] wikilinks. To reference RC operational
memory, use a plain markdown file link, NOT a wikilink, e.g.
[operator profile](file:///C:/Users/Administrator/.claude/projects/C--Riot-Commander/memory/user_operator_profile.md)
Never add the memory/ dir as a vault folder (it would write .obsidian junk there).

## MODEL POLICY (hard rule)
- INGEST and LINT run on a STRONG model (budget-saver-smart / DeepSeek, or Opus).
  Atomicity, correct linking, and no hallucinated relationships are the hard part.
- QUERY/READ runs on the LOCAL 8B (budget-saver) with a narrow prompt and tiny
  context. The cheap model NEVER creates or edits notes. It reads and answers.

## INGEST (strong model only)
1. Save the raw artifact verbatim to raw/<slug>.md (immutable).
2. Create notes/<slug>.md, type: source, source_url set, summarizing it.
3. Extract each distinct idea into its own type: note file, in your own words,
   readable standalone.
4. For each recurring thing the notes mention, create or update its type: entity
   note. One canonical entity note per thing - resolve against existing titles
   first, never duplicate.
5. Add [[wikilinks]] between related notes under each note's ## Links heading.
6. Update INDEX.md: add every new note under the right section with a one-line
   gloss. The index is the map - it must stay complete.
7. Append one line to LOG.md: `## [YYYY-MM-DD] ingest | <source title>`.
A single source may touch 5-15 notes. That is expected.

## QUERY (local 8B, narrow)
1. Read INDEX.md. Find the notes relevant to the question.
2. Open ONLY those notes and the ones they [[link]] to. Do NOT read the whole
   vault. Do NOT embed or vector-search - there is no vector index by design.
3. Answer from what you read, and cite the note titles you used.
4. If the answer is good and reusable, hand it to the strong model to file as a
   new note (the 8B proposes; the strong model writes). Append a LOG.md line:
   `## [YYYY-MM-DD] query | <question>`.

## LINT (strong model only - the adversarial auditor)
Run the checks in section 6 of the build spec. It is a CONSISTENCY pass only
(broken links, orphans, missing/duplicate frontmatter, index/log drift). It is
NOT a correctness gate and its output is advisory - never auto-delete on its say-so.
Append: `## [YYYY-MM-DD] lint | <n> issues found`.
```

---

## 4. Note taxonomy (4 types, and why not more)

Exactly four `type` values. This is a deliberate collapse of the 5-type zettelkasten taxonomy (source/atomic/molecule/entity/moc) down to four, because the atomic-vs-molecule distinction is a classification the 8B cannot reliably make and does not need.

1. `source` - one captured external artifact. Provenance anchor. Has `source_url`. The ingester reads it to mine ideas; it is never where synthesis happens.
2. `note` - one self-contained idea/claim in your own words. This ONE type absorbs both "atomic" (a claim from one source) and "molecule" (a synthesis across several). WHY merged: the difference between "a claim from one source" and "a synthesis of three notes" is real for a human zettelkasten purist, but for an 8B reader it is a distinction without a query-time difference - both are just "a note that states an idea and links to what it draws on." Forcing the ingester to pick between them adds a wrong-classification failure mode for zero reader benefit. A synthesis note simply links to more notes under `## Links`; the link count is self-evident, no `type` split needed.
3. `entity` - the one canonical page for a recurring thing (a tool, a person, a concept, a champion). It is a LEAN hub, not a dump - durable facts live in `note` files that link to the entity; the entity page curates and points. One canonical entity per thing; resolve before creating to avoid duplicates.
4. `moc` - a hand-curated map of one topic: grouped `[[links]]` with a sentence of connective prose per group. This is the only place prose-driven organization lives. INDEX.md is the root MOC / degenerate case (mechanical, exhaustive); a `type: moc` note is a curated, opinionated, deliberately-incomplete topic map. Distinction: INDEX.md lists EVERYTHING (auto-maintained); a MOC note SELECTS and CONNECTS (hand-curated). Both are markdown link lists the 8B reads top-down.

Directionality (kept simple enough for an 8B to not violate):
- `note` -> `source` (a note links to the source it came from).
- `note` <-> `note` (associative links - the core of the graph).
- `note` -> `entity` (a note links to the entity it is about).
- `moc` -> everything (a MOC gathers links downward).
- `source` links to NOTHING (it is an immutable leaf; notes link INTO it).
All links live in the note BODY as wikilinks. There is no frontmatter link graph to maintain, so there is nothing for the ingester to desync.

---

## 5. Ingest pipeline (strong model writes, cheap model never does)

The ingest op is the HARD part and is strong-model-only. Sequence (also encoded in CLAUDE.md above so the driving model self-executes it):

```
INGEST(artifact):
  1. raw/<slug>.md        <- artifact verbatim, immutable (provenance frozen)
  2. notes/<slug>.md      <- type: source, source_url set, short summary
  3. for each distinct idea in the source:
        notes/<idea-slug>.md   type: note, in own words, standalone-readable,
                               ## Links -> [[source-slug]] + related notes
  4. for each recurring thing mentioned:
        resolve against existing entity notes (title + prose match)
        create or UPDATE notes/<entity-slug>.md  type: entity (lean hub)
  5. wire [[wikilinks]] among the new notes (## Links sections)
  6. INDEX.md   <- add every new note under its section, one-line gloss each
  7. LOG.md     <- append `## [YYYY-MM-DD] ingest | <source title>`
```

Enforcement of the model policy:
- The vault CLAUDE.md states in plain language that ingest/lint are strong-model-only and query is 8B-only. That is the primary guard (the driving model reads its own manual).
- Operationally: ingest is launched from a `budget-saver-smart` session (ANTHROPIC_MODEL=rc-deepseek-pro) or a full Opus session. Query is launched from a `budget-saver` session (ANTHROPIC_MODEL=rc-main -> local llama3.1:8b). See section 9 for the exact launch wiring.
- The 8B physically CAN write files (it has the filesystem MCP), so the guard is procedural, not hard-enforced. To make the 8B's read path safe, the query prompt (section 7) explicitly forbids creating/editing notes and tells it to hand any new-note proposal to the strong model. A cheap model that goes off-script and edits a note is caught by the next lint pass (frontmatter/link drift) - the adversarial auditor is the backstop, not the gate.

One-at-a-time with a human in the loop is the default (Karpathy's recommended supervision level). Batch ingest is allowed but only on the strong model and only when the operator explicitly asks for a batch.

---

## 6. Query protocol (index-then-links, never vector search)

This is the 8B's ONLY job and it is deliberately mechanical:

```
QUERY(question):
  1. Read INDEX.md (one file). It is the map.
  2. Pick the notes whose gloss matches the question.
  3. Open ONLY those notes + the notes they [[link]] to (one hop, maybe two).
  4. Answer from what was read. Cite the note titles used.
  5. Do NOT read the whole vault. Do NOT embed. Do NOT vector-search.
     There is no vector index - by design.
```

WHY no vector/embedding RAG (this is the load-bearing design choice):
- An embedding index is a separate subsystem the 8B cannot reason about, that goes stale silently, and that needs its own similarity model. It fails in ways an 8B cannot debug or even detect.
- An index FILE the model reads top-to-bottom is fully legible: the 8B sees exactly what exists and why it picked a note. It is debuggable by a human reading the same file.
- At this scale (tens to low hundreds of notes) Karpathy reports the index-file approach "works surprisingly well ... and avoids the need for embedding-based RAG." We are well inside that envelope.
- The index + one-hop-links traversal keeps the 8B's context tiny (index + 3-6 notes), which is exactly what a 32k-ctx local model needs to not degrade. Vector RAG would dump a dozen loosely-related chunks into context and the 8B would lose the thread.

Escalation: if the 8B reads the relevant notes and still cannot answer confidently, it says so and defers to a strong-model session - it does NOT widen its own read to the whole vault (that path leads to the 8B drowning, the exact failure LEAN_CLAUDE.md exists to prevent).

Optional future CLI (NOT built now): if the vault ever outgrows the single-index approach, add `qmd` (local markdown search, BM25 + vector + LLM rerank, has a CLI + MCP server) as a shell-out for the strong model. Explicitly deferred - at current scale the index file alone is enough and adding a search engine now is premature.

---

## 7. Lint / adversarial-auditor spec (consistency only, never over-trusted)

Lint is strong-model-only and is a CONSISTENCY pass, NOT a correctness gate. It never asserts a claim is true or false; it only finds structural drift. Its output is ADVISORY - the operator (or strong model) decides; nothing is auto-deleted on the auditor's say-so.

Checks (each is mechanical and an 8B-independent script can pre-compute most of them; the strong model interprets):

```
LINT:
  A. BROKEN LINKS   - every [[slug]] resolves to a notes/<slug>.md. Report dangling.
  B. ORPHANS        - every note has >= 1 inbound link OR is listed in INDEX.md
                      or a MOC. Report notes reachable from nothing.
  C. FRONTMATTER    - every note has title, type, created, tags. type in the enum.
                      source notes have source_url. Report missing/malformed.
  D. DUPLICATE      - no two notes share a title/slug; no two entity notes cover
                      the same thing (alias/title collision). Report duplicates.
  E. INDEX DRIFT    - every notes/*.md appears exactly once in INDEX.md, and every
                      INDEX.md entry points to a real file. Report both directions.
  F. LOG DRIFT      - LOG.md is append-only and parseable (each op line starts
                      `## [YYYY-MM-DD] <op> | ...`). Report unparseable lines.
  G. RAW IMMUTABLE  - raw/ files unchanged since creation (git: no edits to raw/).
                      Report any raw/ file modified after its add commit.
```

Adversarial framing (kept honest): the auditor is asked to actively HUNT for the above, not to bless the vault. But its verdict is never over-trusted - a "0 issues" result is not proof of correctness (it only means no STRUCTURAL drift), and a flagged issue is a candidate for human review, not an auto-fix. This mirrors the RC rule "never over-trust a generated report; re-verify against ground truth." The lint op appends `## [YYYY-MM-DD] lint | <n> issues found` to LOG.md.

Cadence: run lint after every batch ingest and on demand. It is cheap enough (checks A-G are grep-able) to run often. A helper script `tools/lint_vault.py` (strong-model authored later) can pre-compute A-G mechanically so the model only interprets the deltas - but that script is OPTIONAL and not part of this spec's must-build.

---

## 8. Minimal Obsidian plugin set

Obsidian is already installed (v1.12.7). The vault is just a folder of markdown, so it works with ZERO plugins. Install only what earns its place:

INSTALL (core set):
- (none required to function). Obsidian's built-in editor, backlinks panel, and graph view already give the human everything needed to read the vault. The 8B does not use Obsidian at all - it reads files via the filesystem MCP.

OPTIONAL (install only if the human hits the specific need):
- Dataview - ONLY if you want live auto-generated index tables from frontmatter (`TABLE ... FROM notes WHERE type = "entity"`). Nice-to-have for the human; the 8B still reads INDEX.md, not Dataview output. Use stable DQL, never DataviewJS.

DO NOT INSTALL (bloat / git-churn / fights the design):
- Templater - the ingester (a model) writes frontmatter directly into the files it creates; Templater only fires inside the Obsidian app on human-created notes, so it adds a second frontmatter path to keep in sync for zero automation benefit here. Skip it.
- Obsidian Git - the driving model already commits via the git CLI. Two committers on one branch = noise/conflicts. One committer of record (the model).
- Excalidraw / Kanban / Canvas-heavy plugins - they write large JSON/embedded-image blobs that bloat diffs.
- Any sync plugin (Obsidian Sync, Remotely Save) - plain git IS the sync. Two sync mechanisms fight.
- Calendar / Periodic Notes - no daily-note workflow here.

WHY near-zero plugins: every plugin is per-device state that can churn git, and the whole point is a clean text vault a model maintains. The value is in the markdown + the index + the schema, not in Obsidian features. Obsidian is the human's read/graph viewer; it is not load-bearing.

`.obsidian/` + `.gitignore` at the vault root (kill the two real noise sources - per-device workspace state and plugin secrets):

```
# Obsidian per-device UI state (churns every session)
.obsidian/workspace.json
.obsidian/workspace-mobile.json
# Local caches / derived state
.obsidian/cache
.obsidian/graph.json
.obsidian/*.log
# Obsidian trash
.trash/
# Plugin secrets - never commit auth tokens
.obsidian/plugins/*/data.json
# OS cruft
.DS_Store
Thumbs.db
```

After a normal Obsidian session `git status` must show ONLY note changes - no `workspace.json`, no `data.json`. If it shows those, the ignore lines are wrong.

Git bring-up: `git init` at `C:\RC_Knowledge\`, add the `.gitignore` above, first commit the seed notes + INDEX.md + LOG.md + CLAUDE.md. Own repo (mirrors Sibling-A), can share the same API keys as RC - that is fine. If pushed to a remote, use a NEW repo (e.g. `Remus3/rc-knowledge`), never the RC repo.

---

## 9. budget-saver + budget-saver-smart integration

The two launch profiles map exactly onto the two-model policy:

| Op | Profile | ANTHROPIC_MODEL | Backing model | Allowed to write vault |
|---|---|---|---|---|
| INGEST | budget-saver-smart | rc-deepseek-pro | DeepSeek v4 pro (cloud reasoning) | YES |
| LINT | budget-saver-smart | rc-deepseek-pro | DeepSeek v4 pro | YES (advisory) |
| QUERY | budget-saver | rc-main | llama3.1:8b local (via LiteLLM :4000) | NO (read + propose only) |

How the enforcement actually lands (no new code required):
- A `budget-saver` session already launches Claude Code pointed at the local 8B. Run the QUERY protocol (section 6) from THAT session. The query prompt forbids create/edit and tells the 8B to hand new-note proposals to a strong session. That is the cheap-read path.
- A `budget-saver-smart` session launches Claude Code pointed at rc-deepseek-pro. Run INGEST and LINT from THAT session. That is the strong-write path.
- Neither script needs modification. The policy is carried by (a) the vault CLAUDE.md manual, and (b) WHICH launcher the operator opens for WHICH op. The vault is a separate root, so opening a budget-saver session and `cd`-ing to `C:\RC_Knowledge\` (or pointing the filesystem MCP there) is all that is needed.

One wiring note the build session MUST handle (flagged by the proxy probe): all three local aliases (rc-main / rc-local / rc-background) point at `ollama_chat/llama3.1:8b` in config.yaml, but Ollama currently only has `llama3-groq-tool-use:8b` pulled. Before the QUERY path works, EITHER `ollama pull llama3.1:8b` OR edit the three config.yaml model lines to the pulled model. This is a budget-saver setup fix, not a vault change, but the vault's query path depends on it - the self-test (section 10) will catch it.

Optional convenience (NOT required): add `C:\RC_Knowledge\` to the filesystem MCP scope in a copy of `lean-mcp.json` so a budget-saver session can reach the vault. The current lean-mcp.json scopes the filesystem server to `C:\Riot Commander` only; a vault session needs the vault path in scope. This is a one-line MCP config addition the build session makes, not a change to the RC lean config.

---

## 10. Self-test the local 8B runs to prove the build worked

This is a scripted acceptance test the build session runs LAST, from a `budget-saver` (8B) session, to prove the vault is real and the cheap-read path works end to end. It uses a tiny seed corpus the build session ingests first (from a strong session). Pass = all 6 checks green.

Seed (ingested by the strong model before the test): 3 source notes, 6 `note` notes, 2 `entity` notes, 1 `moc`, all wired with `[[links]]`, all listed in INDEX.md. (E.g. seed the vault with notes ABOUT this very method: a `source` note for the Karpathy gist, `note` notes for "index-file beats vector RAG at small scale", "one idea per note", "strong model ingests / cheap model reads", an `entity` note for "Obsidian" and "LiteLLM", a `moc` for "llm-wiki-method".)

The 8B self-test (run each step, record PASS/FAIL):

```
SELF-TEST (run from a budget-saver / 8B session):

T1 REACHABLE   - List notes/*.md. Assert count matches INDEX.md entry count.
                 PASS if the 8B can enumerate the vault and the numbers agree.

T2 INDEX READ  - Read INDEX.md only. Answer: "which note explains why this vault
                 uses an index file instead of vector search?"
                 PASS if the 8B names the correct note WITHOUT reading every file.

T3 LINK HOP    - Open that note. Follow its [[links]] one hop. Answer:
                 "what source is that claim drawn from?"
                 PASS if the 8B lands on the correct source note via the link,
                 not by scanning the whole vault.

T4 NO-VECTOR   - Confirm the 8B answered T2/T3 by reading INDEX.md + named notes
                 only (inspect which files it opened). PASS if it did NOT attempt
                 an embedding/vector search and did NOT read all notes.

T5 CITATION    - The T2/T3 answers each cite the note title(s) used.
                 PASS if citations are present and point to real files.

T6 WRITE-GUARD - Ask the 8B to add a fact. Expected behavior: it REFUSES to write
                 and instead emits a proposed note for a strong session to file.
                 PASS if no file was created/edited by the 8B and a proposal was
                 emitted. (This proves the read-only cheap path holds.)

ALL PASS => the vault is built correctly and the cheap-read / strong-write split
holds. Append to LOG.md: `## [YYYY-MM-DD] self-test | 6/6 PASS`.
Any FAIL => fix and re-run before declaring the build done.
```

WHY these 6: T1 proves the vault exists and INDEX.md is complete (the map is trustworthy). T2 proves the 8B can navigate by reading ONE file (the core query design). T3 proves the link graph is traversable (one-hop, not whole-vault). T4 proves the no-vector design holds under a real 8B. T5 proves answers are grounded/cited. T6 proves the model policy (cheap reads, strong writes) is actually enforced at the point it matters. Together they prove the exact properties this minimal design was built to guarantee.

---

## 11. Build order (for the executing budget-saver-smart session)

1. Strong session: `mkdir C:\RC_Knowledge`, `git init`, write `.gitignore` (section 8), `CLAUDE.md` (section 3), empty `INDEX.md` + `LOG.md`, `README.md`.
2. Strong session: ensure the vault path is in the filesystem MCP scope (section 9 optional wiring); pull/point the local model so rc-main resolves (section 9 note).
3. Strong session: INGEST the seed corpus (section 10 seed) - source + note + entity + moc, wired, indexed, logged.
4. Strong session: run LINT (section 7). Fix any A-G issues. Commit the seed vault.
5. 8B session (budget-saver): run the SELF-TEST (section 10). Record 6/6.
6. On 6/6 PASS: commit, append the self-test LOG line, declare the build done. Any FAIL: fix, re-run.

END OF SPEC.
