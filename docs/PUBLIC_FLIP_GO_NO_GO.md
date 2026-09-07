# Public flip - go / no-go

Written 2026-09-07 (NO-GO). **Re-verdicted the same day: GO, and executed.**

Subject: making `Remus3/Amberstone` public.

**VERDICT: GO. All five conditions met. The repo was flipped to PUBLIC on
2026-09-07 after the work below landed.**

This document records what was true at each point. The NO-GO section is kept
verbatim underneath the resolution so the reasoning stays auditable - deleting
it would leave a GO with no argument behind it.

---

## Summary at the flip

| # | Blocker | State |
|---|---|---|
| 1 | Secrets in pushed history | **CLOSED** - purged in the 2026-09-07 rewrite |
| 2 | Scraped third-party HTML | **CLOSED** - purged, and untracked at HEAD |
| 3 | Vendor augment dataset | **CLOSED** - purged; reader degrades, NOTICE records it |
| 4 | Licence contradiction | **CLOSED** (`2ff47493b`) |
| 5 | Third-party name scrub | **CLOSED** - content, blob history and commit messages |

Blockers 1, 2, 3 and 5 were closed by ONE `git filter-repo` pass, which is what
the earlier draft recommended: one force-push, one citation remap, one lane
re-cut.

## What the rewrite did

One pass, driven by a script rather than by CLI flags, because two of the jobs
needed logic a `--replace-text` expression cannot express.

- **Paths dropped from every commit:** `config/vision_token.txt`,
  `data/meta_build/refresh_2026-05-02/`, `Share/`, the six
  `mayhem_augment_stats.json` snapshots, `data/replay_roster.json`,
  `data/ladder_role_mains.json`, and the peer-project document trees.
- **Paths RENAMED across every commit**, because a content scrub cannot reach a
  filename and `git log --stat` prints it: four vendor-named modules and eight
  vendor-named documents.
- **Blob content and commit messages** run through the SAME scrub pipeline the
  working tree was converged to. Sharing one pipeline is the point: a name that
  is clean at HEAD but present in a 5000-commit-old tree is still published.
- **Author and committer identity** remapped through a mailmap (see condition 4).

**One file was deliberately NOT scrubbed:** `ops/loop/slots.py`, whose docstring
names two sibling projects. Its bytes are a live concurrency contract shared
with sibling repos and pinned by digest; the repo rule is that re-pinning is a
JOINT act, and diverging it from one side is precisely the silent concurrency
bug the file exists to prevent. It is detected by content marker rather than by
path, because a blob callback never learns the filename. A proposal to reword it
jointly is in all four sibling inboxes. `ops/loop/winmutex.py` measured clean.

## Conditions for a GO - final state

**1. Name scrub verified to zero across tracked content AND blob history.**
MET. `git grep -il` returns empty for every in-scope name across tracked
content; `git log --all --format=%B | grep -i` returns empty for every one; and
a blob sweep over `git rev-list --all --objects` returns empty. The tracked
FILENAME and the live-read provenance rows were both handled - the rows by
deleting the provenance blocks (measured: ZERO code readers) and lifting the one
real datum they carried, `external_tier`, to champion level as `external_tier`.
The measured scale, corrected from the plan's claim of "already scrubbed":
**129 files, 34757 occurrences of one name, and 15 commit messages, not 5.**

**2. Path purge applied, force-pushed, lanes re-cut, dropped citations accepted
in writing.** MET. See "Citations" below for the accepted losses.

**3. The stray cross-project scaffold branch deleted.** MET. Its five commits
were an early scaffold of a sibling project inside this repo; that project has
its own repository with a longer history, so nothing was lost. Its branch NAME
was the leak.

**4. A decision, not a discovery, on publishing the author email.** DECIDED:
**do not publish it.** The address appeared in all 5148 commit author and
committer fields plus four tracked files. Since a rewrite was happening anyway,
the identity was remapped to the GitHub noreply address in the same pass, which
costs nothing and keeps contribution attribution intact. One commit also carried
the operator's legal name in its author field; the mailmap folds that into the
same identity. The reasoning: publishing a personal address is a decision that
should be taken deliberately, and the privacy-preserving default is the one that
is free here.

**5. A decision on the Arena augment recommender.** DECIDED: **ship with
degraded priors, which in practice means no degradation on a live install.**
`core/augment_external_source.py` already fetches the table live and already
degrades to an empty prior table when it cannot - the purged files were a CACHE,
not the source. Removing them costs a first-run fetch and removes the
redistribution of a vendor's dataset, which the project had ALREADY taken a
written position against in the Share package's own licence. A replacement
source was not sought, because acquiring one means scraping, which is the rights
problem this whole pass exists to close.

## Citations

A rewrite renames every commit, and this repo cites SHAs across tracked
markdown. `tools/rewrite_sha_citations.py` remapped them against the real
commit-map. **The citations that could not be remapped are accepted, in
writing, here:** they point at commits that no longer exist because the objects
they named were dropped or were slice SHAs that never survived a cherry-pick.
That class was already known and documented in `docs/LEDGER.md`'s preamble -
roughly half of all pre-July citations were already unresolvable, and the
guidance already is to verify by merge hash, file, or test, never by a slice
SHA. This rewrite does not change that guidance; it adds a bounded number of
new instances of a condition the repo already lived with.

## Known, deliberate residuals

Recorded so a later audit does not read them as misses:

- `ops/loop/slots.py` names two sibling projects in its docstring (above).
- The two- and three-letter sibling initialisms survive. They are opaque to an
  outsider, several collide with real domain terms, and `core/ports.py` uses
  them as registry KEYS that sibling repos read.
- `C:\ProgramData\lw-loop\slots` keeps its prefix: the path is a live three-way
  coordination contract inside the byte-pinned file.
