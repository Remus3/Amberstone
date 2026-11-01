"""`_TOOLS_UNCLASSIFIED` of the atomic-write guard: only shrinks."""
# RM-258 residual (s144): tools/ is IN scope by default. Out of scope are the
# one-shot extractors the row itself allowlists (`tools/*extract*`), tools/
# test code, and the files below - every tools/ module that offended when the
# blanket tools/ exemption was narrowed (measured 2026-10-27: 100 renames + 82
# scratch names across 77 files, 6 of them extractors). Each entry is
# UNCLASSIFIED, not proven one-shot: it leaves this set by converting onto
# core.polled_json (then it joins _RUNTIME_TOOLS if it is long-running) or by
# a named one-shot proof (no scheduled task, no poller, no reader racing it).
# The set only shrinks: a new tools/ writer starts guarded, and an entry that
# stops offending fails test_tools_baseline_is_exact until it is dropped.
ROWS = {
    "tools/build_portable.py",
}
