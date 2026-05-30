"""DOM grep-guard + ASCII tests for web/js/panels/ds_statcheck.js."""

from __future__ import annotations

import pathlib

_PANEL = (
    pathlib.Path(__file__).resolve().parents[1] / "web" / "js" / "panels" / "ds_statcheck.js"
)


def _src() -> str:
    return _PANEL.read_text(encoding="utf-8")


def test_panel_is_ascii() -> None:
    raw = _PANEL.read_bytes()
    assert all(b < 128 for b in raw), "non-ASCII byte in ds_statcheck.js"


def test_exports_present() -> None:
    s = _src()
    assert "export function renderDsStatcheck" in s
    assert "getDsStatcheckCacheCount" in s
    assert "_resetDsStatcheck" in s
    assert "export const __test" in s


def test_gate_on_my_champion() -> None:
    s = _src()
    assert "my_champion" in s


def test_resolve_champ_names_import() -> None:
    s = _src()
    assert "resolveChampNames" in s
    assert "cc_conditional_pressure.js" in s


def test_block_id_referenced() -> None:
    s = _src()
    # the orchestrator mounts on csv-ds-statcheck; panel references the dss-* mount classes
    assert "dss-" in s


def test_target_knob_inputs_present() -> None:
    s = _src()
    # the sandbox knobs are the TARGET (enemy) stats
    assert 'data-knob="target_armor"' in s
    assert 'data-knob="target_mr"' in s
    assert 'data-knob="target_hp"' in s
    assert 'data-knob="target_bonus_hp"' in s
