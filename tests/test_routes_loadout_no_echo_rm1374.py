"""RM-1374 (filed by the s144 queue lane as RM-1374): `/api/loadout/apply`
never echoes the caller's champion, variant or build-path key in its 404.

The defect: `dashboard/routes_loadout._resolve_user_build` built its two
failure texts from the caller's own values (`no user build {uid!r} for
{champion!r}`, `user build {uid!r} malformed`), and
`_serve_loadout_apply_post` sent the resolver's dict back VERBATIM as the
404 body. The variant resolver it shares that 404 with
(`coaches.loadout_resolver.resolve`) does the same (`no variant
{variant!r} for {champion!r}`, `variant {variant!r} not allowed in ...`,
`no build_path {path_key!r} for ...`), so the same-root sibling is the
route's 404, not only the user-build helper. It was the last site of the
RM-1255 census (`tests/test_dashboard_route_no_repr_echo_guard_rm1255.py`).

Consumer re-check (before the fix): both callers map a non-2xx to null -
`web/js/panels/champ_select.js` `_csvApplyLoadout` and
`web/js/panels/item_build.js` `_ibPushItems` read
`r && r.ok ? r.json() : null` - so the text was never rendered. The fix is
the CLAUDE.md "Error Handling" floor (a fixed reply text, the raw one in
the log), not a visible UI change.

These are route-entry tests: each drives `_serve_loadout_apply_post` with a
stub handler, the same entry the dispatcher calls.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from unittest import mock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard import routes_loadout as rt  # noqa: E402

# Distinctive caller values: if any of them reaches a reply byte, the
# route echoed it.
_CHAMP = "ZzEchoChamp"
_UID = "feedc0de"
_VARIANT = "zz_echo_variant"
_PATH = "zz_echo_path"


class _Handler:
    def __init__(self) -> None:
        self.status: int | None = None
        self.body: bytes = b""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body


def _apply(payload: dict) -> _Handler:
    h = _Handler()
    rt._serve_loadout_apply_post(h, payload)
    return h


def _assert_no_echo(h: _Handler, *values: str) -> dict:
    text = h.body.decode("utf-8")
    for value in values:
        assert value not in text, (
            f"the 404 reply echoes the caller's value {value}: {text}")
    return json.loads(text)


def _patch_user_store(recs, shaped):
    return (
        mock.patch("coaches.sr_user_builds.list_for", return_value=recs),
        mock.patch("coaches.sr_user_builds.format_for_display",
                   return_value=shaped),
    )


def test_unknown_user_build_answers_a_fixed_404():
    p1, p2 = _patch_user_store([], None)
    with p1, p2:
        h = _apply({"champion": _CHAMP, "variant": "userbuild_" + _UID,
                    "mode": "sr"})
    assert h.status == 404
    body = _assert_no_echo(h, _CHAMP, _UID)
    assert body == {"ok": False, "err": rt._UB_NOT_FOUND}


def test_malformed_user_build_answers_a_fixed_404():
    p1, p2 = _patch_user_store([{"id": _UID}], None)
    with p1, p2:
        h = _apply({"champion": _CHAMP, "variant": "userbuild_" + _UID,
                    "mode": "sr"})
    assert h.status == 404
    body = _assert_no_echo(h, _CHAMP, _UID)
    assert body == {"ok": False, "err": rt._UB_MALFORMED}


def test_the_user_build_helper_itself_returns_fixed_texts():
    """The helper's own dict, not only the route body: a later caller that
    forwards it must not get the echo back."""
    p1, p2 = _patch_user_store([], None)
    with p1, p2:
        missing = rt._resolve_user_build(_CHAMP, "userbuild_" + _UID, "sr", None)
    p1, p2 = _patch_user_store([{"id": _UID}], None)
    with p1, p2:
        bad = rt._resolve_user_build(_CHAMP, "userbuild_" + _UID, "sr", None)
    assert missing == {"ok": False, "err": rt._UB_NOT_FOUND}
    assert bad == {"ok": False, "err": rt._UB_MALFORMED}


def test_unknown_variant_from_the_real_resolver_answers_a_fixed_404(caplog):
    """Same-root sibling, through the REAL `coaches.loadout_resolver.resolve`:
    an unknown champion has no variants, so it fails with its own
    `no variant ... for ...` text, which quotes both caller values. The
    route answers a fixed text and logs the raw one."""
    from coaches.loadout_resolver import resolve
    raw = resolve(_CHAMP, _VARIANT, "sr")
    assert raw.get("ok") is False
    assert _CHAMP in raw["err"] and _VARIANT in raw["err"], (
        "precondition: the resolver's own text quotes the caller values; if "
        "it no longer does, this test no longer pins the route scrub")
    with caplog.at_level(logging.INFO, logger=rt.log.name):
        h = _apply({"champion": _CHAMP, "variant": _VARIANT, "mode": "sr"})
    assert h.status == 404
    body = _assert_no_echo(h, _CHAMP, _VARIANT)
    assert body == {"ok": False, "err": rt._VARIANT_NOT_FOUND}
    assert any(_VARIANT in r.getMessage() for r in caplog.records), (
        "the raw resolver text must reach the log, not vanish")


@pytest.mark.parametrize("raw_err", [
    f"no variant {_VARIANT!r} for {_CHAMP!r}",
    f"variant {_VARIANT!r} not allowed in sr",
    f"no build_path {_PATH!r} for {_CHAMP!r}:{_VARIANT!r}",
    "",
    None,
    {"nested": _CHAMP},
])
def test_every_resolver_failure_shape_answers_the_fixed_404(raw_err):
    def _resolved(champ, variant, mode, ov):
        return {"ok": False, "err": raw_err, "champion": _CHAMP,
                "variant": _VARIANT}

    with mock.patch.object(rt, "_resolve_variant", _resolved):
        h = _apply({"champion": _CHAMP, "variant": _VARIANT + ":" + _PATH,
                    "mode": "sr"})
    assert h.status == 404
    body = _assert_no_echo(h, _CHAMP, _VARIANT, _PATH)
    assert body == {"ok": False, "err": rt._VARIANT_NOT_FOUND}


def test_the_fixed_texts_carry_no_format_field():
    for text in (rt._UB_NOT_FOUND, rt._UB_MALFORMED, rt._VARIANT_NOT_FOUND):
        assert isinstance(text, str) and text
        assert "{" not in text and "%" not in text
    assert rt._FIXED_RESOLVE_ERRS == frozenset(
        {rt._UB_NOT_FOUND, rt._UB_MALFORMED})
