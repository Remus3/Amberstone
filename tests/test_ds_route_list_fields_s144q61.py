"""RM-1372: a non-list list field in a DS POST body reads as [], never a 500.

Measured on the base before the fix, in dashboard/routes_state.py:

- ``_serve_ds_preview_post`` built ``items`` as
  ``[str(i) for i in (payload.get("items") or []) if i]``. A JSON scalar
  (``"items": 5``, ``5.5``, ``true``) raised TypeError, fell to the outer
  ``except Exception`` and the preview answered 500. A JSON string was
  iterated per character, so ``"3031"`` became the owned ids
  "3", "0", "3", "1"; an object was iterated by its keys.
- ``_serve_build_order_post`` had the same shape twice, for ``items`` and
  for ``incumbent``.

Choice recorded: a non-list reads as [] (absent), the precedent the s144
true-audit already set in dashboard/routes_build_plan.py for the same
``items`` field (``isinstance(raw_items, list)``), and the RM-415
``_as_list`` seam in the same module. Not a 400: every in-tree caller sends
a JSON array (web/js/panels/active_match.js, build_order.js and
routes_build_plan's composed seed calls).

Part (b): routes_build_plan's ``level`` parse read a JSON ``true`` as level 1
(``int(True)``), while ds-preview and build-order take the default for a
boolean since RM-1328. It now takes the default too, so the three routes
agree.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard import routes_build_plan
from dashboard.routes_state import _serve_build_order_post, _serve_ds_preview_post
from tests.test_build_plan_contract import _fake_seed_fn

# Raw JSON texts that are not arrays, parsed the way the dispatcher parses
# a POST body.
_NON_LIST_TOKENS = ("5", "5.5", "true", '"3031"', '{"3031": 1}')
_TARGET = ('"target_armor": 50, "target_mr": 40, "target_max_hp": 2000, '
           '"target_bonus_hp": 0')


class _Handler:
    def __init__(self) -> None:
        self.status = 0
        self.body = b""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body


def _ok_preview() -> dict:
    return {"ok": True, "scorer": "dps", "archetype": "carry",
            "ranked": [], "fell_back": False}


class _FakePlan:
    def to_dict(self) -> dict:
        return {"order": []}


class DsPreviewItemsTests(unittest.TestCase):
    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    def test_non_list_items_read_as_empty_never_500(self, mock_disp):
        mock_disp.return_value = _ok_preview()
        for tok in _NON_LIST_TOKENS:
            with self.subTest(tok=tok):
                mock_disp.reset_mock()
                body = json.loads(
                    '{"champion": "Ahri", "mode": "SR", "archetype": "carry", '
                    f'"items": {tok}, {_TARGET}}}')
                h = _Handler()
                _serve_ds_preview_post(h, body)
                self.assertEqual(h.status, 200, h.body[:200])
                self.assertEqual(mock_disp.call_count, 1)
                self.assertEqual(mock_disp.call_args.kwargs["item_ids"], [])

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    def test_list_items_still_forward(self, mock_disp):
        # Positive control: a legal array keeps its ids and the falsy filter.
        mock_disp.return_value = _ok_preview()
        body = json.loads(
            '{"champion": "Ahri", "mode": "SR", "archetype": "carry", '
            f'"items": [3031, "3089", 0, ""], {_TARGET}}}')
        h = _Handler()
        _serve_ds_preview_post(h, body)
        self.assertEqual(h.status, 200, h.body[:200])
        self.assertEqual(mock_disp.call_args.kwargs["item_ids"],
                         ["3031", "3089"])


class BuildOrderListFieldTests(unittest.TestCase):
    @mock.patch("core.build_order.plan_build_order")
    def test_non_list_items_and_incumbent_read_as_empty_never_500(
            self, mock_plan):
        mock_plan.return_value = _FakePlan()
        for key, kwarg in (("items", "owned_item_ids"),
                           ("incumbent", "incumbent")):
            for tok in _NON_LIST_TOKENS:
                with self.subTest(key=key, tok=tok):
                    mock_plan.reset_mock()
                    body = json.loads(
                        '{"champion": "Ahri", "mode": "SR", '
                        f'"archetype": "carry", "{key}": {tok}, {_TARGET}}}')
                    h = _Handler()
                    _serve_build_order_post(h, body)
                    self.assertEqual(h.status, 200, h.body[:200])
                    self.assertEqual(mock_plan.call_count, 1)
                    self.assertEqual(mock_plan.call_args.kwargs[kwarg], [])

    @mock.patch("core.build_order.plan_build_order")
    def test_list_fields_still_forward(self, mock_plan):
        mock_plan.return_value = _FakePlan()
        body = json.loads(
            '{"champion": "Ahri", "mode": "SR", "archetype": "carry", '
            '"items": [3031, 0, "3089"], "incumbent": ["3031", " ", 3089], '
            f'{_TARGET}}}')
        h = _Handler()
        _serve_build_order_post(h, body)
        self.assertEqual(h.status, 200, h.body[:200])
        self.assertEqual(mock_plan.call_args.kwargs["owned_item_ids"],
                         ["3031", "3089"])
        self.assertEqual(mock_plan.call_args.kwargs["incumbent"],
                         ["3031", "3089"])


def _build_plan_level(raw) -> int:
    seen: list = []
    orig = routes_build_plan._seed_fn_factory

    def _factory(**kw):
        seen.append(kw)
        return _fake_seed_fn

    routes_build_plan._seed_fn_factory = _factory
    try:
        h = _Handler()
        routes_build_plan._serve_build_plan(
            h, {"champion": "Miss Fortune", "items": [], "level": raw})
    finally:
        routes_build_plan._seed_fn_factory = orig
    assert seen, h.body[:200]
    return seen[0]["level"]


class BuildPlanBoolLevelTests(unittest.TestCase):
    def test_bool_level_takes_the_default(self):
        # Part (b): same rule as routes_state._payload_int (RM-1328).
        for raw in (True, False):
            with self.subTest(raw=raw):
                self.assertEqual(_build_plan_level(raw), 11)

    def test_integer_levels_unchanged(self):
        for raw, want in ((1, 1), (14, 14), (40, 18), (-3, 1), (0, 11),
                          ("12", 12), (None, 11), (float("inf"), 11)):
            with self.subTest(raw=raw):
                self.assertEqual(_build_plan_level(raw), want)


if __name__ == "__main__":
    unittest.main()
