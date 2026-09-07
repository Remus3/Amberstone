# Public flip - go / no-go

Written 2026-09-07. Subject: making `Remus3/Amberstone` public.

**VERDICT: NO-GO today. Three of five blockers are closed; two are not, and one
of those cannot be closed without a session of its own.**

Repo is `PRIVATE` as of this writing (`gh repo view --json visibility`).
Nothing in this document authorises the flip; it records what is true.

---

## Summary

| # | Blocker | State |
|---|---|---|
| 1 | Secrets in pushed history | **OPEN** - purge proven in staging, not applied |
| 2 | Scraped third-party HTML | **OPEN** - purge proven in staging, not applied |
| 3 | Overlay App E augment data | **OPEN** - purge proven in staging, not applied |
| 4 | Licence contradiction | **CLOSED** (`2ff47493b`) |
| 5 | Third-party name scrub | **OPEN - BLOCKING, needs its own session** |

Blockers 1-3 are one mechanical step away from closed. Blocker 5 is the one
that makes today a no-go regardless of how the others land.

---

## 1. Secrets in pushed history - OPEN, mechanically ready

`config/vision_token.txt` was tracked from the initial commit `92feb15a8`
(2026-04-26) until `dcd965f2d` (2026-09-06). **5111 commits carried it**, and
the blob is reachable from `origin/main` today - deleting the file did not
remove it.

**The token was ROTATED.** The historical blob and the current value differ, so
the exposure is a stale credential rather than a live one. That lowers the
severity; it does not close the blocker, because a public repo would publish a
real historical secret.

**The hand-off's ref count was wrong.** It said five lane branch tips plus the
backup tag. Measured: **12 refs**, and one of them nobody had mentioned -
a stray cross-project scaffold branch, whose *branch name* is itself a
cross-project reference that would be publicly visible.

Sweep for other credentials came back **clean**: no `.env`, `.pem`, `.key`,
private key, `AKIA`, `ghp_`, `xoxb-` ever committed. The `sk-ant-` and `RGAPI-`
hits are all test placeholders; a pickaxe for a full-length key returns zero
commits.

**Adjacent, and a judgement call rather than a defect:** the author email
appears in all 5132 commit author fields and in 4 tracked files. Publishing it
may well be intended - many people publish under a real address - but it should
be a decision, not a discovery. `Users\Administrator` appears 423 times across
tracked content; that is a portability and reuse defect, not PII, since it is
the generic Windows default account name.

## 2. Scraped third-party HTML - OPEN, mechanically ready

`data/meta_build/refresh_2026-05-02/_phase3_html/` holds **109 verbatim scraped
pages** from a third-party build-stats site: 51,079,688 bytes, entering history
2026-05-03 at `d50a37e17`. Confirmed verbatim, not derived - the files open with
that site's own Next.js preload set and mascot asset.

**Nothing live reads them.** The only referent outside `data/` is a one-shot
migration script with a hardcoded 2026-05-03 date that no import, task or
workflow calls.

**But they ship.** `riot-commander.spec:113` gathers `data/meta_build`
recursively into the PyInstaller binary, so every scraped page is inside the
distributed artifact. That makes this the clearest redistribution exposure in
the repo, and it is not repo-only.

**Do not purge `data/meta_build/` wholesale.** The rest of that tree is live:
the DDragon mirrors and `aram/arena_champion_builds.json` are read by 11 modules
including `lcu_client.py`, `rune_wpa.py`, all three coaches and `_sr_prompt.py`.
A wholesale purge would break the application. The correct target is
`refresh_2026-05-02/` only.

The "51 MB" and "66.25 MiB" figures in circulation are both right about
different sets: 51.08 decimal MB is the `.html` subset, 66.25 MiB is the whole
tracked tree.

## 3. Overlay App E augment data - OPEN, mechanically ready

Six byte-identical copies of one 2026-05-18 snapshot at
`data/daemon_slayer/{16.10.1..16.15.1}/mayhem_augment_stats.json`, 73,982 bytes
each, 443,892 total. All six carry the same blob hash and the same
`source_generated_at`.

**The repo already documented in writing that this is not redistributable.**
the Share package's own LICENSE (lines 79-87, deleted with the package in
`d76004025`; read it at `d76004025^`) excluded it on exactly those grounds,
and `tools/ds_share_sync.py` enforced the exclusion. Shipping it in a public
main repo contradicts a position this project had already taken.

It has a live reader, reached by f-string rather than by literal filename:
`core/augment_external_source.py:199`, on the Arena augment-select path. Removing
the data degrades the augment recommender's priors - that is a behaviour change
to plan for, not a free deletion.

