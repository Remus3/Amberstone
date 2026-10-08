# Security Policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: **Security -> Report a
vulnerability** on this repository, or go straight to the form at
<https://github.com/Remus3/Amberstone/security/advisories/new>. That form is
the only confidential channel this project offers, and it reaches the
repository owner directly. Please do NOT open a public issue for something
exploitable.

No email address is published here on purpose. There is no bug bounty, and
there is no service-level commitment - this is a personal project with one
maintainer, so the honest promise is a look as soon as it is seen, not a
response time.

Include what you would want if you were fixing it: the version or commit, the
platform, the steps, and what an attacker gains. If you have a proof of
concept, please describe it rather than attaching anything that would run.

## Supported versions

Only the current `main` branch. There are no releases, no tags and no
backports, so a fix lands as a commit on `main` and nothing else is patched.

## What this project actually is, because it changes the threat model

Amberstone runs on ONE Windows machine, alongside the game it watches. Every
service binds a local port; nothing is intended to be reachable from another
host, and there is no hosted deployment, no multi-tenant surface and no user
accounts. The realistic threat model is therefore local: something already on
that machine, or content the machine ingests.

The parts worth pointing a reviewer at:

- **Third-party input paths.** The build engine ingests published game data,
  the vision path ingests screen captures, and the cross-repo responder ingests
  notes written by another repository's maintainer. Anything that reads bytes
  it did not author is where the interesting bugs are.
- **The model boundary.** A language model may PROPOSE actions; a deterministic
  allowlist DISPOSES. The model never holds write authority, and a proposal
  outside the allowlist is refused and held rather than executed. If you find a
  path where model output reaches a side effect without passing that check,
  that is the report worth writing.
- **Secrets.** The API key lives in a gitignored file outside version control,
  and the one path that spawns a session on another party's input strips
  `ANTHROPIC_API_KEY` from the child environment before it runs
  (`tools/inbox_responder_spawn.py`, `child_env`). That is a statement about
  that path, not a blanket claim about every subprocess. If you find a key, a
  token, an absolute path carrying a username, or any other credential in the
  tracked tree or in published output, report it privately - it is a leak, not
  a feature.

## Supply chain

- Dependabot (`.github/dependabot.yml`) opens weekly version-update PRs for
  GitHub Actions, pip and npm, one grouped PR per ecosystem. Nothing
  auto-merges; a PR is merged once CI is green on it.
- Every action in `.github/workflows/` is pinned to a full commit SHA, and CI
  installs Python packages from hash-pinned files (`.github/ci/`) with
  `pip install --require-hashes`.
- Every workflow token is read-only by default. The two jobs that commit to
  `main` (the docs-guards auto-repair and the patch-day data sync) are the only
  ones granted `contents: write`, at job level.
- CodeQL runs as a checked-in workflow (`.github/workflows/codeql.yml`) on
  every push to `main`, every pull request and weekly.

## Fuzzing: ruled out, for now

Decided 2026-10-05 (repository-wide supply-chain review). No fuzzing harness
is maintained. These are single-user tools running on the operator's own
machine; their parsers read the operator's own files and pinned upstream game
data, not untrusted network input, so a fuzzer would buy a scorecard point
rather than reduce real risk, at the cost of hours of setup and recurring CI
minutes. This reverses when the project starts parsing untrusted input - a
network-facing service, third-party user-supplied files, or a published parser
library - or when the maintainer orders it.

## Out of scope

- Anything requiring physical or administrative access to the machine that is
  already running the software.
- Denial of service against a service that only listens on localhost.
- Third-party game data being wrong, unavailable, or changed upstream.
- The absence of hardening for deployments this project explicitly does not
  support, such as exposing a port to a network.