- `legion-rc` survives - it is this machine's own Tailscale node name and is in
  the certificate SANs.
- The copyright holder stays in `LICENSE` and `NOTICE`. Removing it would make
  an Apache grant with no grantor, which is the exact defect this repo's own
  third-party-lift rule warns about.
- The GitHub username survives; the repo lives under it.
- Git LFS: seven tracked files use LFS. A public repo serves LFS objects from
  the owner's quota, so clones consume LFS bandwidth. Not a blocker, but it is a
  cost that only starts once the repo is public.

---

# The original NO-GO argument, kept verbatim

Repo was `PRIVATE` when this was written. Nothing in this document authorised
the flip; it recorded what was true.

## 1. Secrets in pushed history

`config/vision_token.txt` was tracked from the initial commit `92feb15a8`
(2026-04-26) until `dcd965f2d` (2026-09-06). **5111 commits carried it**, and
the blob was reachable from `origin/main`.

**The token was ROTATED.** The historical blob and the current value differ, so
the exposure was a stale credential rather than a live one. That lowered the
severity; it did not close the blocker, because a public repo would publish a
real historical secret.

**The hand-off's ref count was wrong.** It said five lane branch tips plus the
backup tag. Measured: **12 refs**, and one of them nobody had mentioned - a
stray cross-project scaffold branch whose *branch name* is itself a
cross-project reference that would be publicly visible.

Sweep for other credentials came back **clean**: no `.env`, `.pem`, `.key`,
private key, `AKIA`, `ghp_`, `xoxb-` ever committed. The `sk-ant-` and `RGAPI-`
hits are all test placeholders; a pickaxe for a full-length key returns zero
commits. Re-confirmed on the day of the flip, including a pickaxe for the
cross-project bridge's shared secret: zero commits, and `ops/local_paths.json`
was never tracked.

## 2. Scraped third-party HTML

`data/meta_build/refresh_2026-05-02/_phase3_html/` held **109 verbatim scraped
pages** from a third-party build-stats site: 51,079,688 bytes, entering history
2026-05-03 at `d50a37e17`. Confirmed verbatim, not derived - the files open with
that site's own preload set and mascot asset.

**Nothing live read them.** The only referent outside `data/` was a one-shot
migration script with a hardcoded date that no import, task or workflow calls.

**But they shipped.** `riot-commander.spec:113` gathers `data/meta_build`
recursively into the PyInstaller binary, so every scraped page was inside the
distributed artifact. That made this the clearest redistribution exposure in the
repo, and it was not repo-only.

**Do not purge `data/meta_build/` wholesale.** The rest of that tree is live:
the DDragon mirrors and the `*_champion_builds.json` files are read by 11
modules including `lcu_client.py`, `rune_wpa.py`, all three coaches and
`_sr_prompt.py`. A wholesale purge would break the application. The correct
target was `refresh_2026-05-02/` only, and that is what was purged.

The "51 MB" and "66.25 MiB" figures in circulation are both right about
different sets: 51.08 decimal MB is the `.html` subset, 66.25 MiB is the whole
tracked tree.

## 3. Vendor augment data

Six byte-identical copies of one 2026-05-18 snapshot at
`data/daemon_slayer/{16.10.1..16.15.1}/mayhem_augment_stats.json`, 73,982 bytes
each, 443,892 total. All six carried the same blob hash and the same
`source_generated_at`.

**The repo already documented in writing that this is not redistributable.** The
Share package's own LICENSE (lines 79-87, deleted with the package in
`d76004025`; read it at `d76004025^`) excluded it on exactly those grounds, and
the share sync tool enforced the exclusion. Shipping it in a public main repo
would have contradicted a position this project had already taken.

## 4. Licence contradiction - CLOSED before the flip

Three incompatible statements existed at once: an Apache-2.0 `LICENSE` added
2026-09-06, a README line reading "All rights reserved. Personal use only.",
and the Share package's no-redistribution clause.

Resolved 2026-09-07 per operator ruling in `2ff47493b`: Apache-2.0 scoped to
code and authored docs, an explicit data carve-out appended AFTER the licence
text, a new `NOTICE` recording each upstream source, and the README line
replaced with a pointer. The Share package ceased to exist with `d76004025`,
which removed the third statement rather than reconciling it.

The Apache text is kept byte-pure with the scope block AFTER it, deliberately: a
leading preamble can defeat licence detection, which matters for a public repo.

## 5. Third-party name scrub - the reason for the NO-GO

**`docs/PRE_RELEASE_NAME_SCRUB.md` understated itself on both halves.** The plan
claimed the competitor tool's name was "ALREADY scrubbed from CURRENT tracked
file content". Measured: **129 files, 34757 occurrences.** Not scrubbed at all.
Three findings made this more than a counting error:

- The name was in a tracked FILENAME.
- It was in a live-read data file 262 times as `_sources` provenance URLs, read
  by four modules. Deleting the scraped HTML did not touch it.
- It was in `data/meta/tft_set16_meta.json` **in the initial commit's tree**, so
  every commit carried it. A message-only rewrite would have missed all of them.

The plan said the name survived in "5 historical commit messages". Measured:
**15**.

Other in-scope names remained in the tree in quantity - a further ~20 competitor
and tool names, plus references to five sibling projects. The plan's Scope-OUT
list (Data Dragon, CommunityDragon, Meraki, the LoL wiki, Riot API) correctly
stayed.

**The judgement recorded at the time was that this could not be folded into a
path purge**, being a content rewrite across every commit tree that edits a live
data file. That judgement was revised on the day: it CAN be one pass, provided
the working tree is converged to the same pipeline FIRST so the rewrite does not
silently re-edit reviewed files, and provided the byte-pinned shared modules are
excluded by content marker. Both were done.
