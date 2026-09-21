"""RC-ONLY gate arms for the cross-repo channel doc - never vendored.

`tests/test_channel_doc_pin.py` is RC's own stdlib-only portable half; it is
not copied byte-identical anywhere, and the only byte-pinned artifact is
`docs/CHANNEL.md`, via CHANNEL_PIN. THIS module is the half that stays here: it
hard-imports RC-only tools and reads an RC-only config shape, so a vendored
copy would fail at import in every sibling tree and each sibling would then
edit it - the exact drift the pin exists to prevent.

The imports are HARD on purpose. `pytest.importorskip` would turn "the guard
does not exist" into a green run, which is the vacuity ADR-015 exists to stop:
an absent sweep and a clean file must never produce the same verdict. The only
skips here are the ones that are honest about a MEASUREMENT that could not be
taken - the sweep running without its gitignored needle config, and a sibling
checkout that does not carry the doc yet.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# A single-line, whitespace-free literal, so tools/md_guard_selector.py selects
# this module too.
CHANNEL_DOC = "docs/CHANNEL.md"

from tools import sibling_name_sweep as sweep  # noqa: E402
from tools.citation_audit import CITATION_RE  # noqa: E402
from tools.inbox_responder_runner import NOTE_NAME_RE  # noqa: E402

_TWELVE_HEX = re.compile(r"[0-9a-f]{12}")

# The version a copy of the doc DECLARES about itself. Read from the bytes on
# each side rather than from RC's pin, so a carrier's copy is graded by what it
# says it is and never by what RC believes it should be.
_DECLARED_VERSION = re.compile(r"^CHANNEL_VERSION: (\d+)$", re.MULTILINE)


def _declared_version(raw: bytes) -> int | None:
    match = _DECLARED_VERSION.search(raw.decode("ascii", "replace"))
    return int(match.group(1)) if match else None


def _text() -> str:
    return (REPO_ROOT / CHANNEL_DOC).read_bytes().decode("ascii")


def _sibling_roots() -> list[Path]:
    """Where the byte-identical carrier repos live ON THIS MACHINE.

    Same per-host config the cross-repo inbox poller reads. It is gitignored,
    so a fresh clone and CI resolve an EMPTY list here and the mirror arm below
    spells that as ONE explicit named skip (pytest.ini fails an empty parameter
    set at collect). That is the honest shape: a skip that says no carrier was
    checked. A linked worktree is NOT in
    that set (RM-433): it reads the main working tree's copy. A config that
    EXISTS but names zero repos is an assertion failure, never an empty set.
    """
    raw = os.environ.get("RC_MOON_SYNC_REPOS", "")
    if raw:
        return [Path(p.strip()) for p in raw.split(os.pathsep) if p.strip()]
    # RM-433: the shared resolver, so a linked worktree reads the MAIN working
    # tree's gitignored copy rather than resolving zero carriers.
    cfg = sweep.resolve_config_path(REPO_ROOT)
    try:
        blob = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    roots = [Path(str(p)) for p in (blob.get("repos") or []) if str(p).strip()]
    assert roots, (f"{cfg} exists but names zero repos; an empty carrier set "
                   f"would turn the mirror arm into an empty parametrisation")
    return roots


def _adopted_carrier_docs() -> dict[Path, Path]:
    """Carrier root -> that carrier's own copy of the doc, for the carrier
    trees on THIS machine that have actually vendored it.

    Re-derived from the per-host config on every call rather than taken from
    the parameter, because both halves of the answer live OUTSIDE this
    checkout: which trees are carriers at all is named only by the gitignored
    `ops/moon_sync_repos.json` (or `RC_MOON_SYNC_REPOS`), so a fresh clone and
    CI see none; and whether a carrier that does exist has
    adopted the doc is that project's decision, unreachable from here.

    Written this way on purpose. RC's own `docs/CHANNEL.md` is TRACKED and is
    therefore present in every checkout, so it is never the missing half - and
    a gate spelled `(root / "docs" / "CHANNEL.md").is_file()` resolves, to a
    static reader, to that tracked path, which reads as an always-passing guard
    over RC's own artifact and is exactly the shape
    tests/test_skip_condition_hygiene.py rejects. Routing the question through
    the per-host config makes the absent thing - a sibling tree named by
    machine-local state - the thing the gate is seen to depend on.
    """
    out: dict[Path, Path] = {}
    for root in _sibling_roots():
        doc = root / "docs" / "CHANNEL.md"
        if doc.is_file():
            out[root] = doc
    return out


def _grammar_rows() -> list[dict]:
    """Rows of the filename-grammar table in the review-conventions section.

    Returns one dict per data row with the `example` cell and the `rc_gate6`
    cell, located by HEADER TEXT rather than by column index, so adding a
    per-code column cannot silently repoint the assertion at the wrong cell.
    """
    rows: list[dict] = []
    header: list[str] | None = None
    in_section = False
    for line in _text().splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.startswith("## 6.")
            header = None
            continue
        if not in_section or not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells if c) and header is not None:
            continue
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        example = row.get("example", "").strip("`")
        gate = row.get("rc gate 6", "").strip()
        if not example or not gate:
            continue
        rows.append({"example": example, "rc_gate6": gate})
    return rows


def test_channel_doc_passes_the_sweep_structural_arm():
    """The config-free arm, which is the one that still runs in CI."""
    findings = sweep.structural_findings(_text(), path=CHANNEL_DOC, source="TEST")
    assert findings == [], (
        f"sibling-name sweep structural arm reported {len(findings)} finding(s) "
        "on the shared doc; a drive-rooted path is machine-specific and cannot "
        "travel byte-identical"
    )


def test_channel_doc_passes_the_sweep_needle_arm_when_armed():
    cfg = sweep.load_config()
    if cfg.mode != sweep.MODE_ARMED:
        pytest.skip(
            f"sweep is {cfg.mode}, not {sweep.MODE_ARMED}: the gitignored needle "
            "config is absent here, so the name arm was NOT measured"
        )
    findings = sweep.scan_text(
        sweep.build_needles(cfg),
        cfg.codes,
        _text(),
        path=CHANNEL_DOC,
        source="TEST",
    )
    assert findings == [], (
        f"sibling-name sweep name arm reported {len(findings)} finding(s) on "
        "the shared doc; roots are named by CODE only"
    )


def test_no_sweep_needle_is_an_exact_twelve_hex_token():
    """A 12-hex subject digest in a note name must not be able to false-halt.

    The sweep's name arms are alphanumeric-bounded against the original text,
    so a needle INSIDE a contiguous hex run cannot fire in any arm. The single
    remaining shape is a needle that IS exactly twelve hex characters. Asserted,
    never printed - a failure here names no needle.
    """
    cfg = sweep.load_config()
    if cfg.mode != sweep.MODE_ARMED:
        pytest.skip(
            f"sweep is {cfg.mode}, not {sweep.MODE_ARMED}: no needles exist here, so this collision was NOT measured"
        )
    offenders = 0
    for needle in sweep.build_needles(cfg):
        for value in vars(needle).values() if hasattr(needle, "__dict__") else ():
            if isinstance(value, str) and _TWELVE_HEX.fullmatch(value):
                offenders += 1
    assert offenders == 0, (
        f"{offenders} sweep needle variant(s) are exactly twelve hex characters "
        "and would false-halt on a subject digest in a note name (needle text "
        "deliberately not printed)"
    )


def test_channel_doc_carries_no_line_cite_per_citation_audit():
    """RC's citation regex is a superset of the sibling docs-citation shape."""
    hit = CITATION_RE.search(_text())
    assert hit is None, (
        f"line cite {hit.group(0) if hit else ''} in the shared doc; it "
        "resolves in at most one tree and the inbox resolves in none"
    )


