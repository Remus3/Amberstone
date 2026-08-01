"""Layered CONTENT guard for the committed HZ-B build-order precompute tables.

The sibling stamp guard (``test_build_order_engine_stamp_sync``) only checks that
``payload["engine_version"] == ENGINE_VERSION`` - the STAMP. It never inspects the
per-champ CONTENT, so the committed tables can silently drift stale vs the current
generator while the stamp still reads fresh (the exact gap that let a 1.187.0
generator bump leave the tables computed under old scorer math).

This module adds two layers over the six committed tables

    build_orders_{sr,aram,arena}.json          (content key: "build_orders")
    build_order_variants_{sr,aram,arena}.json   (content key: "build_orders")

1. FAST per-commit checks (roster completeness, stamp integrity, structural
   integrity) that MUST pass against the current committed tables and catch a
   SEED-clobber (roster collapsed to ~10 champs) loudly.
2. A SLOW full-roster regen-vs-committed content diff, env-gated OFF by default
   (``RC_BUILD_ORDER_FULL_REGEN``) so it never taxes per-commit CI. That is the
   layer that actually catches scorer-drift staleness; it runs nightly / on
   demand via the deterministic in-process static path (no :8860 required).

Both table families use the same top-level content key ``build_orders`` (verified
by grep - the variants payload does NOT use a "variants"/"build_order_variants"
content key).
"""
from __future__ import annotations

import json
import os

import pytest

from agents.daemon_slayer import ENGINE_VERSION
from core import build_order_precompute as bop
from core import build_order_variants as bov

# Both families nest the per-champ dict under this single top-level key.
_CONTENT_KEY = "build_orders"

# Cross-table equality is the primary roster guard; this floor is a coarse
# backstop that catches a SEED-clobber to ~10 champs. Deliberately NOT the exact
# roster size (173) so a real roster change does not require a test edit.
_ROSTER_FLOOR = 170

_MODE_KEYS = ("sr", "aram", "arena")
_FAMILIES = ("precompute", "variants")
_TABLES = [(family, mode) for family in _FAMILIES for mode in _MODE_KEYS]
_TABLE_IDS = [f"{family}-{mode}" for family, mode in _TABLES]

_FULL_REGEN = os.environ.get("RC_BUILD_ORDER_FULL_REGEN")


def _load_table(family: str, mode_key: str) -> dict:
    """Read one committed table via its canonical mtime-cached loader.

    Hermetic: the loaders resolve to
    ``data/daemon_slayer/build_orders/<patch>/`` under the repo root and need no
    running server.
    """
    patch = bop.resolve_patch()
    if family == "precompute":
        return bop.load_build_order_precompute(mode=mode_key, patch=patch)
    return bov.load_build_order_variants(mode=mode_key, patch=patch)


def _collect_orders(node: object, path: str = "") -> list:
    """Return ``(json_path, value)`` for every dict key literally named "order"
    anywhere under ``node``. Recurses through nested dicts and lists so it finds
    the leaf regardless of how deep a cell nests it."""
    found: list = []
    if isinstance(node, dict):
        for key, val in node.items():
            child_path = f"{path}/{key}"
            if key == "order":
                found.append((child_path, val))
            else:
                found.extend(_collect_orders(val, child_path))
    elif isinstance(node, list):
        for idx, val in enumerate(node):
            found.extend(_collect_orders(val, f"{path}[{idx}]"))
    return found


# --------------------------------------------------------------------------- #
# FAST per-commit guards
# --------------------------------------------------------------------------- #
def test_roster_completeness_and_cross_table_parity() -> None:
    """Every table carries the SAME champion key-set, above a >=170 floor."""
    rosters: dict = {}
    for family, mode_key in _TABLES:
        payload = _load_table(family, mode_key)
        content = payload.get(_CONTENT_KEY)
        assert isinstance(content, dict) and content, (
            f"{family} {mode_key}: content key {_CONTENT_KEY!r} missing or empty"
        )
        rosters[(family, mode_key)] = frozenset(content.keys())

    for (family, mode_key), keys in rosters.items():
        assert len(keys) >= _ROSTER_FLOOR, (
            f"{family} {mode_key}: roster has {len(keys)} champions, below floor "
            f"{_ROSTER_FLOOR} - a SEED-clobber (regen with no --champions all) "
            f"collapses the table to the ~10-champ seed"
        )

    ref_key, ref_roster = next(iter(rosters.items()))
    for (family, mode_key), keys in rosters.items():
        missing = sorted(ref_roster - keys)[:5]
        extra = sorted(keys - ref_roster)[:5]
        assert keys == ref_roster, (
            f"{family} {mode_key} roster differs from {ref_key[0]} {ref_key[1]}: "
            f"missing={missing} extra={extra}"
        )


