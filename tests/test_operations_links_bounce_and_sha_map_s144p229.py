"""docs/BOUNCE_POLICY.md and docs/SHA_CITATION_MAP.md are reachable (RM-1733).

The 2026-10-09 repo review (B13-08, filed as RM-710) found both docs with no
reference from any living doc: SHA_CITATION_MAP was cited only from append-only
history files, BOUNCE_POLICY from nothing. Neither is dead - the bounce policy
is RC's own written position for the armed inbox responder, and the map is the
RULE-SAFE lookup for the dead commit citations in the append-only history
files (RM-501). Both are linked from docs/OPERATIONS.md, the living doc that
owns the responder and the file-location table. Pinned here:
  * both docs exist;
  * docs/OPERATIONS.md names each by its repo path;
  * the bounce pointer sits in the "Inbox responder" section, not elsewhere.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPS = ROOT / "docs" / "OPERATIONS.md"
BOUNCE = "docs/BOUNCE_POLICY.md"
SHA_MAP = "docs/SHA_CITATION_MAP.md"


def _ops() -> str:
    return OPS.read_text(encoding="utf-8")


def test_both_docs_exist():
    assert (ROOT / BOUNCE).is_file()
    assert (ROOT / SHA_MAP).is_file()


def test_operations_links_the_bounce_policy_in_the_responder_section():
    text = _ops()
    head = "## Inbox responder (`RC-InboxResponder`)"
    assert head in text, "the Inbox responder section moved"
    section = text.split(head, 1)[1].split("\n## ", 1)[0]
    assert BOUNCE in section, (
        "docs/OPERATIONS.md Inbox responder section must point at " + BOUNCE)


def test_operations_links_the_sha_citation_map():
    assert SHA_MAP in _ops(), (
        "docs/OPERATIONS.md must point at " + SHA_MAP)
