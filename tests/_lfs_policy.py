"""RM-509: one policy for a test whose subject is a git-LFS-backed file.

DECISION (self-adjudicated 2026-10-03, recorded here and in the RM-509 commit):
CI does NOT fetch LFS. The LFS-backed subjects are the
`data/daemon_slayer/laning_scenarios/<patch>/*.json` tables, ~64 MB each, and a
per-run `git lfs pull` on every push and nightly would blow through the
repository's LFS bandwidth quota in days. So in CI an unfetched pointer stays
an EXPLICIT SKIP with its reason (visible in the skip count), never a warning
over a green pass and never a silent pass.

What changes: `RC_REQUIRE_LFS_CONTENT=1` turns the skip into a FAILURE. Arm it
on any checkout that HAS the LFS content (the dev box) so the pin is enforced
where it can be, and so a checkout that silently lost its smudge filter is
caught instead of skipped. Distinct from RC_REQUIRE_BUILD_ORDER_TABLES on
purpose: "generated" and "fetched into this checkout" have different owners.
"""
from __future__ import annotations

import os

REQUIRE_LFS_ENV = "RC_REQUIRE_LFS_CONTENT"
LFS_POINTER_MAGIC = b"version https://git-lfs"


def lfs_required() -> bool:
    return os.environ.get(REQUIRE_LFS_ENV, "").strip() == "1"


def is_pointer_bytes(head: bytes) -> bool:
    return head.lstrip().startswith(LFS_POINTER_MAGIC)

