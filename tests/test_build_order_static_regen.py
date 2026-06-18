"""HZ-B fully-static (engine-less) build-order regen (--static).

build_order_precompute._install_static_transport rebinds the DS client's
_post_json to the server's POST-route handlers in-process, so a patch-refresh
regen needs no :8893 and no running server. Output is identical to the live path
by construction (same handlers; verified by a static-vs-live diff at ship time).
These pin that the in-process path resolves real rankings without a server, and
that re-install is idempotent (snapshot already loaded). The global _post_json
rebind is restored in finally so the swap never leaks into other tests.
"""
from __future__ import annotations

import pytest


def test_static_transport_ranks_without_server():
    from core import build_order_precompute as bop
    from core import daemon_slayer_client as dsc

    orig = dsc._post_json
    try:
        bop._install_static_transport()
        # in-process /rank-mage for a real champ -> non-empty rows, no :8893.
        # None would mean "engine unreachable" - which must not happen in-process.
        rows = dsc.rank_mage_for("Ahri", level=11, item_ids=[], mode="SR", top=5)
        assert rows is not None
        assert len(rows) > 0
        assert rows[0].item_id
    finally:
        dsc._post_json = orig


def test_static_transport_idempotent_and_carry_path():
    from core import build_order_precompute as bop
    from core import daemon_slayer_client as dsc

    orig = dsc._post_json
    try:
        bop._install_static_transport()
        bop._install_static_transport()  # snapshot already loaded -> no raise
        # carry/dps path (Garen routes to ds.dps) also resolves in-process.
        rows = dsc.rank_for("Garen", level=11, item_ids=[], mode="SR", top=3)
        assert rows is not None
        assert len(rows) > 0
    finally:
        dsc._post_json = orig


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
