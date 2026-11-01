"""`SANCTIONED` rows of the atomic-write guard for ops/."""
# (relpath, enclosing function or its dotted qualname) -> why this
# implementation may not import core.polled_json. Each must itself use a
# per-writer scratch name, a bounded WinError 5 retry and fsync (asserted for
# the ops trio in tests/test_ops_atomic_writers_rm261.py and for the launcher
# below).
ROWS = {
    ("ops/rc_supervisor.py", "_replace_with_retry"):
        "FROZEN watchdog: stdlib-only by design so a broken app package "
        "cannot take the process that restarts it down with it",
    ("ops/rc_dev_runtime.py", "_atomic_write_json"):
        "FROZEN runtime host: stdlib-only heartbeat writer with its own "
        "measured retry budget (tests/test_rc_dev_runtime_atomic_write_retry.py)",
    ("ops/rc_transactional_deploy.py", "_replace_with_retry"):
        "deploy transaction runs while the app tree is being swapped, so it "
        "must not import from the tree it is replacing",
    ("ops/launcher/service_host.py", "_replace_with_retry"):
        "PKG-1 launcher service host: stdlib-only and run under `python -I` "
        "with no RC module on sys.path, because it starts and stops the "
        "backend core.polled_json belongs to (docs/PACKAGING_PLAN.md 3.1). "
        "Its atomic_write_json meets the three requirements, asserted by "
        "test_launcher_writer_meets_the_sanction_contract below: a "
        "<dest>.<pid>.<token>.tmp scratch, flush + fsync before the rename, "
        "a bounded PermissionError (WinError 5) retry, and the scratch "
        "removed when the rename fails for good",
    ("ops/launcher/service_host.py", "HostLog.write"):
        "log ROTATION, not an atomic write (the core/log_rotation.py "
        "try_rotate class), in the same stdlib-only launcher, checked against "
        "the three requirements. fsync: nothing to flush - the rename moves "
        "an existing file and writes no payload. WinError 5 retry: none in "
        "the call - a refused rename (a reader holding the log or its `.1` "
        "open) is swallowed, the line still appended, and the next write "
        "re-checks the size and re-attempts, so the retry is one level up "
        "and the log outgrows LOG_MAX_BYTES only while that holder stays. "
        "Per-writer scratch: none - the target is the fixed `.1` slot. The "
        "host is single-writer under HostLock except main()'s two pre-lock "
        "lines (bad manifest, lock refused), so a second launch crossing the "
        "size threshold in the same instant as the live host can replace "
        "`.1` with a one-line file: one lost older generation, never torn "
        "bytes (residual reported for the PKG-1b slice)",
    ("ops/launcher/updater.py", "_replace_with_retry"):
        "PKG-2 backend updater: stdlib-only and run under `python -I` with no "
        "RC module on sys.path, because it replaces the backend tree "
        "core.polled_json belongs to (docs/PACKAGING_PLAN.md 3.4) - the same "
        "reason as the ops/rc_transactional_deploy.py row. Its _write_json / "
        "_write_bytes_atomic meet the three requirements, asserted by "
        "test_launcher_writer_meets_the_sanction_contract below: a "
        "<dest>.<pid>.<token>.tmp scratch, flush + fsync before the rename, "
        "a bounded PermissionError (WinError 5) retry, and the scratch "
        "removed when the rename fails for good. The same helper also moves "
        "the updater's own staging and quarantine entries (renames of whole "
        "existing files and directories inside ops/runtime/, no payload)",
}
