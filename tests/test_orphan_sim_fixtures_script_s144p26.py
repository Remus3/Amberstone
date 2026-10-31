"""RM-1177: scripts/rebuild_sim_fixtures.py stays deleted.

The script wrote 26 dev-preview fixtures plus a manifest into data/sim/ at the
repo root. It was dead on two independent counts when it was removed:

1. No caller. Nothing in any .py / .js / .ps1 / .bat / .json / .yml / .xml /
   .html file ran or imported it; only dated history docs named it.
2. No reader of its output. The dev-preview dropdown that loaded
   data/sim/manifest.json lived in web/js/sim.js, deleted in s218
   (824c79c44). The dashboard serves /data/ from web/ only
   (dashboard/routes_static.py _serve_web_asset), so the repo-root data/sim/
   was never servable. The UI applier's narrow allowlist rejects writes to
   data/sim/ (agents/agent4_coach_mentor/ui_applier.py ALLOWED_PATHS; pinned
   by agents/agent3_testing/suite/test_round42.py), and data/sim/ did not
   exist in the main checkout. The one remaining reader,
   scripts/audit_ddragon_items.py collect_from_fixtures, is another script
   that audits only this script's own output, so it is not a consumer.

The panel snapshot harness uses its own tests/snapshot_panels/fixtures/, and
the in-page mock data is AM_MOCK_FIXTURES / CS_MOCK_FIXTURES in web/js. If you
add this script back, first name a real consumer of data/sim/.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_DELETED = ("scripts/rebuild_sim_fixtures.py",)


def test_rebuild_sim_fixtures_stays_deleted():
    back = [rel for rel in _DELETED if (_ROOT / rel).exists()]
    assert back == [], (
        "dead dev-preview fixture writer reappeared; data/sim/ has no reader: "
        + ", ".join(back))
