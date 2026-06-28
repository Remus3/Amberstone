"""
tests/snapshot_panels/test_render_dedup_reshow.py

Regression guard for a SILENT RENDER-GATE class surfaced by the R27 broader
shipped-panel audit (the follow-on to the R26 ds_statcheck dead-panel fix).

The three ctx-driven ACTIVE-MATCH panels - spike_markers / spike_curve /
draft_elo - each dedup their render by a content SIGNATURE: the renderer
early-returns when the new sig equals the last-stamped sig, leaving the DOM
untouched. That is correct ONLY while the renderer is the sole authority over
the mount's innerHTML.

But active_match.js drives them through outer `_render*FromCtx` HIDE paths
that clobber `mount.innerHTML = ""` directly (e.g. active_match.js:1062-1063
for spike-markers) WITHOUT going through the renderer - so the renderer's
stamped sig no longer reflects the (now-empty) DOM. After a transient
liveclient dropout (champion briefly absent -> hide path runs) followed by a
re-show with IDENTICAL data, the sig-dedup early-returns and the cleared
innerHTML is never repainted: the panel renders VISIBLE-BUT-EMPTY on the
in-game overlay until the next level / item change moves the signature.

Root cause = the dedup guard assumes its DOM still matches the stamped sig.
Fix = also require the mount's innerHTML to be non-empty before short-
circuiting, so an externally-cleared mount always repaints. This pins that
invariant per panel: render content -> simulate the outer clear -> re-render
the SAME payload -> the mount must repaint (non-empty) and stay shown.

RED before the fix (re-render early-returns, innerHTML stays "").
"""
from pathlib import Path

# ---- minimal content payloads (each reaches the renderer's CONTENT path) ----

_SPM_PAYLOAD = {
    "ok": True, "champion": "Jinx", "level": 11,
    "markers": [
        {"kind": "level", "threshold": 6, "label": "R unlock",
         "crossed": True, "next": False},
        {"kind": "level", "threshold": 11, "label": "R rank 2",
         "crossed": False, "next": True},
        {"kind": "item", "threshold": 1, "label": "1st item",
         "crossed": True, "next": False},
    ],
    "next": {"kind": "level", "threshold": 11, "label": "R rank 2"},
    "count": 3,
}

_DE_PAYLOAD = {
    "ok": True, "predicted_wr": 0.62, "team_score": 5,
    "sample": {"min_solo": 40, "min_pair": 12}, "top_contributions": [],
}


def _new_page(mock_server, pw_browser, payload):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=sr#active-match",
        wait_until="domcontentloaded", timeout=15_000,
    )
    return ctx, page, errors


def _run(page, module_path, reset_name, mount_id, payload):
    """Bind payload P into page scope, then drive the reshow sequence."""
    return page.evaluate(
        """async ({modulePath, resetName, mountId, P, kind}) => {
          const m = await import(modulePath);
          if (resetName && m[resetName]) m[resetName]();
          const el = document.getElementById(mountId);
          const call = () => {
            if (kind === 'spm') m.renderSpikeMarkers(el, P);
            else if (kind === 'curve') m.renderSpikeCurve(
              el,
              [{minute:0,power:10},{minute:1,power:20},{minute:2,power:30}],
              [{minute:0,power:8},{minute:1,power:18},{minute:2,power:26}],
              null, 5, {});
            else if (kind === 'de') m.renderDraftElo(el, P);
          };
          call();
          const firstLen = el.innerHTML.length;
          el.style.display = 'none';
          el.innerHTML = '';        // outer hide-path clobber (no renderer)
          el.style.display = '';
          call();                   // re-show, identical data
          return { firstLen, reshowLen: el.innerHTML.length, hidden: el.hidden };
        }""",
        {"modulePath": module_path, "resetName": reset_name,
         "mountId": mount_id, "P": payload, "kind": {
             "spike_markers.js": "spm", "spike_curve.js": "curve",
             "draft_elo.js": "de"}[module_path.split("/")[-1]]},
    )


def test_spike_markers_repaints_after_external_clear(mock_server, pw_browser):
    ctx, page, errors = _new_page(mock_server, pw_browser, _SPM_PAYLOAD)
    try:
        r = _run(page, "/js/panels/spike_markers.js", "_resetSpikeMarkers",
                 "am-spike-markers", _SPM_PAYLOAD)
        assert r["firstLen"] > 0, "spike-markers did not render content initially"
        assert r["reshowLen"] > 0, (
            "spike-markers stayed EMPTY after an external clear + identical-data "
            "re-render (sig-dedup desync)"
        )
        assert r["hidden"] is False, "spike-markers shown but empty (the bug shape)"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_spike_curve_repaints_after_external_clear(mock_server, pw_browser):
    ctx, page, errors = _new_page(mock_server, pw_browser, {})
    try:
        r = _run(page, "/js/panels/spike_curve.js", "_resetSpikeCurve",
                 "am-spike-curve", {})
        assert r["firstLen"] > 0, "spike-curve did not render content initially"
        assert r["reshowLen"] > 0, (
            "spike-curve stayed EMPTY after an external clear + identical-data "
            "re-render (sig-dedup desync)"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_draft_elo_repaints_after_external_clear(mock_server, pw_browser):
    ctx, page, errors = _new_page(mock_server, pw_browser, _DE_PAYLOAD)
    try:
        r = _run(page, "/js/panels/draft_elo.js", "_resetDraftElo",
                 "am-draft-elo", _DE_PAYLOAD)
        assert r["firstLen"] > 0, "draft-elo did not render content initially"
        assert r["reshowLen"] > 0, (
            "draft-elo stayed EMPTY after an external clear + identical-data "
            "re-render (sig-dedup desync)"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_BUILD_PAYLOAD = {
    "p": {
        "champion": "Jinx", "level": 11,
        "daemon_slayer_picks": [
            {"id": 3031, "name": "Infinity Edge"},
            {"id": 3094, "name": "Rapid Firecannon"},
        ],
    },
    "ctx": {"mode": "sr"},
    "lc": None,
    "ownedIds": [],
}


def test_build_body_repaints_after_external_clear(mock_server, pw_browser):
    """active_match build pane (flicker fix 2026-06-28): the sig-dedup added to
    _renderAmBuildBody must carry the R27 reshow guard - an external innerHTML
    clear with identical data must still repaint, not stay visible-but-empty."""
    ctx, page, errors = _new_page(mock_server, pw_browser, {})
    try:
        r = page.evaluate(
            """async (P) => {
              const m = await import('/js/panels/active_match.js');
              const el = document.getElementById('am-build-body');
              const call = () => m._renderAmBuildBody(el, P.p, P.ctx, P.lc, P.ownedIds);
              call();
              const firstLen = el.innerHTML.length;
              el.style.display = 'none';
              el.innerHTML = '';        // outer hide-path clobber (no renderer)
              el.style.display = '';
              call();                   // re-show, identical data
              return { firstLen, reshowLen: el.innerHTML.length };
            }""",
            _BUILD_PAYLOAD,
        )
        assert r["firstLen"] > 0, "build body did not render content initially"
        assert r["reshowLen"] > 0, (
            "build body stayed EMPTY after an external clear + identical-data "
            "re-render (sig-dedup desync - the flicker fix's reshow guard)"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
