"""RM-299b: GET list params are capped ONLY where the list fans out.

Survey verdicts (2026-10-03) for the csv-parsing route modules are recorded
in the RM-299b commit body; the five that drive per-element engine work were
capped. One test per capped route: over the limit is a 400 naming the
parameter and the compute is NEVER reached; at the limit it is not rejected.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import _get_caps  # noqa: E402
from dashboard import routes_cc_blended_ehp_threat as blended  # noqa: E402
from dashboard import routes_cc_conditional_pressure as condp  # noqa: E402
from dashboard import routes_cc_pairing as pairing  # noqa: E402
from dashboard import routes_ds_combo as combo  # noqa: E402
from dashboard import routes_peel_priority as peel  # noqa: E402


class _H:
    def __init__(self, path):
        self.path = path
        self.sent = None

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)


def _names(n):
    return ",".join(f"Champ{i}" for i in range(n))


def _path(mod, param, n):
    """Both-sided routes require ally AND enemy; the other side gets one."""
    q = {param: _names(n)}
    if mod in (blended, condp):
        other = "enemy" if param == "ally" else "ally"
        q[other] = "Garen"
    return "/x?" + "&".join(f"{k}={v}" for k, v in q.items())


def _run(mod, serve, path, compute_attr="_compute"):
    h = _H(path)
    with mock.patch.object(mod, compute_attr,
                           side_effect=AssertionError("compute reached")) as m:
        try:
            serve(h)
        except AssertionError:
            pass
    return h, m


@pytest.mark.parametrize("mod,serve,param", [
    (blended, blended._serve_cc_blended_ehp_threat, "ally"),
    (blended, blended._serve_cc_blended_ehp_threat, "enemy"),
    (condp, condp._serve_cc_conditional_pressure, "ally"),
    (condp, condp._serve_cc_conditional_pressure, "enemy"),
    (pairing, pairing._serve_cc_pairing, "ally"),
    (peel, peel._serve_peel_priority, "ally"),
])
def test_oversized_champion_list_is_rejected_before_compute(mod, serve, param):
    path = _path(mod, param, _get_caps.MAX_CHAMPION_LIST + 1)
    h, m = _run(mod, serve, path)
    assert m.call_count == 0, "compute ran on an oversized list"
    assert h.sent[0] == 400
    assert json.loads(h.sent[1])["error"].startswith(f"{param}: ")


@pytest.mark.parametrize("mod,serve,param", [
    (blended, blended._serve_cc_blended_ehp_threat, "ally"),
    (condp, condp._serve_cc_conditional_pressure, "enemy"),
    (pairing, pairing._serve_cc_pairing, "ally"),
    (peel, peel._serve_peel_priority, "ally"),
])
def test_list_at_the_limit_is_not_rejected(mod, serve, param):
    path = _path(mod, param, _get_caps.MAX_CHAMPION_LIST)
    h, m = _run(mod, serve, path)
    assert m.call_count == 1 or (h.sent and h.sent[0] != 400)


def test_oversized_combo_sequence_is_rejected():
    seq = ",".join(["Q"] * (combo._MAX_SEQ_STEPS + 1))
    h = _H(f"/api/ds-combo?champion=Ahri&seq={seq}")
    with mock.patch.object(combo, "_compute",
                           side_effect=AssertionError("compute reached")) as m:
        combo._serve_ds_combo(h)
    assert m.call_count == 0
    assert h.sent[0] == 400
    assert json.loads(h.sent[1])["error"].startswith("seq: ")
