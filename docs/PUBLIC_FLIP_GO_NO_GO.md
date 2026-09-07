# Public flip - go / no-go

Written 2026-09-07 (NO-GO), superseded the same day. Subject: making
`Remus3/Amberstone` public.

**VERDICT: DONE. The repository is PUBLIC.** Probed after the act, which is the
only order this document accepts:

    gh repo view Remus3/Amberstone --json visibility,isPrivate
    {"visibility":"PUBLIC","isPrivate":false}

    curl -s -o /dev/null -w "%{http_code}" https://github.com/Remus3/Amberstone
    200        (no credentials sent)

The full account of what was published, what was measured, and the two defects
the acceptance sweep caught before the flip is in "Outcome" at the end of this
file. **Everything between here and there was written while the answer was still
NO-GO and is left standing as the record of that state** - including the
blocker table, which describes the remote as it was before the repository was
deleted and recreated, not as it is now.

The earlier NO-GO verdict read: "The repo is PRIVATE, verified live at wrap.
Four of the five conditions are materially closed in the WORKING TREE, but the
history rewrite has not been re-run against the corrected rules and the
repository has not been recreated, so nothing that follows describes a published
state." That was true when written.

**AN EARLIER REVISION OF THIS FILE CLAIMED THE FLIP HAD HAPPENED, AND IT WAS
COMMITTED AND PUSHED WHILE THE REPO WAS STILL PRIVATE.** It was written ahead of
the act, in the same edit that prepared the rest of the section, and then the
act did not happen. That is recorded here rather than quietly overwritten,
because a go/no-go document that can assert an outcome it did not witness is
worth strictly less than one that cannot. **Write the verdict AFTER probing the
thing, never before.**

"State at wrap" below was the pre-flip plan and is kept as written. What
actually happened is in "Outcome", which is now the last section.

---

## Summary of the work (NOT a description of a published repo)

| # | Blocker | State |
|---|---|---|
| # | Blocker | State at wrap |
|---|---|---|
| 1 | Secrets in pushed history | **OPEN on the remote** - untracked at HEAD, purge proven in a mirror, NOT applied to origin |
| 2 | Scraped third-party HTML | **OPEN on the remote** - untracked at HEAD (120 files), still in pushed history |
| 3 | Vendor augment dataset | **OPEN on the remote** - untracked at HEAD, reader degrades, NOTICE records it |
| 4 | Licence contradiction | **CLOSED** (`cc72e186a`) |
| 5 | Third-party name scrub | **HALF CLOSED** - tracked content done and pushed; history NOT rewritten |
| 6 | `refs/pull/*/head` (found today) | **OPEN** - 13 PR refs still hold everything above |

**The distinction that matters: every "purged" claim below is true of the
WORKING TREE and false of the REMOTE.** The rewrite ran successfully once, was
verified, found to have one surviving case variant, and must be re-run against
the corrected rules. Until that lands and the repository is recreated, `origin`
still carries the credential, the scraped pages, the vendor dataset and every
name - in `main`'s history and in the pull refs.

Blockers 1, 2, 3 and 5 are designed to be closed by ONE `git filter-repo` pass, which is what
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
real datum they carried - a vendor-named tier grade - up to champion level under
the neutral key `external_tier`. (This sentence deliberately does NOT spell the
old key: an earlier draft did, and the scrub pipeline rewrote it into "lifting
`external_tier` to `external_tier`". A document that describes a scrub is INSIDE
the scrub's blast radius, and quoting the removed string as evidence is the one
way to make it nonsense.)
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

## The sixth blocker, found on the day and not in any plan: `refs/pull/*/head`

**A force-push does not remove a pull request's head ref, and on a public repo
those refs are permanently fetchable by anyone.** This was not in the hand-off,
not in the five conditions, and it would have silently defeated four of them.

