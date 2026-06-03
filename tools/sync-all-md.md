---
description: Reconcile every Markdown doc in the repo against a single source of canonical facts, fix cross-doc drift, refresh the README in its locked s207 style, flag broken cross-references and orphaned/stale/deprecated .md files. Use when docs have drifted (test counts, ENGINE_VERSION, patch, coverage) or after a run of sessions, before a doc audit, or when the operator asks to "sync all md".
---

The operator wants every `.md` in the repo to tell the **same story with the same numbers**. Docs drift: README says one test count, DAEMON_SLAYER.md another, WAKEUP a third. This skill establishes canonical facts ONCE from authoritative sources, propagates them everywhere, refreshes the README in its locked style, and surfaces broken/orphaned docs - without rewriting history.

This is a **documentation-only** skill. It makes NO code changes, does NOT restart RC, does NOT touch `data/`.

**Args:**
- _(none)_ → full reconcile, apply surgical edits, print report. **No commit.**
- `--dry-run` (or `preview`) → report only, zero writes. Use first if unsure.
- `commit` → after edits, stage ONLY the doc files touched + one Conventional Commit. Never `git add -A`.
- `readme` → fast path: §1 + §4 + §6 + §10 only (just reconcile + rewrite the README).

Run sections in order. Surgical edits only - never full rewrites of anything except the README body (which has an explicit style contract in §4).

---

### 1. Establish canonical facts (the whole point - do this first)

Read these authoritative sources and write the values down. Every doc must match THESE, not each other:

| Fact | Canonical source (read at runtime - never trust a doc) |
|---|---|
| League / DDragon patch | `data/daemon_slayer/current.txt` (single line, e.g. `16.10.1`) |
| `ENGINE_VERSION` | the `ENGINE_VERSION = "x.y.z"` assignment in `agents/daemon_slayer/__init__.py`; cross-check `curl -k https://127.0.0.1:8893/health` (`engine_version` field) if DS is up |
| DS test count | `py -m pytest agents/daemon_slayer/ -q --co 2>$null` → count collected; **collect, don't trust the doc** |
| Wider RC test count | `py -m pytest tests/ -q --co 2>$null` → count collected |
| Purchasable item count | DS `/health` `item_count`, else the `effects.py` registry length (historically 547) |
| Champion override coverage | recompute from the four registries `agents/daemon_slayer/champion_{max_priority,combo_sequences,form_index,block_index}.json` - count distinct champions and total (champion,key) entries; **drop the `_meta` key before counting** |
| Match-history rows | `rewind_history.db` row count (sqlite) - memory historically cites ~2,8xx |
| Latest session + commits | `git -C "C:/Riot Commander" log --oneline -15` + the top block of `WAKEUP_NOTES.md` + the highest-numbered item in `docs/LEDGER.md` |

Produce a **Canonical Facts table** in your working notes. This is the contract for §3-§5. If DS `:8893` is down, derive `ENGINE_VERSION`/items from source files and note "DS offline - values from source, not /health" in the report.

### 2. Inventory the .md ecosystem

`Glob **/*.md`. Classify every hit into one bucket (exclude `python-embed/`, `node_modules/`, `.pytest_cache/`, site-packages - third-party):

- **LIVING - sync targets (surgical edits OK):** `README.md`, `CLAUDE.md` (only the one-line DS reference + the `### Settled` summary (the "Active priorities" block is a static pointer - do NOT add items) in "Living docs"/topology header), `ROADMAP.md`, `BACKLOG.md`, `docs/ARCHITECTURE.md`, `docs/DAEMON_SLAYER.md`, `docs/OPERATIONS.md`, `docs/BRIDGE.md`, `docs/API.md`, `docs/AGENTS.md`.
- **APPEND-ONLY - never rewrite, never reflow:** `WAKEUP_NOTES.md` (append + prune via `scripts/wakeup_prune.py` only), `docs/history_notes.md`, everything under `docs/_archive/**`, `docs/adr/**` (ADRs are immutable - add a new ADR, never edit an old one), any dated artifact (`AUDIT_*`, `PHASE_*`, `ARCH-*`, `*_2026-*`), `agents/**/charter.md`, `agents/**/reports/**`, `docs io RC peer/**` (dated cross-Claude artifacts). Per memory `feedback_no_history_rewrite` + `reference_archive_dir`: **only sync the living docs; never rewrite a ledger.**
- **FROZEN - do not edit (CLAUDE.md hard rule):** `tools/process-bridge-tasks.md`, `tools/diagnose.md`, `tools/caveman.md`, `tools/bridge_watcher_action_prompt.md`, plus anything else on the CLAUDE.md frozen list. Read-only here.
- **INDEX:** `MEMORY.md` (index of memory files - one line per entry, ≤150 chars, never write memory bodies into it) and the memory `*.md` under `C:/Users/Administrator/.claude/projects/C--Riot-Commander/memory/`.
- **SKILL/COMMAND specs:** `.claude/commands/*.md`, `tools/*.md` (the done/diagnose/caveman family), `.claude/skills/*/SKILL.md` - including **this skill's own two files** (see §9 self-congruence).
- **CANDIDATE - unclassified:** anything else → §7 disposition.