def test_channel_doc_grammar_table_matches_rc_gate6():
    rows = _grammar_rows()
    assert len(rows) == 4, (
        f"the filename-grammar table must carry exactly 4 rows, found "
        f"{len(rows)}; an empty or short table would pass the agreement check "
        "vacuously"
    )
    for row in rows:
        admitted = bool(NOTE_NAME_RE.fullmatch(row["example"]))
        declared = row["rc_gate6"].upper() == "ADMIT"
        assert admitted == declared, (
            f"the doc says RC gate 6 would {row['rc_gate6']} "
            f"{row['example']!r}, but the live grammar "
            f"{'ADMITs' if admitted else 'REFUSEs'} it"
        )


# A host with no sibling config (CI) has ZERO roots. pytest.ini sets
# empty_parameter_set_mark = fail_at_collect, so the no-carrier state is spelled
# as ONE None parameter that falls into the body's existing machine-local
# carrier skip, rather than an empty parameter set. An unconditional
# pytest.mark.skip here is refused by tests/test_skip_condition_hygiene.py.
_ROOT_PARAMS = _sibling_roots() or [None]


@pytest.mark.parametrize(
    "root", _ROOT_PARAMS, ids=lambda p: p.name if p is not None else "none"
)
def test_channel_doc_matches_the_sibling_copies_when_present(root):
    """Byte identity with a carrier that has already vendored THIS version.

    Green-by-skip is a REAL state here and there are now two ways to reach it,
    so if you are relying on byte identity, assert this arm actually RAN and
    read which branch it took:

    1. The carrier holds no copy of the doc at all. Adoption is that sibling's
       to make true and RC cannot make it true from here.
    2. The carrier holds an OLDER declared CHANNEL_VERSION, which means the
       re-pin round for the current version is still open. Byte identity is not
       asserted across that gap and the skip line says so with both digests.

    Everything else is an assertion, including two copies that declare the SAME
    version with different bytes.
    """
    adopted = _adopted_carrier_docs()
    if root not in adopted:
        pytest.skip(
            f"carrier {root.name if root is not None else '(none configured)'} "
            f"is not among the {len(adopted)} carrier "
            "tree(s) this machine's gitignored config names that have vendored "
            "the doc - the trees are machine-local and each sibling owns its "
            "own adoption, so neither half is RC's to make true"
        )
    carrier = adopted[root]
    mine = (REPO_ROOT / CHANNEL_DOC).read_bytes().replace(b"\r\n", b"\n")
    theirs = carrier.read_bytes().replace(b"\r\n", b"\n")
    my_digest = hashlib.sha256(mine).hexdigest()
    their_digest = hashlib.sha256(theirs).hexdigest()
    if their_digest == my_digest:
        return

    # An OPEN re-pin round is not drift. The doc's own re-pin section orders the
    # acts: the author writes the bytes FIRST and every other carrier vendors
    # afterwards, and it calls the gap between those two acts PROVISIONAL. A
    # permanently red arm across that gap would say nothing, and the pressure
    # would be to delete it.
    #
    # The discriminator is the version each copy DECLARES in its own bytes, and
    # ONLY a strictly OLDER declared version on the carrier's side buys this
    # branch. Two copies declaring the SAME version with different bytes is the
    # silent divergence this arm exists for and still fails hard, as does a
    # carrier that is AHEAD of RC (then RC is the tree that owes a vendor) and a
    # copy that declares no version at all.
    my_version = _declared_version(mine)
    their_version = _declared_version(theirs)
    if my_version is not None and their_version is not None and their_version < my_version:
        pytest.skip(
            f"PROVISIONAL: carrier {root.name} still declares CHANNEL_VERSION "
            f"{their_version} while this tree declares {my_version}, so the "
            "re-pin round for this version is OPEN and byte identity was NOT "
            "asserted here. It becomes an assertion the moment that carrier "
            f"vendors.\n  this tree: {my_digest}\n  carrier:   {their_digest}"
        )

    raise AssertionError(
        f"carrier {root.name} holds different bytes at CHANNEL_VERSION "
        f"{their_version} against this tree's {my_version}. Re-pin is a JOINT "
        "act: hand over the exact bytes, re-hash in both trees from their own "
        "disk, and bump CHANNEL_VERSION in the same round."
        f"\n  this tree: {my_digest}\n  carrier:   {their_digest}"
    )
