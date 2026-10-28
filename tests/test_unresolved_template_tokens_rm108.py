# arch: RM-108 unresolved-template-token guard | section=tests | frozen=no
"""RM-108 - guard the vendored feeds against unresolved template tokens.

Four assertions, in descending order of how loudly they should fail:

1. ``test_no_token_in_numerically_read_key`` - the load-bearing one. A token in
   a key the engine reads NUMERICALLY is a genuine RM-108 defect. The registry
   section is empty today (measured 2026-07-19: all 4,174 distinct tokens land
   in display-prose keys), so any entry appearing here is news.

2. ``test_no_new_leaf_key_carries_tokens`` - SUBSET, not equality. A new leaf
   key sprouting tokens is a schema change worth a human look; a feed dropping
   a key it used to carry is not, and must not redden CI.

3. ``test_documented_instances_still_unresolved`` - the INVERSE-VALUE
   assertion. Every documented row asserts the token is STILL a token. The day
   Riot publishes ``@BaseHeal@`` as a number this goes red, and that red means
   "go delete R136's zero-pin", not "something broke".

4. ``test_scan_is_patch_invariant`` - anti-churn. Emitted feed paths must carry
   no literal patch number, or every DDragon bump reddens the suite.

Deliberately NOT asserted: occurrence counts. 33,293 of the 56,896 occurrences
live in ``champion_detail``, which moves whenever Riot ships or reworks a
champion. Counting there buys churn and zero signal.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unresolved_token_scan import (  # noqa: E402
    Finding,
    load_json,
    load_registry,
    main,
    regen_allowlist,
    resolve_feed_glob,
    scan,
    value_at,
)

PATCH_LITERAL = re.compile(r"\d+\.\d+\.\d+")


@pytest.fixture(scope="module")
def findings() -> list[Finding]:
    """The scan, with a NON-VACUITY meta-guard.

    Without this assert the whole suite is green under a scan() that returns
    nothing: ``numeric_read_keys`` is legitimately empty, so
    ``test_no_token_in_numerically_read_key`` reduces to "no member of X is in
    the empty set", which is true for every X including the empty one. T2 and
    T4 degrade the same way - each quantifies over the findings, so zero
    findings satisfies them trivially. A completely broken scanner would ship
    CI-green and the capability would be gone with nothing to show it.

    So the fixture asserts the scan found SOMETHING. It deliberately does not
    assert HOW MUCH - occurrence counts churn on every champion rework, which
    is exactly the coupling the module docstring rejects. The sibling
    tools/ds_feed_index.py test carries the same meta-guard as its T1.
    """
    found = scan()
    assert found, (
        "the token scan returned ZERO findings across the vendored feeds - "
        "that is a broken scanner, not clean data. Every other assertion in "
        "this file passes vacuously when this list is empty.")
    return found


@pytest.fixture(scope="module")
def registry() -> dict:
    return load_registry()


def test_no_token_in_numerically_read_key(findings, registry):
    """A token in an engine-read numeric key is a real defect. Empty today."""
    numeric = set(registry["numeric_read_keys"])
    offenders = sorted(
        {(f.feed_glob, f.json_path, f.token) for f in findings if f.leaf_key in numeric}
    )
    assert offenders == [], (
        "unresolved template token(s) landed in a numerically-read key - this is "
        "an RM-108 defect, not documentation: " + repr(offenders[:10])
    )


def test_no_new_leaf_key_carries_tokens(findings, registry):
    """Subset, not equality - a feed dropping a key must not redden CI."""
    allowed = set(registry["display_key_allowlist"]["keys"])
    seen = {f.leaf_key for f in findings}
    novel = sorted(seen - allowed)
    assert novel == [], (
        "new leaf key(s) now carry template tokens; confirm each is display "
        "prose (not engine-read) and then add it to display_key_allowlist: "
        + repr(novel)
    )


def test_documented_instances_still_unresolved(registry):
    """Inverse-value: red here means upstream RESOLVED it and a pin can go."""
    rows = registry["documented_instances"]
    assert rows, "documented_instances must not be empty - it is the primary product"

    checked = 0
    for row in rows:
        for glob in row["feed_globs"]:
            for path in resolve_feed_glob(glob, root=ROOT, champion=row.get("champion")):
                if not path.exists():
                    # data/daemon_slayer/16.10.1 is missing 10 of 20 feeds
                    # (measured); an absent feed is not a failure.
                    continue
                doc = load_json(path)
                if doc is None:
                    continue
                value = value_at(doc, row["json_path"])
                assert isinstance(value, str), (
                    f"{row['id']}: {path.name} {row['json_path']} is no longer a "
                    f"string (got {type(value).__name__}) - upstream reshaped the "
                    "field; re-verify the row"
                )
                assert row["token"] in value, (
                    f"{row['id']}: upstream RESOLVED {row['token']} in {path} at "
                    f"{row['json_path']}. This is GOOD NEWS - go read {row['ref']} "
                    "and replace the pin with the published value."
                )
                checked += 1

    assert checked, "every documented feed file was absent - the scan roots look wrong"


def test_scan_is_patch_invariant(findings):
    """Normalized feed paths carry no literal patch number."""
    leaked = sorted({f.feed_glob for f in findings if PATCH_LITERAL.search(f.feed_glob)})
    assert leaked == [], (
        "feed_glob normalization leaked a literal patch number; every DDragon "
        "bump would redden CI: " + repr(leaked[:10])
    )


@pytest.fixture
def write_spy(monkeypatch):
    """Record every core.polled_json.atomic_write_bytes call, then write."""
    import core.polled_json as pj

    calls = []
    real = pj.atomic_write_bytes

    def spy(path, data):
        calls.append(Path(path))
        real(path, data)

    monkeypatch.setattr(pj, "atomic_write_bytes", spy)
    return calls


def test_regen_allowlist_routes_through_polled_json_and_writes_lf_bytes(
    tmp_path, write_spy
):
    """RM-258: --regen-allowlist goes through core.polled_json (per-writer
    scratch, fsync, bounded WinError 5 retry), not a hand-rolled
    `<dest>.json.tmp` and a bare rename. RM-441: the TRACKED registry stays
    LF-only bytes on Windows."""
    registry = {"numeric_read_keys": [],
                "display_key_allowlist": {"_comment": "c", "keys": ["old"]}}
    dest = tmp_path / "unresolved_template_tokens.json"
    dest.write_bytes((json.dumps(registry, indent=2) + "\n").encode("utf-8"))
    finding = Finding("data/x.json", "a.tooltip", "tooltip", "@Tok@", None)
    keys, wrote = regen_allowlist([finding], dest)
    assert (keys, wrote) == (["tooltip"], True)
    assert write_spy == [dest]
    registry["display_key_allowlist"]["keys"] = ["tooltip"]
    raw = dest.read_bytes()
    assert b"\r\n" not in raw
    assert raw == (json.dumps(registry, indent=2, ensure_ascii=True)
                   + "\n").encode("utf-8")
    assert [q.name for q in tmp_path.iterdir()] == [dest.name]


def test_json_report_routes_through_polled_json(tmp_path, write_spy, monkeypatch):
    """RM-258: the --json report shares the same writer, so it gets the same
    per-writer scratch and leaves no scratch behind."""
    import tools.unresolved_token_scan as uts

    monkeypatch.setattr(uts, "scan", lambda roots=None: [])
    dest = tmp_path / "out" / "report.json"
    assert main(["--json", str(dest)]) == 0
    assert write_spy == [dest]
    assert dest.read_bytes() == (json.dumps(
        {"occurrences": 0, "distinct_tokens": 0, "findings": []},
        indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    assert [q.name for q in dest.parent.iterdir()] == [dest.name]
