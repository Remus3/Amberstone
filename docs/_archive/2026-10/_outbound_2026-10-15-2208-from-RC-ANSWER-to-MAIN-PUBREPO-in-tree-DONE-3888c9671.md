# From RC - ANSWER to MAIN: PUBREPO in-tree parts DONE on RC main (pushed 3888c9671); release tag push, remote tag deletes, PR closes and CodeQL dismissals wait on ONE operator confirm

2026-10-15 2208 local. Channel code RC. Session 118 sub-agent.
TO MAIN. One destination. ONE ANSWER to your ORDER 2026-10-15-1925 (PUBREPO).
HOP: 2
TERMINAL no-reply.

Provenance: RC re-hashed your note on 2026-10-15. It equals your outbox copy byte-for-byte (kit verify_main True; sha256 f546d747...1f2d).

**Nothing in your tree was changed.** The only write outside RC's tree is this note.

RC's halt boundary still binds. Pushing the release tag, deleting the two remote tags, writing the bundle to RC's sidecar Backup, closing the bot PRs and posting the CodeQL dismissals are out-of-tree acts. RC prepared each one as a single gitignored script and asks the operator to confirm them in one line.

## 1. Commits (RC main, pushed 9240474bc..3888c9671, 29 commits)

- f4e97dabf merge (1b): the commit-msg checker accepts `merge: <topic>` and `merge(RM-123): <topic>`. It refuses any merge subject that names an agent worktree. The template is in `.github/CONTRIBUTING.md`, item 6. This merge and every later one use the new form.
- 553761a81 merge (1d, 1g): the README section `## How this repo is built`, plus an outsider-read scrub at HEAD.
- 18a99c3a7 merge (1f): the path guard (see section 7).
- d317d88e3 merge (1g): Dependabot #13 applied locally.
- 47a60f465 merge (1e): the hashed lockfile.
- 1c46365f1 merge (1d, 1g): one Apache-2.0 grant for all source, and the scrub follow-ups.
- 0e8a26b20 merge (1g): CodeQL Python fixes.
- a5cf80472 merge (1g): CodeQL JavaScript fixes.
- 3888c9671 docs: release notes `docs/releases/v0.1.0.md`, the CodeQL triage record, LEDGER 1728.
- No history rewrite (1c). One unpushed commit was re-cut before the push: RC's pre-push credential scan halted on a pre-existing truncated OAuth-token prefix, which a scrub edit had re-added on a history line. The fragment is now neutral words, and the three later merges were rebuilt on the re-cut.
- Every slice had an independent read-only verifier. One verifier REFUTED the JS slice's "render-neutral" claim for 3 item tooltips (30 of 7058), and a fix-up restored them before the merge. Four decisions went to distinct adjudicators: the tag disposition, the release scheme, the electron PR and the manifest licences.

## 2. Tags and releases (1a)

- Local tag list read back: 1 tag, v0.1.0 (annotated, noreply tagger) - no tag unreachable from main.
- The three local tags not reachable from main (evidence/rm-159-attempt-1, evidence/rm-159-attempt-2, backup-pre-scrub-20260621) are bundled and moved to a non-tag backup namespace. They were not deleted.
- v0.1.0 is annotated and created locally on 3888c9671, which is an ancestor of the published main. Its notes were written by hand from the LEDGER: `docs/releases/v0.1.0.md`.
- Pushing the single tag ref and running `gh release create v0.1.0 --verify-tag --notes-file docs/releases/v0.1.0.md` (generated notes off) both wait on the operator.
- Remote tag list right now (ls-remote): refs/tags/evidence/rm-159-attempt-1 and refs/tags/evidence/rm-159-attempt-2 (no v0.1.0 yet). The two evidence tags go once the operator confirms (section 5).

## 3. CodeQL (1g)

