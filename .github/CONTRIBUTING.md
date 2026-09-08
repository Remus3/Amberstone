# Contributing

Read this first, because the honest answer is unusual: **Amberstone is a
personal project published as source, not a project seeking contributors.** It
runs on one Windows machine against a live game client, and most of it cannot
be exercised without that machine and a Riot account in a match.

So set expectations accordingly:

- **Issues are welcome.** A defect report, a correction, or a question about
  how something works is genuinely useful, and the parts of the codebase that
  are pure computation can be checked by anyone.
- **Pull requests may not be merged**, even good ones. That is not a comment on
  the work - it is that every change here is expected to carry tests, live
  measurements and a ledger entry, and a drive-by patch usually cannot. If you
  want to send one anyway, please open an issue first so the design question
  gets settled before you spend the time.
- **Forks need no permission.** The source is Apache-2.0 (see
  [`LICENSE`](../LICENSE)), and the part most worth lifting - the build engine
  under [`agents/daemon_slayer/`](../agents/daemon_slayer/) - is self-contained
  and carries its own test suite. Note that the Apache licence covers the
  source and authored docs, NOT the third-party game data under `data/`, which
  stays governed by its own upstream terms; [`NOTICE`](../NOTICE) records them
  source by source.

## Before you file an issue

Say what you observed and what you expected, and give the evidence:

- The command you ran, or the endpoint you called, and its output.
- The file and line if you are pointing at code. `path/to/file.py:123` is
  clickable and saves a round trip.
- Whether you measured it or inferred it. Both are useful; conflating them is
  not, and this project has paid for that mistake more than once.

Do NOT include anything from your own machine that you would not publish: API
keys, account identifiers, match ids tied to your account, or absolute paths
carrying your username. Suspected vulnerabilities go through
[`SECURITY.md`](./SECURITY.md), not a public issue.

## If you do send a pull request

The repository's own rules are not negotiable, and CI plus the git hooks
enforce most of them:

1. **Install the hooks first.** A fresh clone runs ZERO hooks, because
   `core.hooksPath` is local config and is not cloned:

   ```
   python scripts/install_hooks.py
   ```

2. **Tests first.** Every behaviour change lands with a failing test that the
   change makes pass. Run the two suites from the repository root, never
   `pytest .`:

   ```
   pytest tests
   pytest agents/daemon_slayer
   ```

3. **7-bit ASCII in authored content.** No em-dashes or en-dashes, no smart
   quotes, anywhere - code, comments, docstrings, Markdown, commit messages.
   Use a spaced hyphen for a clause break. This is enforced by a commit hook
   and it exists because a UTF-8 dash inside a PowerShell string has already
   broken a boot script once.

4. **Keep the diff to one item.** One reviewable change per commit, with a
   message that says what was measured, not only what was edited.

5. **Do not add a `Co-Authored-By: Claude` trailer.** The commit-msg hook
   strips it by policy, so its absence is deliberate rather than an oversight.

`CLAUDE.md` at the repository root is the full operating context, including the
frozen-file list. It is written for coding agents, but it is the most complete
statement of how this codebase expects to be changed, so it is worth reading
before touching anything under `app/`, `core/` or `ops/`.

## Code of conduct

By taking part you agree to [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).
