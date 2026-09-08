# Security Policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: **Security -> Report a
vulnerability** on this repository. That form is the only confidential channel
this project offers, and it reaches the repository owner directly. Please do
NOT open a public issue for something exploitable.

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
- **Secrets.** The API key lives in a gitignored file outside version control
  and is stripped from any child process environment. If you find a key, a
  token, an absolute path carrying a username, or any other credential in the
  tracked tree or in published output, report it privately - it is a leak, not
  a feature.

## Out of scope

- Anything requiring physical or administrative access to the machine that is
  already running the software.
- Denial of service against a service that only listens on localhost.
- Third-party game data being wrong, unavailable, or changed upstream.
- The absence of hardening for deployments this project explicitly does not
  support, such as exposing a port to a network.
