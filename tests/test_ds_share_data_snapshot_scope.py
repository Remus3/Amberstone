"""What reference data the Share package ships - and what it deliberately does not.

Two independent defects in the shipped package, both fixed by the same
``_build_expected`` data-selection rules and both pinned here.

1. THE PATCH-INDEPENDENT ENGINE TABLES WERE NEVER SHIPPED.
   ``ult_rates.py`` reads ``data/daemon_slayer/spell_cast_rates.json`` and
   ``data/daemon_slayer/ult_cast_rates.json`` from the data ROOT, not from the
   per-patch snapshot directory (``ult_rates.py:60-63``). The sync copied
   ``current.txt`` plus ``<patch>/**`` only, so both tables were absent from the
   package. They feed four production call sites (``ability_dps.py`` spell rates
   and ult procs, ``dps.py`` Malignance, ``ability_hps.py`` HPS); the lookup is
   fail-soft, so the engine still loaded, but every cast-rate-dependent
   assertion failed and the perturbation propagated several layers into
   ranking-shaped assertions. Measured: the shipped suite ran 8802 passed /
   108 failed / 172 errors standalone, against a README advertising it as a
   clean offline run.

2. AN UNLICENSED THIRD-PARTY WIN-RATE SCRAPE WAS BEING REDISTRIBUTED.
   ``mayhem_augment_stats.json`` is a Overlay App E dataset (its own ``endpoint``
   field is ``data.v2.iesdev.com``), carrying ``win_rate`` / ``pick_rate`` /
   ``num_games`` / ``tier`` for 199 augments. The DS engine never reads it - the
   only consumers are host-side (``core/augment_external_source.py``,
   ``tools/ds_feed_index.py``) - so shipping it granted no capability and put a
   third party's aggregate data into a public package with no license grant. It
   also falsified two README claims ("DS does not scrape win-rate aggregators";
   "The mode sidecars shipped here carry pick-rate-class data"). It stays in the
   repo (a live RC runtime feed) and is excluded from the mirror.

The rules are pinned by PROPERTY where possible: rule 1 is checked against the
engine's actual root-level reads rather than a hard-coded pair, and rule 2 is
backed by a scan for ANY ``win_rate`` field anywhere in the shipped data.
"""
from __future__ import annotations

import json
import re

from tools import ds_share_sync as sync

_DATA_PREFIX = "data/daemon_slayer/"

# Column-0 or indented ``_DATA_ROOT / "name.json"`` style joins in the engine
# package. The engine resolves the data ROOT in several modules; only
# ult_rates.py joins a filename directly onto it (everything else goes through
# the per-patch snapshot dir), and this regex finds that class generically.
_ROOT_JOIN = re.compile(r'_DATA_ROOT\s*/\s*"([A-Za-z0-9_]+\.json)"')


def _engine_root_reads() -> set[str]:
    """Filenames the live engine reads straight off ``data/daemon_slayer/``.

    Derived from the engine source, not from a list in this test, so a new
    root-level table added to the engine fails here until the sync ships it.
    """
    eng = sync._REPO / "agents" / "daemon_slayer"
    found: set[str] = set()
    for p in sorted(eng.glob("*.py")):
        found.update(_ROOT_JOIN.findall(p.read_text(encoding="utf-8")))
    return found


def test_engine_reads_root_level_tables_at_all():
    """Tripwire: the premise of the next test is that such reads exist.

    If the engine ever stops reading anything off the data root this test fails
    loudly rather than letting the shipping guard below pass vacuously.
    """
    assert _engine_root_reads(), (
        "no root-level data reads found in the engine - the regex in this "
        "module has rotted, or the engine moved those tables"
    )


def test_every_root_level_table_the_engine_reads_is_shipped():
    """The package ships each patch-independent table the engine opens.

    THE defect: the sync copied ``current.txt`` + ``<patch>/**`` only, so
    ``spell_cast_rates.json`` and ``ult_cast_rates.json`` never reached the
    reviewer and ~172 collection-clean tests errored on the missing path.
    """
    expected = sync._build_expected()
    missing = sorted(
        name for name in _engine_root_reads()
        if f"{_DATA_PREFIX}{name}" not in expected
    )
    assert not missing, (
        "the engine reads these off data/daemon_slayer/ but the Share mirror "
        f"does not ship them, so the shipped suite cannot pass: {missing}"
    )