## 4. Licence contradiction - CLOSED

Three incompatible statements existed at once: an Apache-2.0 `LICENSE` added
2026-09-06, `README.md:228` "All rights reserved. Personal use only.", and
`Share/LICENSE.md`'s no-redistribution clause.

Resolved 2026-09-07 per operator ruling in `2ff47493b`: Apache-2.0 scoped to
code and authored docs, an explicit data carve-out appended after the licence
text, a new `NOTICE` recording each upstream source, and the README line
replaced with a pointer. `Share/LICENSE.md` ceased to exist with the Share
removal in `d76004025`, which removed the third statement rather than
reconciling it.

The Apache text is kept byte-pure with the scope block AFTER it, deliberately: a
leading preamble can defeat licence detection, which matters for a public repo.

## 5. Third-party name scrub - OPEN, BLOCKING

**This is why the answer is no-go, and `docs/PRE_RELEASE_NAME_SCRUB.md`
understates it on both halves.**

The plan claims the competitor tool's name is "ALREADY scrubbed from CURRENT
tracked file content". Measured: **129 files, 34,757 occurrences.** Not scrubbed
at all. Three findings make this more than a counting error:

- The name is in a tracked FILENAME (`scripts/parse_external_arena.py`).
- It is in `data/meta_build/arena_champion_builds.json` 262 times as `_sources`
  provenance URLs, and that file is **live-read by four modules**. Deleting the
  scraped HTML does not touch it.
- It is in `data/meta/tft_set16_meta.json` **in the initial commit's tree**, so
  every one of the 5132 commits carries it. A message-only rewrite misses all of
  them.

The plan says the name survives in "5 historical commit messages". Measured:
**9**, all reachable from `origin/main`.

Other in-scope names remain in the tree in quantity - a further ~20 competitor
and tool names, plus references to five sibling projects. The scrub plan's
Scope-OUT list (Data Dragon, CommunityDragon, Meraki, the LoL wiki, Riot API)
correctly stays.

**This cannot be folded into a path purge.** It is a content rewrite across
5132 commit trees that edits a live data file, and doing it badly is
irreversible. Operator ruling 2026-09-07: path purge this session, name scrub
next session.

---

## What was actually done

- Licence reconciled to one story; `NOTICE` created (`2ff47493b`).
- `Share/` removed entirely - 548 files, 684 changed, 633497 deletions
  (`d76004025`). Both suites green afterwards, verified fresh on main:
  `pytest tests` **20975 passed / 96 skipped / 0 failed**;
  `pytest agents/daemon_slayer` **10856 passed / 0 failed**.
- `tools/rewrite_sha_citations.py` built and tested (`bede3f927`), because a
  history rewrite renames every commit and this repo cites **7096 SHAs** across
  tracked markdown.
- **The path purge is PROVEN, NOT APPLIED.** Run in an isolated mirror clone at
  `C:/rc-purge-staging/`, dropping `config/vision_token.txt`,
  `data/meta_build/refresh_2026-05-02/`, `Share/`, and the six Overlay App E snapshots.
  Verified: all four targets at 0 commits, all live data intact
  (`arena_champion_builds.json`, `aram_champion_builds.json`, 36 DDragon files
  still present at `main`). Citation remap against the real commit-map:
  **1856 remapped, 25 dropped, 0 ambiguous**.
- Full verified backup bundle at
  `C:/ClaudeBackup_20260906/rc-pre-purge-20260907-012420.bundle`
  (85.9 MB, `git bundle verify` reports a complete history).

**It was deliberately not applied to the live repo.** Seven worktrees are
checked out against it, and `filter-repo` rewrites every ref, which orphans all
of them. Applying it is a short, clean, gated step - it should not happen
incidentally in the middle of other work.

Honest note on size: the pack drops 79.43 -> 76.31 MiB, only ~3 MB. The 51 MB
and 20 MB figures are working-tree sizes; near-duplicate content deltas away to
almost nothing in a packfile. The purge is worth doing for RIGHTS reasons, not
for size.

## Conditions for a GO

1. Name scrub executed and verified to zero across tracked content AND blob
   history, including the tracked filename and the live-read provenance rows.
2. Path purge applied to the live repo, force-pushed, lane branches re-cut, and
   the 25 dropped citations accepted in writing.
3. a stray cross-project scaffold branch deleted - its name alone is a
   cross-project leak.
4. A decision, not a discovery, on publishing the author email in 5132 commits.
5. A decision on whether the Arena augment recommender ships with degraded
   priors or with a replacement source.

Items 1 and 2 are one rewrite if done together, which is the recommendation:
one force-push, one citation remap, one branch re-cut.
