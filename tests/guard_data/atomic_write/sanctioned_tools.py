"""`SANCTIONED` rows of the atomic-write guard for tools/."""
# (relpath, enclosing function or its dotted qualname) -> why this
# implementation may not import core.polled_json. Each must itself use a
# per-writer scratch name, a bounded WinError 5 retry and fsync (asserted for
# the ops trio in tests/test_ops_atomic_writers_rm261.py and for the launcher
# below).
ROWS = {
    ("tools/phase_watcher.py", "_replace_with_retry"):
        "RC-PhaseWatcher is served standalone to its agent directory with no "
        "repo above it (tools/phase_watcher_install.ps1), so it cannot import "
        "core/ - the same constraint tests/test_tls_floor_rm752.py pins for "
        "its TLS floor. Its write_sidecar meets the three requirements, "
        "asserted by test_phase_watcher_writer_meets_the_sanction_contract "
        "below: a <name>.<pid>.<token>.tmp scratch, flush + fsync before the "
        "rename, a bounded PermissionError (WinError 5) retry, and the "
        "scratch removed when the rename fails for good",
    ("tools/moon_sync_poller.py", "_replace_with_retry"):
        "RC-MoonSyncPoller is the only process watching the cross-repo "
        "channel, so nothing from core/ may join its import path (an "
        "import-time fault there would kill every poller restart; its own "
        "comment above _replace_with_retry), and its --ping hook must run in "
        "a copy without RC's modules (MAIN 1254 #17). Its _atomic_write meets "
        "the three requirements, asserted by "
        "test_moon_sync_poller_writer_meets_the_sanction_contract below: a "
        "<name>.<pid>.<token>.tmp scratch, flush + fsync before the rename, a "
        "bounded PermissionError (WinError 5) retry, and the scratch removed "
        "when the rename fails for good",
    ("tools/stop_claim_gate.py", "_replace_with_retry"):
        "the Claude Stop hook is PORTABLE and stdlib-only on purpose: a copy "
        "runs at any depth in another tree with no RC package above it (MAIN "
        "1254 #9, tests/test_stop_claim_gate_portable_main1254.py), so it "
        "cannot import core/. Its _atomic_write (the report, the history "
        "roll and the seen set) meets the three requirements, asserted by "
        "test_stop_claim_gate_writer_meets_the_sanction_contract below: a "
        "<name>.<pid>.<token>.tmp scratch, flush + fsync before the rename, a "
        "bounded PermissionError (WinError 5) retry, and the scratch removed "
        "when the rename fails for good. prune_seen's move of a stale seen "
        "file into pruned/ (a rename of an existing file, no payload) goes "
        "through the same helper",
    ("tools/shadow_archive_split.py", "_swap_in"):
        "RM-859 data-fix SWAP, not a payload write: it renames an archive "
        "scratch onto a new archive (never clobbering one) and a kept scratch "
        "onto the live shadow jsonl, and on a refused live rename puts the "
        "archive back. It may not use core.polled_json because that helper's "
        "in-call WinError 5 retry would rename a STALE kept snapshot over any "
        "row a shadow writer appended during the retry; here the bounded "
        "retry is one level up - archive_split's round loop re-reads the live "
        "file, grow-merges a pure append into the kept scratch and retries, "
        "at most MAX_ROUNDS times with REPLACE_RETRY_S between. Checked "
        "against the three requirements by "
        "test_shadow_archive_split_swap_meets_the_sanction_contract below: a "
        "<name>.split.<pid>.<token>.tmp scratch, flush + fsync before every "
        "rename (_write_tmp), a bounded retry, and both scratch files removed "
        "when the swap fails for good",
}
