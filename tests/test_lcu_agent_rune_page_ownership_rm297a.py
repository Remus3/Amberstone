"""RM-297a: tools/lcu_agent.py apply_runes must never delete a USER rune page.

The old filter `nm[:3] in ("RC ", "RC:", "RC-")` matched user pages named
"RC Main", "RC-smurf" and "RC:test". It also called `pg.get` before the
isinstance guard, so one non-dict row aborted the whole handler.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import lcu_agent as agent  # noqa: E402


def _run(pages):
    deleted = []

    def fake(method, path, body=None, *a, **kw):
        if method == "GET" and path == "/lol-perks/v1/pages":
            return pages, None
        if method == "DELETE":
            deleted.append(path.rsplit("/", 1)[-1])
            return None, None
        if method == "POST":
            return {"id": 999}, None
        return None, None

    cmd = {"cmd": "apply_runes", "page_name": "RC: Lulu (ARAM)",
           "primary_id": 8200, "sub_id": 8300, "perk_ids": list(range(9))}
    with mock.patch.object(agent, "lcu_request", side_effect=fake):
        res = agent.execute_command(cmd)
    return res, deleted


def _pg(pid, name, deletable=True):
    return {"id": pid, "name": name, "isDeletable": deletable}


class RunePageOwnership(unittest.TestCase):
    def test_user_pages_with_rc_stems_survive(self):
        pages = [_pg(1, "RC Main"), _pg(2, "RC-smurf"), _pg(3, "RC:test"),
                 _pg(4, "RCx"), _pg(5, "My page")]
        res, deleted = _run(pages)
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(deleted, [])

    def test_rc_authored_pages_are_reclaimed(self):
        pages = [_pg(10, "RC: Lulu (ARAM)"), _pg(11, "RC - Ashe (SR)"),
                 _pg(12, "RC Experimental - Jinx"),
                 _pg(13, "RC: locked", deletable=False)]
        res, deleted = _run(pages)
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(sorted(deleted), ["10", "11", "12"])

    def test_non_dict_row_does_not_abort_the_push(self):
        res, deleted = _run(["garbage", None, 7, _pg(20, "RC: old")])
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(deleted, ["20"])


if __name__ == "__main__":
    unittest.main()
