"""OQ19 drift guard: the committed current-patch HZ-B build-order tables must
carry the LIVE DS ``ENGINE_VERSION``.

The HZ-B precompute tables (``core.build_order_precompute`` -> ``build_orders_``
and ``core.build_order_variants`` -> ``build_order_variants_``) are patch-keyed
static data read by a FUTURE coach (HZ-C1 / the accrual rail G2 consumer). A DS
engine bump silently leaves them stamped at the OLD engine (they are not
auto-regenerated - reference_hz_precompute_patch_regen), so a consumer would read
build orders computed under stale scorer math.

This guard fails whenever the committed current-patch tables drift from the
engine. The fix is a deterministic, engine-less regen (no :8860 required):

    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m core.build_order_precompute --static --mode all --champions all
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m core.build_order_variants   --static --mode all --champions all

so the two generators re-stamp + recompute against the current engine.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer import ENGINE_VERSION
from core import build_order_precompute as bop
from core import build_order_variants as bov

_MODES = ("sr", "aram", "arena")


@pytest.mark.parametrize("mode", _MODES)
def test_build_order_precompute_stamp_tracks_engine(mode: str) -> None:
    patch = bop.resolve_patch()
    payload = bop.load_build_order_precompute(mode=mode, patch=patch)
    assert payload, (
        f"HZ-B1 build_orders_{mode}.json missing/empty for patch {patch}; "
        f"regen: $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m core.build_order_precompute --static --mode all --champions all"
    )
    assert payload.get("engine_version") == ENGINE_VERSION, (
        f"HZ-B1 build_orders_{mode}.json stamped "
        f"{payload.get('engine_version')!r}, engine is {ENGINE_VERSION!r}; "
        f"regen: $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m core.build_order_precompute --static --mode all --champions all"
    )


@pytest.mark.parametrize("mode", _MODES)
def test_build_order_variants_stamp_tracks_engine(mode: str) -> None:
    patch = bop.resolve_patch()
    payload = bov.load_build_order_variants(mode=mode, patch=patch)
    assert payload, (
        f"HZ-B2 build_order_variants_{mode}.json missing/empty for patch "
        f"{patch}; regen: $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m core.build_order_variants --static --mode all --champions all"
    )
    assert payload.get("engine_version") == ENGINE_VERSION, (
        f"HZ-B2 build_order_variants_{mode}.json stamped "
        f"{payload.get('engine_version')!r}, engine is {ENGINE_VERSION!r}; "
        f"regen: $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m core.build_order_variants --static --mode all --champions all"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