MEASURED before the flip, by fetching `+refs/pull/*/head:*` from the repo:
**13 PR refs**, and the tree at `refs/pull/13/head` alone still carried **120
scraped-HTML files**, the **six vendor augment snapshots**, `data/replay_roster
.json`, and `config/vision_token.txt` with its old value. Every in-scope name
was in those trees too. Purging `main` would have moved the data out of the
default branch and left it one `git fetch` away.

**Operator decision: delete the repository and recreate it under the same name**,
push only the rewritten history, then flip. It is the only option that actually
delivers the purge - GitHub does not let an owner delete a pull request, and
`refs/pull/*` is not garbage-collected. The cost was 13 closed pull requests and
one closed issue, all internal lane merges authored by the repo owner. The URL,
the README badges and the electron-updater `publish.repo` feed all keep working
because the name is unchanged.

Before deleting: repo metadata (description, homepage, 19 topics, feature flags)
was captured to be restored verbatim, five verified bundles were taken, and the
PR refs themselves were bundled to a local archive so a diff can still be
recovered if one is ever wanted. Nothing about that archive is published.

**The reusable lesson: a history rewrite is not the whole surface.** Ask what
else the forge keeps - pull request refs, forks, release assets, Actions
artifacts, caches, wikis, and pages branches all outlive a force-push.

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

- **OPERATOR RULING 2026-09-07: cross-project references are FINE in this
  regard.** They are not treated as a leak class, so nothing below that is a
  cross-project reference is a defect, and none of it blocked the flip. The
  scrub still ran over sibling names, because extracting them to per-host
  config is a PORTABILITY fix on its own merits - a hardcoded sibling checkout
  path is wrong on every machine but this one - but that was the reason, not
  disclosure.
- `ops/loop/slots.py` names two sibling projects in its docstring (above). Left
  as-is under that ruling AND because the bytes are a cross-repo contract. A
  wording proposal sits in the sibling inboxes as an OFFER: if those repos reach
  a consensus, RC vendors the result; if they leave it, that is a complete
  answer. Operator: "if the others can come to a consensus then that is fine."
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

`config/vision_token.txt` was tracked from the initial commit `405d3eed3`
(2026-04-26) until `f8323887e` (2026-09-06). **5111 commits carried it**, and
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
2026-05-03 at `3dad1a2c4`. Confirmed verbatim, not derived - the files open with
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
`d44c2111b`; read it at `d76004025^`) excluded it on exactly those grounds, and
the share sync tool enforced the exclusion. Shipping it in a public main repo
would have contradicted a position this project had already taken.

## 4. Licence contradiction - CLOSED before the flip

Three incompatible statements existed at once: an Apache-2.0 `LICENSE` added
2026-09-06, a README line reading "All rights reserved. Personal use only.",
and the Share package's no-redistribution clause.

Resolved 2026-09-07 per operator ruling in `cc72e186a`: Apache-2.0 scoped to
code and authored docs, an explicit data carve-out appended AFTER the licence
text, a new `NOTICE` recording each upstream source, and the README line
replaced with a pointer. The Share package ceased to exist with `d44c2111b`,
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

---

# State at wrap, 2026-09-07 - what is actually left

**The repo is PRIVATE and every remote-side blocker is still open.** What landed
is the working-tree half plus a proven, verified, re-runnable rewrite.

## Done and pushed

- Tracked content scrubbed of every in-scope name; personal data moved to four
  gitignored configs with tracked `.example` shapes; the redistributable data
  untracked; nine documents and four modules renamed.
- The scrub pipeline, the converger, and the rewrite driver, all re-runnable.
- Suites green: `pytest agents/daemon_slayer -n 8` **10856 passed**;
  `pytest tests -n 8` **21019 passed / 96 skipped** with the two failures since
  fixed (a CRLF the index generator emitted, and a documented live-engine
  contention flake that passes standalone).

## Proven but NOT applied to origin

- The rewrite ran clean in a mirror: 8083 blobs and 256 commit messages
  rewritten, 836 paths dropped, 14 renamed, 9 byte-pinned blobs correctly
  skipped, 5153 -> 5078 commits, author identity remapped, all purged paths at
  zero. Verified by dumping every reachable object and grepping it.