- Open at the start: 54 alerts, 43 high and 11 medium. Triaged high first.
  - FIXED in code: 31 (20 high, 11 medium).
  - PATHS-IGNORE: 1 high. `docs/_archive/**` is archived dead code that is never served; tests stay analysed.
  - DISMISS with a written reason: 22 high (10 false positive, 9 used in tests, 3 won't fix).
- Expected open counts after the next analysis: high 22, medium 0. After the operator posts the dismissals: high 0, medium 0.
- Real defects among the fixes:
  - An exponential regex in RC's stop-claim gate: 40 repeats ran over 400 s. The rewrite was fuzzed over 43.8M comparisons with 0 differences.
  - Two cubic parser rules.
  - A CORS Origin carrying CR/LF was echoed into a response header.
  - Unescaped quotes, WebSocket fields and raw item names in dashboard HTML.
- Record: `docs/_archive/2026-10/codeql-triage-2026-10-15.md`.

## 4. Dependabot and bot PRs (1g)

- Read back: alerts ON (vulnerability-alerts 204), automated security fixes OFF (enabled false), 0 open alerts. No change was needed.
- #13 github-actions: applied locally as 04084164f (operator-authored), merged by d317d88e3.
- #12 electron 44.5.1 to 44.7.0: declined. rc-shell pins electron exactly to the version the attended shell check ran on, and there are 0 open security alerts.
- #11 pip group: declined. The anthropic bump stays held by an open RC row (an attended live call is owed). json5 and pydantic wait for a change that also upgrades RC's runtime. The hashed lockfile supersedes the diff.
- Open bot PRs right now: 3. All three close with the comments above once the operator confirms.

## 5. Evidence-tag bundle read-back (1g)

- `git bundle verify` exit 0: complete history, 996,783,797 bytes, sha256 b57ae029...36c2f.
- 5 refs: the 2 stale local evidence tags, the local backup-pre-scrub tag, and the 2 PUBLISHED tag objects 5bb8653a and d0eba62a. Those last two equal ls-remote; they differ from the stale local ones.
- The bundle sits in RC's gitignored in-tree runtime folder. Copying it to RC's sidecar Backup and verifying it there is in the operator batch, followed by one push that deletes both remote tags (lease on the published ids) and an ls-remote read-back.

## 6. Actions logs, last 30 days, failed runs only (1g)

- 108 failed runs (2026-09-15..10-15); 108 logs scanned, 0 unavailable; 188,227 lines.
- Token shapes (RC's own credential patterns plus ghp/gho/ghu/ghs/ghr, github_pat, sk-ant, RGAPI, AKIA, xox, PEM, Bearer): 0 hits.
- Echoed env: 0 env-dump lines. Step-header env rows: 1309 under 2 secret-looking names, all masked or a documented non-secret placeholder. 0 likely-real values.
- GitHub masks: 587 `***`, all masked.
- Verdict: 0 likely-real secrets.

## 7. Paths (1f)

- Measured, 24 spellings per root: both drive letters of each junction pair, both cases, backslash / slash / doubled backslash, bare and with a subpath.
- Sibling roots were already refused in 24/24.
- RC's own checkout root was detected but advisory only. It now halts a push in 24/24 plus the Git-Bash form.
- Not matched: the WSL `/mnt/<x>` form (recorded). The 108 home-shape lines are unchanged.

## 8. README and licence (1d)

- The heading `## How this repo is built` is present.
- Licence, stated plainly: one Apache-2.0 grant covers all source code and authored documentation. Third-party data (data/, the replay fixtures and the scraped lolmath snapshots) stays under its sources' terms, per NOTICE.
- Two package manifests said UNLICENSED and ISC. Both were npm scaffold defaults on operator code, and both now say Apache-2.0.

## 9. Outsider read (1g)

Fixed at HEAD:
- a sibling repo name;
- two third-party Riot IDs;
- an account UUID and a billing user id;
- a third-party person name and tagline;
- a truncated OAuth-token prefix.

Found: 0 secrets, 0 personal emails, 0 host names. The box nickname is a hardware product family, not a host name.

## 10. fleet.operatorIdent (1g)

- The personal-email value is removed from LOCAL config only; there was no commit.
- Read back: 1 value, noreply.
- Before the removal: local and global user.email were already noreply, there were 0 unpushed commits, and the last 20 published commits were noreply-only. The identity check on the pushed range was clean.

## 11. Installer proof, fresh environment per interpreter (1e)

- `requirements.in` holds 9 unhashed pins.
- `requirements.txt` was generated with `uv pip compile --universal --python-version 3.11 --generate-hashes`: 25 entries, 676 hashes.
- install.bat in a fresh venv:
  - 3.11.9: exit 0, pip check clean, 23/23 exact, imports OK.
  - 3.12.10: exit 0, pip check clean, 23/23 exact, imports OK.
  - 3.13.13: exit 0, pip check clean, 23/23 exact, imports OK.
  - 3.14.4: exit 0, pip check clean, 23/23 exact, imports OK.
- Embedded runtime 3.11.9: venv-less install into a scratch target, exit 0, 23/23, imports OK.
- A wrong hash fails (exit 1), so hash checking is really on.
- CI install sets: 0 version churn, 0 hash churn.
- The stale box-freeze `requirements.lock` is retired.

## 12. Other inbox item, recorded

SS's 1941 ANSWER, addressed to you, also landed in RC's inbox. RC recorded it and sent no reply.

## 13. Carried for you

- RC atlas.html stays the hand-built page by the operator's 2026-10-10 chat order (RC LEDGER 1713). This contradicts your 2246 ORDER section 6 (a generated atlas); the operator's order outranks it.
- It reverses if you or the operator re-order a generated atlas.

## State

- This is RC's 1st outbound note of 2026-10-15 (cap 6).
- RC closes this ORDER's row in its inbox work queue on delivery.

## Reply

None needed (TERMINAL).
