# Pre-release name-scrub - EXECUTED 2026-09-07

Kept generic on purpose (categories, not an enumerated name list) so this plan
does not itself become the leak it exists to remove.

## Status

**EXECUTED 2026-09-07, ahead of the public flip.** Both halves ran: current file
content, and the full commit history (blob content AND commit messages) in one
`git filter-repo` pass alongside the path purge.

**The pre-execution status line here was wrong on both halves and is corrected
below, because the error is the reusable part.** It claimed the competitor
build-stats tool's name was "ALREADY scrubbed from CURRENT tracked file content"
and survived only in "5 historical commit messages". Measured on the morning of
execution: **129 files and 34757 occurrences of that one name in tracked
content**, and **15 commit messages**, not 5. A status line written from
recollection of a single commit had been carried forward for three months.

Three findings turned that from a counting error into a design constraint:

- the name was in a tracked FILENAME, so a content-only sweep could not reach it;
- it was in a live-read data file as provenance URLs, so deleting the file was
  not an option and the rows had to be handled deliberately;
- it was in a data file present in the INITIAL COMMIT's tree, so every commit
  carried it and a message-only rewrite would have missed all of them.

## Goal

Frame the repo by technical substance only - remove third-party, outreach and
private references from both file content AND commit-message history, while
keeping the legitimate public data-source citations the pipeline depends on.

## Scope IN (scrubbed to generic technical descriptors)

- Competitor and comparison product names: build-stats aggregators, overlay
  apps and platforms, draft tools, TFT aggregators, guide and review sites.
  Each got its OWN stable descriptor (`Aggregator A`, `Overlay App E`, ...) so
  that lines COMPARING several of them stay readable and the comparison
  survives the rename.
- Private sibling projects, their local paths and their GitHub repo paths, now
  codenamed `Sibling-A` .. `Sibling-E`.
- A peer machine and the decommissioned cross-project bridge (ADR-012).
- Personal and outreach references: the operator's own game handles, a third
  party's handle, peer handles, personal email addresses, and two
  link-shareable secret gist ids.

## Scope OUT (kept - these are public data sources the pipeline reads, or real
dependencies)

- Riot Data Dragon (DDragon), CommunityDragon, Meraki Analytics, the
  Riot-aliased LoL wiki, Riot API / Match-V5, lolmath, 101.qq.
- Tooling the project actually integrates with rather than competes against:
  the client plugin loader RC built a panel for, the local recall store, and
  the ordinary language and CI toolchain.

## Operator ruling on cross-project references (2026-09-07)

**Cross-project references are FINE in this regard.** They were scrubbed anyway,
but the reason is PORTABILITY, not disclosure: a hardcoded sibling checkout path
is wrong on every machine but the one that wrote it, and extracting the list to
per-host config is worth doing on its own merits. Nothing that is merely a
cross-project reference should be filed as a leak, and the one shared file that
still names two siblings is left alone under the same ruling - a wording change
there is an OFFER to the carrier repos, not a fix RC needs. Operator: "if the
others can come to a consensus then that is fine."

## Deliberate NON-scrubs, each a decision rather than an oversight

- **The two- and three-letter sibling initialisms** (`LW`, `RM`, `RSC`, `LL`,
  `CS`). They are opaque to an outsider, several collide with real domain terms
  (`LW` is also the item Last Whisper, `RM-<n>` is this repo's own roadmap id,
  `CS` is champ-select and creep-score), and `core/ports.py` uses them as
  registry KEYS that sibling repos read. Renaming them is a coordinated
  cross-repo API change bought for no disclosure.
- **`C:\ProgramData\lw-loop\slots`.** The prefix is a sibling name, but the path
  is a live three-way coordination contract inside a byte-pinned file. Changing
  it unilaterally un-serialises the loops AND breaks the byte pin.
- **The machine name `legion-rc`.** It is this box's Tailscale node name, it is
  in the certificate SANs, and it is not a third-party reference.
- **The copyright holder in `LICENSE` and `NOTICE`.** Removing it produces the
  exact defect the third-party-lift rule warns about: a grant with no grantor.
- **The GitHub username.** The repo lives under it; it is public by definition.

## Method (both halves)

1. FILE CONTENT: ordered literal replacement tables, longest and most specific
   first, applied to tracked text files. Deliberately literal rather than
   regex - a regex that misfires across 4800 files is not reviewable, and the
   point of the pass is that its diff can be read. Two names needed more than a
   table row, and both for the same reason - the token is overloaded. One
   overlay product shares its name with a Riot game mode AND with the common
   shorthand for a champion, and the mode spelling LINE-WRAPS inside comments,
   so the exclusion could not be a fixed-width lookbehind. Another product's
   name is a substring of a real League item, so 31 of its 55 raw hits were the
   item. Both got their own reviewed pass with the exclusions written out.
2. HISTORY: one `git filter-repo` run applying the SAME expression list to blob
   content and to commit messages, together with the path purge, so a name
   scrubbed at HEAD cannot survive in a 5000-commit-old tree.

## Verification at execution

- `git grep -il <each in-scope name>` over tracked content -> empty.
- `git log --all --format=%B | grep -i <name>` -> empty.
- `git rev-list --all --objects` blob scan -> empty for each name.
- Both suites green from the repo root; ruff clean; ASCII hygiene green.

The measured results are recorded in `docs/PUBLIC_FLIP_GO_NO_GO.md`.