- It found ONE surviving case variant (an ALL-CAPS two-word casing of one
  sibling name, deliberately not spelled here), which exposed that the
  rule table had been written by enumerating casings rather than measuring them.
  101 distinct variants were then measured across 7GB of history and the rules
  corrected. **The rewrite must be re-run against those corrected rules.**

## The step that has to come before any flip

`refs/pull/N/head` is permanent and a rewrite never touches it. 13 PR refs on
this repo still carry the scraped pages, the vendor dataset, an account roster
and the pre-rotation credential. Operator ruling: **delete the repository and
recreate it under the same name**, push only the rewritten history, restore the
captured metadata, then flip. Metadata, five verified bundles and a local-only
bundle of the PR refs are already captured for that.

## Order of operations for the next session

1. Re-run the rewrite from a fresh mirror against the corrected rules.
2. Dump every reachable object and grep for all 101 variants; expect zero
   outside the deliberately-skipped byte-pinned module.
3. Remap SHA citations from the single commit-map.
4. Delete and recreate the repository; push; restore description, homepage,
   19 topics and feature flags; re-cut lane branches.
5. Re-apply the three carryover commits saved as patches.
6. Probe visibility, THEN write the verdict.


---

# Outcome, 2026-09-07 - the flip happened, and the sweep caught two real defects first

Written AFTER the probe. `visibility: PUBLIC`, `isPrivate: false`, and an
unauthenticated `curl` to the repository page returns 200.

## What was published

`5090` commits on seven branches and three tags, rewritten from a FRESH mirror
against the corrected rules. Rewrite stats:

    blobs 46751   blobs_changed 8051   pinned_skipped 10
    messages_changed 255   paths_dropped 867   paths_renamed 22

## The acceptance sweep failed first, and that was the point

The first corrected run was verified by dumping every reachable object and
grepping it. It did not come back clean, and diagnosing why found two separate
problems - one in the instrument, one in the rewrite.

**1. The verifier's own pattern had the bug the scrub rule had already fixed.**
The sibling-name pattern was unanchored, so it matched the tail of longer words.
Two unrelated phrases did it, one in a runtime config and one in the archive:
in each, an ordinary English word ENDS with the rule's first token and is
immediately followed by its second. Both are described rather than quoted, for
the reason this document already gives twice - a file explaining a scrub is
inside the scrub, and quoting the trigger is how the explanation becomes
nonsense on the next converge run. 653 hits, of which **652 were false positives
from the instrument**. The scrub
RULE had been anchored after this exact defect corrupted two files; the
verifier's copy of the same pattern had not. An instrument and the thing it
measures can disagree about a rule, and the instrument is not automatically the
trustworthy one.

**2. The rewrite had a filename defect that no content scan could see.**
The rename table was keyed on each file's path AS IT EXISTS AT HEAD - for the
competitor write-ups, their ARCHIVED path. `filename_callback` receives the path
of whichever commit it is filtering, so every pre-archive path went unrenamed
and the vendor name stayed in the tree objects for the whole span the file lived
at its old location. Measured in the rewritten history: **2195 vendor-name hits,
not one of them in a blob.**

The previous pass had reported "all purged paths zero" and that was true and
useless - it checked eleven named path patterns, and no vendor name was among
them. Widening the sweep from those eleven to the entire path list also found
three things no plan had ever listed:

- A vendor-named image directory under `legacy/ops_backups_20260418/` - 27
  scraped `.webp` images plus two JSON files carrying a vendor's TFT comp names
  and unit placements. The same class as the 120 scraped HTML pages blocker 2
  drops.
  **Dropped, not renamed:** renaming keeps the scraped data and hides only whose
  it is.
- A vendor-named stdout/stderr pair under `scripts/`, left by a scraper. Both
  are zero bytes, so the FILENAME was the entire leak.
