# Pre-release name-scrub - standing prerequisite

Operator-authorized standing task. Kept generic on purpose (categories, not an
enumerated name list) so this plan does not itself become a leak.

## Trigger
Execute BEFORE the project is released publicly or open-sourced. Timing is not
fixed - it is gated on that release/open-source decision (TBD). This is a
pre-requisite hygiene pass, not an in-flight item.

## Goal
Frame the repo by technical substance only - remove third-party / outreach /
private references from both file content AND commit-message history, while
keeping the legitimate public data-source citations the data pipeline depends on.

## Scope IN (scrub -> generic technical descriptors; keep the technical substance + the RC integration)
- The referenced competitor build-stats tool - its name is ALREADY scrubbed from
  CURRENT tracked file content (one commit this session). Its name still remains
  in 5 of this session's historical commit MESSAGES (immutable without a rewrite).
- All OTHER third-party competitor / tool / product names (the research-triage
  catalogs, comparison references, etc.).
- Outreach / peer / private-project references and personal context (peer handles,
  private side-projects, cross-project leaks, personal names).

## Scope OUT (KEEP - these are public accessible data sources the pipeline sources from + credits)
- Riot Data Dragon (DDragon)
- CommunityDragon (CDragon)
- Meraki Analytics
- LoL wiki (the Riot-aliased MediaWiki the DS sidecar extractor reads)
- Riot API / Match-V5

## Method (two halves)
1. FILE CONTENT: replace each in-scope name with a generic descriptor (e.g. "the
   competitor", "a peer project"). Preserve every technical claim, formula, and RC
   integration point - only the name goes. ASCII only. Run the hygiene tests +
   `git grep -i <name>` = 0 in tracked content. Commit normally.
2. COMMIT-MESSAGE HISTORY: full-repo history rewrite (git filter-repo or an
   interactive rebase) to scrub the in-scope names from EVERY historical commit
   message, then `git push --force`. The operator has PRE-AUTHORIZED this force-push
   for the pre-release execution (this overrides the standing no-force-push rule
   for this one deliberate pass only - re-confirm at execution time).

## Verification at execution
- `git grep -il <each in-scope name>` over tracked content -> empty.
- `git log --all --format=%B | grep -i <each in-scope name>` -> empty.
- Hygiene suite green (smart-quote / mojibake / u2500); ruff clean; ASCII clean.
- CI green after the (force-pushed) push.

## Status
- 2026-06-02: the competitor tool's name scrubbed from current file content
  (committed this session). Everything else above is DEFERRED to the pre-release
  trigger. Do NOT execute the broad scrub or the history rewrite before that
  trigger.