@pytest.mark.parametrize("family,mode_key", _TABLES, ids=_TABLE_IDS)
def test_table_stamp_integrity(family: str, mode_key: str) -> None:
    """engine_version tracks the live engine; version tracks the resolved patch."""
    payload = _load_table(family, mode_key)
    assert payload, f"{family} {mode_key}: table missing/empty"
    assert payload.get("engine_version") == ENGINE_VERSION, (
        f"{family} {mode_key}: engine_version stamp "
        f"{payload.get('engine_version')!r} != ENGINE_VERSION {ENGINE_VERSION!r}"
    )
    patch = bop.resolve_patch()
    assert payload.get("version") == patch, (
        f"{family} {mode_key}: version stamp {payload.get('version')!r} != "
        f"resolved patch {patch!r}"
    )


@pytest.mark.parametrize("family,mode_key", _TABLES, ids=_TABLE_IDS)
def test_table_structural_integrity(family: str, mode_key: str) -> None:
    """Every champ entry is a non-empty dict/list, and every build order it holds
    is a non-empty list of numeric-string item ids.

    Item ids are validated as numeric strings ONLY - NOT cross-checked against the
    DDragon catalog, because the Arena/ARAM tables legitimately use 22xxxx/32xxxx
    mirror ids that are absent from the base catalog (a catalog check false-fails).
    """
    payload = _load_table(family, mode_key)
    content = payload.get(_CONTENT_KEY)
    assert isinstance(content, dict) and content, (
        f"{family} {mode_key}: content key {_CONTENT_KEY!r} missing or empty"
    )
    for champ, entry in content.items():
        assert entry and isinstance(entry, (dict, list)), (
            f"{family} {mode_key}: champ {champ!r} entry is not a non-empty "
            f"dict/list (got {type(entry).__name__})"
        )
        orders = _collect_orders(entry)
        assert orders, (
            f"{family} {mode_key}: champ {champ!r} contains no build 'order'"
        )
        for order_path, order in orders:
            assert isinstance(order, list) and order, (
                f"{family} {mode_key}: champ {champ!r} order at {order_path} is "
                f"not a non-empty list"
            )
            for item_id in order:
                assert isinstance(item_id, str) and item_id.isdigit(), (
                    f"{family} {mode_key}: champ {champ!r} order at {order_path} "
                    f"has non-numeric-string item id {item_id!r}"
                )


# --------------------------------------------------------------------------- #
# SLOW content-freshness guard (env-gated OFF; nightly / on-demand only)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not _FULL_REGEN,
    reason="RC_BUILD_ORDER_FULL_REGEN not set - the full-roster regen guard is "
           "slow and runs nightly / on-demand, never per-commit",
)
@pytest.mark.parametrize("family,mode_key", _TABLES, ids=_TABLE_IDS)
def test_content_freshness_matches_static_regen(family: str, mode_key: str) -> None:
    """Regenerate the committed roster via the in-process static path and assert
    the fresh content equals the committed content.

    This is the layer that catches scorer-drift staleness. It is EXPECTED to fail
    while the committed tables are stale; the orchestrator regenerates them, then
    re-runs this with RC_BUILD_ORDER_FULL_REGEN=1 to prove freshness. The
    top-level generated_at stamp is a sibling of build_orders and is excluded by
    comparing the content dicts only.
    """
    payload = _load_table(family, mode_key)
    committed = payload.get(_CONTENT_KEY) or {}
    roster = sorted(committed.keys())
    assert roster, f"{family} {mode_key}: committed roster empty - nothing to regen"

    bop._install_static_transport()
    if family == "precompute":
        regen = bop.generate_table(
            roster,
            mode=bop.DS_MODE_BY_KEY.get(mode_key, "SR"),
            level=bop.DEFAULT_LEVEL,
        )
    else:
        regen = bov.generate_table(
            roster,
            mode=bov.DS_MODE_BY_KEY.get(mode_key, "SR"),
        )
    regen_content = regen.get(_CONTENT_KEY) or {}

    committed_blob = json.dumps(committed, sort_keys=True)
    regen_blob = json.dumps(regen_content, sort_keys=True)
    assert regen_blob == committed_blob, (
        f"{family} {mode_key}: committed content drifted from a fresh static "
        f"regen under ENGINE_VERSION {ENGINE_VERSION} - the table is STALE. Regen "
        f"the full roster: python -m core.build_order_precompute --static --mode "
        f"all --champions all (and the core.build_order_variants sibling)."
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
