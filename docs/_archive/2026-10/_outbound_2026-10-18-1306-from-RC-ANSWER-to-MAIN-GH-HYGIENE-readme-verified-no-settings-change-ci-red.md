# From RC - ANSWER to MAIN: GH-HYGIENE - README verified, no settings change, two red workflows at HEAD

2026-10-18 1306 local. Channel code RC. Headless run gh-hygiene.
TO MAIN. One destination. ONE ANSWER to your ORDER 2026-10-18 1215 (GH-HYGIENE).
HOP: 2
TERMINAL no-reply.

Provenance: the ORDER note's sha256 39a11dc0db36079b68efbb640964115705154a45b7a823d20f2ebd80343e2be0 was re-hashed before work and matched.

## README fixes
None - verified. No claim was stale. Read back: all relative links resolve; every backticked repo path exists (install.bat, start.bat, requirements.txt, scripts/install_hooks.py, tools/regen_rc_cert.ps1, LICENSES/OFL-1.1.txt, oss/win32_atomic_io); badge workflows ci.yml and docs-guards.yml exist; external links git-lfs.com and the atlas page answer 200; "How this repo is built" heading present; the licence paragraph states Apache-2.0 and matches LICENSE. No claim on README by a live agent; README had no uncommitted edits. No path, email or account id in README.

## Settings changed
None. Read back: description set and accurate; homepage is the atlas page; 20 topics; default branch main; wiki, projects and discussions off, issues on; detected licence apache-2.0; not archived; issue and PR templates present (tree takes outside issues); branch protection on main: enforce_admins true, force pushes off, deletions off, no required checks or reviews configured.

## Outside-view issues
- FOUND, LEFT: the ci workflow and the docs-guards workflow both failed on the push of HEAD (the kit v19 adoption commit). ci: tests/test_inbox_tick_v8.py::test_fleet_route_passes_kind_through_to_the_kit (kit v19 call shape vs a pre-v8 assertion). docs-guards: one tracked archive path is 131 chars, over the 129 clone-root budget. Both badges are red. Left because the fix touches a test and an append-only archive name, outside a README/settings ORDER; reported here for the next lane.
- Release v0.1.0 (the only release and tag) is reachable from main; notes are hand-written. Open issues 0, open PRs 0. codeql and the patch-day sync workflows are green.
- Left (allowlisted append-only records): none scrubbed.

## Needs an operator ORDER
- Visibility is PUBLIC: matches RC's intended posture (public Apache-2.0 repo); no mismatch.
- Social preview: REPORT ONLY - a custom image is set (usesCustomOpenGraphImage true).
- Branch protection carries no required status checks, so red CI does not block merges; change only on an operator ORDER.

## Commits and push
No content change was needed. Only this note's tracked copy is committed; push per RC's pre-push gates, read-back reported to the operator.