### 3. Reconcile cross-cutting facts across LIVING docs

For every fact in the §1 table, grep all LIVING docs for stale instances and replace with the canonical value. The usual offenders:

- **Test counts** - README ("N tests"), `docs/DAEMON_SLAYER.md` (status line **and** the `tests/` module-map row - they drift independently), CLAUDE.md DS reference line.
- **`ENGINE_VERSION`** - DAEMON_SLAYER.md status line, CLAUDE.md DS reference line. (WAKEUP carries it too but is append-only - leave it.)
- **Patch** - DAEMON_SLAYER.md, README ("current League patch" stays prose; don't hard-pin a number in the README unless it already names one).
- **Champion coverage** - DAEMON_SLAYER.md ("N entries / N champions" + the prose %), README ("about two-thirds of the roster" - keep it as a rounded prose phrase, only correct it if the fraction crossed a boundary).
- **Item count / match-history count** - wherever cited.

Rule: pick the phrasing already in the doc and swap only the number/version. Do not restructure sentences. If a doc rounds ("~3,000 matches", "about two-thirds") keep the rounding unless it's now wrong.

### 4. README pass - locked s207 style

The README was deliberately rewritten in s207 to a plain-English summary. **Style contract - enforce, do not "improve":**

- Audience: a smart reader who is NOT this codebase's engineer. Prose paragraphs, not bullet dumps.
- Keep the 8-section skeleton: title+tagline → What it does → How it works → Daemon Slayer build engine → Where it runs → Project status → More → License. Don't add sections.
- **No session changelog, no `sNNN` ids, no commit SHAs, no enumerated "then we added X" history.** README describes the *current* system, not how it got here.
- Exactly **one** table allowed (the 6-row DS scoring-mode table). Don't add tables.
- No deep cross-machine/topology specifics, no install steps, no RC-Tutor strategy - those live in CLAUDE.md / docs.
- Only the hard numbers update (items / tests / patch / coverage), pulled from §1. Prose stays prose.
- "More" links must all resolve (§6 verifies).

If the README's structural claims (modes covered, what the engine does, two-machine split) still match reality, only the numbers change. If something structural genuinely changed (a mode retired, a new top-level capability), update the one relevant sentence - minimally.

### 5. Per-doc congruence pass (LIVING only)

- **CLAUDE.md** - touch ONLY: (a) the one DS reference line if `ENGINE_VERSION`/items/patch moved; (b) the `### Settled` summary if a decision changed. The "Active priorities" block is now a STATIC POINTER - per-item completion entries go to `docs/LEDGER.md` (newest-first), NEVER into CLAUDE.md (CI size-budgeted < 60KB). Leave Topology / Paths / Hard rules / everything else alone.
- **ROADMAP.md** - Now+Next ledger. Mark shipped items `✅` + SHA; ensure the top reflects the latest session from §1. Do not delete completed items (history lives elsewhere); do not rewrite older entries.
- **BACKLOG.md** - strike (`~~...~~`) anything that shipped this period with the SHA; don't reorder.
- **docs/ARCHITECTURE.md / OPERATIONS.md / BRIDGE.md / API.md / AGENTS.md** - **structural sync only.** Verify module map / endpoints / ports / task names against the actual code & CLAUDE.md. Update a line only if code changed it. These are not changelogs - don't add session notes.
- **docs/DAEMON_SLAYER.md** - the highest-drift doc. Reconcile the status line (`ENGINE_VERSION · N tests · items · patch`), the `tests/` module-map row, the "Phase 3 ... implemented today" sentence (all 6 scorers are wired now - verify against CLAUDE.md/code, fix if it still says "three"), and the coverage numbers.
- **MEMORY.md** - verify every linked memory file exists and each line is ≤150 chars; if a LIVING doc fact contradicts a memory, the memory is stale → note it in the report (do NOT auto-edit memory bodies here; that's `/consolidate-memory`'s job - just flag).
- **Lessons** - there is no `LESSONS.md`. The lesson surface is `docs io RC peer/RC_PHASE1_LESSON_SCHEMA_2026-05-02.md` (dated, append-only - do NOT rewrite) + the `/process-incoming-lessons` flow + memory `feedback_*` entries. Only check: does the lesson-schema's frontmatter field list still match `core/bridge_envelope.py` and the CLAUDE.md "Memory frontmatter" section? If they diverged, report it - don't edit the dated artifact.

### 6. Cross-reference integrity

For every LIVING doc, extract every relative link `](path)` and every backticked file path, and verify the target exists.

- **Referenced-but-missing** → report each (path, the doc(s) citing it). **Resolved historical case - do NOT re-flag or repoint:** `docs/_archive/CHANGELOG.md` never existed; its real cross-references were repointed to `docs/history_notes.md` in s222 (the live `Completed work:` pointer in `CLAUDE.md` is already correct). Every remaining match is a *narrative mention inside a session-ledger entry* (CLAUDE.md / ROADMAP.md Active-priorities prose - some literally describing the s222 fix). Those are history: rewriting them is a `feedback_no_history_rewrite` violation for zero benefit and does not stop the re-flag. Treat the CHANGELOG string as closed; only report a genuinely-new missing ref. For other missing refs: **do not silently rewrite** - surface the decision with options; only apply if the operator has a standing preference in memory/CLAUDE.md.
- **Orphaned** → a LIVING-looking doc that nothing links to and that isn't in the §2 living set → §7.
- Broken anchors / renamed files → list them.

### 7. Other .md - update / deprecate / complete

For each CANDIDATE (and any orphan from §6), decide and report a disposition (apply only the safe ones; surface the rest):

- **Stale but live** → reconcile facts (§3) if it's effectively a living doc that escaped the §2 list; recommend adding it to this skill's §2 list.
- **Superseded / dead** → recommend moving to `docs/_archive/YYYY-MM-DD-<reason>/` (the quarantine pattern from memory `reference_archive_dir` - **move, never delete; reversible**). Do not move without operator confirmation unless it's already obviously dated and unreferenced.
- **Incomplete** (TODO/TBD/`<placeholder>`/empty sections) → list the file + the gap; don't fabricate content to fill it.
- **Duplicate** (two docs claiming to be the source of truth for the same thing) → name both, recommend which is canonical.

Never delete a `.md`. Quarantine is the only removal.

### 8. Append-only / history protection (hard invariant)

Before any write, re-confirm the target is in the LIVING set. If a fact is wrong in `WAKEUP_NOTES.md`, `docs/history_notes.md`, `docs/_archive/**`, an ADR, or any dated artifact: **do not fix it there.** History records what was true *then*. Note the discrepancy in the report and fix only the LIVING doc. The only sanctioned WAKEUP mutation is `py "C:/Riot Commander/scripts/wakeup_prune.py" --keep 3` (idempotent; run only if WAKEUP has >3 sessions and the operator asked for a prune - otherwise just report the count).

### 9. Self-congruence

This skill ships as two files that MUST stay byte-identical (house pattern, like `done.md`):
- `tools/sync-all-md.md` - the **tracked canonical** (committed; survives `/clear`)
- `.claude/commands/sync-all-md.md` - the operative slash command, **gitignored local runtime** (regenerated per machine)

Diff them. If they differ, the **tracked canonical `tools/` copy wins** - re-mirror it onto `.claude/commands/`. Never re-mirror the other direction: the gitignored runtime copy can predate a repo-wide pass (e.g. the s244 em-dash purge) and pushing it onto `tools/` would re-introduce rule-violating content into a tracked file. Before reporting "identical", also confirm BOTH copies satisfy the no-em-dash / no-smart-quote hard rule - that (not structural drift) was the only legitimate divergence this skill itself ever caused. Report the action + direction. (A doc-sync skill that lets its own two copies drift, or that re-injects banned glyphs into the repo, is self-refuting.)

### 10. Final report banner

Print exactly this shape:

```
══════════════════════════════════════════════════════════════════
  /sync-all-md - md congruence pass
══════════════════════════════════════════════════════════════════
  canonical facts   : patch=<p> engine=<v> ds_tests=<n> rc_tests=<n>
                      items=<n> champ_cov=<entries>/<champs> matches=<n>
  living docs edited : <list of files + one-line what-changed each>
  facts reconciled   : <N stale numbers/versions fixed across M docs>
  readme             : <numbers-only | +1 structural line | unchanged>
  broken refs        : <N>  (genuinely-missing only; CHANGELOG = closed, see 6)
  orphans / stale    : <N flagged>  deprecation moves proposed: <N>
  history protected  : <N stale-in-ledger noted, not edited>
  self-congruence    : <identical | re-mirrored tools/ copy>
  commit             : <none | docs: sync living docs - <topic> (SHA)>
══════════════════════════════════════════════════════════════════
  Decisions needing operator: <broken-ref resolutions, deprecation moves, ...>
══════════════════════════════════════════════════════════════════
```

List anything needing a human call (broken-ref resolution, deprecation moves, history discrepancies) under the bottom rule. If `--dry-run`, every "edited"/"commit" line says `(preview)` and nothing was written.

### Safety rails

- Documentation only. NO code edits, NO `data/` writes, NO RC restart, NO DS restart.
- Never rewrite history (WAKEUP / history_notes / _archive / ADRs / dated artifacts) - §8 is non-negotiable.
- Never touch a CLAUDE.md frozen file. Never edit a memory body (only flag stale; defer to `/consolidate-memory`).
- README: enforce the s207 style contract; resist the urge to "polish" beyond fact reconciliation.
- `commit` arg: stage only the explicit doc files you edited (list them by path), never `git add -A`/`.`. Conventional Commit subject (`docs: sync living docs - <topic>`) with the standard `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer. Never `--amend`, never force-push, never `--no-verify`.
- Broken-ref and deprecation decisions are surfaced, not silently applied, unless the operator has a standing preference recorded in memory/CLAUDE.md.
- Preserve file encodings and line endings. Surgical edits - minimal diff.
