"""`SANCTIONED` rows of the atomic-write guard for core/."""
# (relpath, enclosing function or its dotted qualname) -> why this
# implementation may not import core.polled_json. Each must itself use a
# per-writer scratch name, a bounded WinError 5 retry and fsync (asserted for
# the ops trio in tests/test_ops_atomic_writers_rm261.py and for the launcher
# below).
ROWS = {
    ("core/polled_json.py", "_replace_with_retry"):
        "the canonical implementation every other writer routes through",
    ("core/log_rotation.py", "try_rotate"):
        "log ROTATION, not an atomic write (RM-718 a), checked against the "
        "three requirements above. Per-writer scratch: yes - "
        "<name>.rotating/.dropping.<pid>.<token>, and orphans from a crash are "
        "recovered, never overwritten. WinError 5 retry: deliberately none in "
        "the call - the refusal here is not a reader's millisecond poll but "
        "another process holding the log open for its lifetime (measured "
        "2026-10-25 as WinError 32, a sharing violation, RM-864 c), so an "
        "in-call retry only stalls the logging call that triggered the "
        "rollover; the bounded retry is one level up (the handler re-attempts "
        "after _RETRY_AFTER_S, the one-shot writer on its next run), and a "
        "refusal rolls the applied renames back, best effort and no-clobber (a "
        "refused roll-back rename leaves its file one slot higher or under a "
        "scratch name recover_orphans() preserves). fsync: nothing to "
        "flush - it only renames existing files, it writes no payload. It "
        "may not use core.polled_json because those helpers write a payload "
        "to a destination; there is no payload here",
}