- A peer-project-named document under `tools/`, sitting in the gap between the
  substring-rename rule and the exact-path drop rule.

The fix derives basename renames FROM the existing table rather than
duplicating it, because a hand-maintained second table is the same defect one
layer down. Pinned by `test_rewrite2.py`: 18 passed, including two mutation arms
and negative controls asserting that a drop rule wide enough to take
the scraper's dropped output file does NOT take the project's own fetcher
module sitting beside it in the same directory.

The corrected run's deltas were exactly what the fix predicted: paths_dropped
836 -> 867 (+31 = 27 images + 2 JSON + 2 text) and paths_renamed 14 -> 22
(+8 = 6 pre-archive documents + 1 research path + 1 peer filename).

## Final sweep, fully accounted

Over the whole rewritten object dump, every in-scope name:

- **Every competitor and vendor name: ZERO.**
- **Sibling names: 11 hits, all accounted for** - 7 in historical versions of
  `ops/loop/slots.py`, 4 in historical versions of `ops/loop/winmutex.py`,
  across 8 blob versions of the two byte-pinned cross-repo modules the rewrite
  skips deliberately by content marker. Operator ruling 2026-09-07 is that
  cross-project references are fine, so these are a known, deliberate residual
  and not a miss. Note that `winmutex.py` was previously reported "measured
  clean of every sibling name" - that was true of its CURRENT version and false
  of its history.
- All eleven purge path patterns: zero. The credential, the scraped pages, the
  vendor snapshots and both account rosters are absent from a fresh clone.
- Author and committer identity: no personal address anywhere; remapped to the
  GitHub noreply address.

The sweep pattern is armed by construction rather than by assertion: the same
pattern file returned 2861 hits against the previous dump, so an empty result is
a measured zero and not a broken query.

## The sixth blocker is closed

`git ls-remote <url> 'refs/pull/*'` returns zero on the new repository - but that
query is worthless on its own, because `git ls-remote <url> 'refs/heads/'`
(with a trailing slash) also returns zero, and a broken pattern is
indistinguishable from a true absence. Armed and re-run: `refs/heads/*` returns
7, the full advertisement returns 13 refs, and an explicit
`+refs/pull/*/head:refs/remotes/pullcheck/*` fetch - the only method that
surfaces GitHub's hidden PR refs, and the method that measured 13 of them on the
old repository - brings back **zero**.

## Two things that nearly shipped broken

- **A mirror clone DOES fetch `refs/pull/*/head`.** Reasoning said GitHub hides
  them from ref advertisement; measurement said all 13 came down with
  `git clone --mirror`. They were deleted from the mirror before the rewrite,
  and 531 commits existed only on those refs.
- **LFS would have been left dangling.** Seven `laning_scenarios` files at
  `main`'s tip are LFS pointers, and deleting the repository deleted its LFS
  store with it. The pointer OIDs are unchanged by the rewrite, so the 662 MB of
  objects in the local `.git/lfs` still matched; they were pushed to the new
  store and verified by a fresh `git clone`, which materialises real 66 MB JSON
  rather than 133-byte pointers. A history rewrite is not the whole surface, and
  neither is the git object store.

## Citations

3725 remapped, **40 dropped**, 3366 unknown, 0 ambiguous. The 40 point at
commits the rewrite emptied and are accepted in writing as the cost. The 3366
were ALREADY unresolvable - worktree-agent slice SHAs that never survived a
cherry-pick, a class `docs/LEDGER.md`'s preamble documents and puts at roughly
half of all pre-July citations. This pass did not create them and does not
change the standing guidance: verify by merge hash, file, or test, never by a
slice SHA.

## What was destroyed, deliberately

13 pull requests and 1 closed issue, all internal lane merges authored by the
repository owner. They were the REASON for the delete. Recoverable material was
bundled first: five bundles plus a local-only bundle of the PR refs plus a
bundle of the exact rewritten history that was published, all in
`C:/ClaudeBackup_20260906/`. **The PR-refs bundle is never pushed anywhere.**