def test_shipped_root_tables_are_declared_and_all_exist():
    """``_ROOT_DATA_FILES`` is the declared set and every entry is real.

    A renamed or deleted upstream table would otherwise leave a dead entry that
    ships nothing while reading as covered.
    """
    declared = set(sync._ROOT_DATA_FILES)
    assert _engine_root_reads() <= declared, (
        "engine root-level reads not declared in _ROOT_DATA_FILES: "
        f"{sorted(_engine_root_reads() - declared)}"
    )
    live = sync._REPO / "data" / "daemon_slayer"
    dead = sorted(name for name in declared if not (live / name).is_file())
    assert not dead, f"_ROOT_DATA_FILES names files that do not exist: {dead}"


def test_current_txt_still_ships():
    """The patch pointer is unchanged by the root-table addition."""
    assert f"{_DATA_PREFIX}current.txt" in sync._build_expected()


def test_blitz_augment_sidecar_is_not_redistributed():
    """The Overlay App E win-rate scrape is excluded from the public package.

    Not deleted from the repo - it is a live RC runtime feed - but the engine
    never opens it, so shipping it was pure redistribution risk.
    """
    expected = sync._build_expected()
    leaked = sorted(
        rel for rel in expected
        if rel.rsplit("/", 1)[-1] in sync._EXCLUDED_SNAPSHOT_FILES
    )
    assert not leaked, (
        "third-party aggregate data leaked into the public Share package: "
        f"{leaked}"
    )


def test_excluded_sidecar_is_not_read_by_the_engine():
    """Exclusion costs the package nothing - no engine module names it.

    If a future engine change starts reading the sidecar this fails, forcing a
    deliberate re-decision instead of a silent capability loss.
    """
    eng = sync._REPO / "agents" / "daemon_slayer"
    hits = []
    for name in sorted(sync._EXCLUDED_SNAPSHOT_FILES):
        stem = name.rsplit(".", 1)[0]
        for p in sorted(eng.rglob("*.py")):
            if sync._is_transient(p):
                continue
            if stem in p.read_text(encoding="utf-8"):
                hits.append(f"{name} -> {p.relative_to(sync._REPO).as_posix()}")
    assert not hits, (
        "an excluded data file IS referenced by the engine - excluding it "
        f"breaks the package: {hits}"
    )


def test_no_win_rate_field_survives_anywhere_in_the_shipped_data():
    """The property behind the README claim, not just the one known file.

    ``Share/README.md`` states that DS does not scrape win-rate aggregators and
    that the shipped mode sidecars carry pick-rate-class data. Riot developer
    policy permits displaying pick / play rate but not win rate. This asserts
    the claim over the whole shipped snapshot, so a future sidecar carrying a
    win-rate column cannot quietly falsify the README again.
    """
    offenders = []
    for rel, blob in sync._build_expected().items():
        if not rel.startswith(_DATA_PREFIX) or not rel.endswith(".json"):
            continue
        if b"win_rate" not in blob and b"winRate" not in blob:
            continue
        # Confirm it is a real key rather than an incidental substring.
        doc = json.loads(blob.decode("utf-8"))
        stack = [doc]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if "win_rate" in node or "winRate" in node:
                    offenders.append(rel)
                    break
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    assert not offenders, (
        "win-rate data is present in the shipped snapshot, falsifying the "
        f"README data-policy claims: {sorted(set(offenders))}"
    )


def test_snapshot_exclusion_is_surgical():
    """The rest of the patch snapshot still ships (no over-broad predicate)."""
    expected = sync._build_expected()
    snap = [rel for rel in expected
            if rel.startswith(f"{_DATA_PREFIX}{sync._PATCH}/")]
    assert len(snap) >= 15, f"the data snapshot collapsed to {len(snap)} files"
    for name in ("champions.json", "items.json", "manifest.json"):
        assert f"{_DATA_PREFIX}{sync._PATCH}/{name}" in expected
