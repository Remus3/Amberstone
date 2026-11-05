"""RM-1393: eleven more modules cite their neighbours by symbol.

The remaining non-DS production modules that carried `<file>.py:<line>`
anchors. Several had drifted: `agents/supervisor.py:275` and `app/__init__.py:253`
no longer point at what the prose says, `tests/test_effects_expansion.py:3892`
is a lethality test, not the glyph consumer. The prose now names the symbol; this
guard keeps it that way and pins that every cited symbol still exists. Port
numbers such as `:8889` are not line cites and are left alone. Two files keep
their cite on purpose and are outside this guard: app/_game_lifecycle.py is a
frozen file, and tools/stop_claim_gate.py quotes a line cite as the example of
the pattern it detects.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "agents/agent3_testing/suite/test_round19.py",
    "agents/agent3_testing/suite/test_supervisor.py",
    "coaches/aram_coach.py",
    "core/augment_external_source.py",
    "core/smoothed_rates_101qq.py",
    "dashboard/_wave_timing.py",
    "dashboard/_writers.py",
    "ops/audit/p3c24_b1b_sweep.py",
    "tools/credential_patterns.py",
    "tools/lcu_agent.py",
    "tools/phase_watcher.py",
)

_LINE_CITE = re.compile(r"[A-Za-z0-9_/.]+\.(?:py|js|css|json):\d+")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_file_line_numbers(rel):
    assert _LINE_CITE.findall(_read(rel)) == [], "cite a symbol, not a line number"


@pytest.mark.parametrize("rel", MODULES)
def test_module_stays_ascii_and_lf(rel):
    raw = (ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "``game_ingest.py:203-216``. 170 of the",
        "died at ``agents/supervisor.py:275`` with",
        "Copied from web/js/lib/items_index.js:60-64 (_splitItemList with",
        "(item_build.js:222-226) before rendering.",
        "# core/synergy_external_source.py:135-147 is the twin",
        "(tests/test_smoothed_rates_101qq_lock.py:375), a guard",
        "readout at ``web/js/panels/next.js:16-83`` stays",
        "# app/__init__.py:253. Cycle 28 correction",
        "consumer = tests/test_effects_expansion.py:3892,",
        "`.claude/settings.json:32`) supplies",
        "# Precedent: tools/liveclient_relay.py:41-51.",
    ):
        assert _LINE_CITE.search(old), old
    assert _LINE_CITE.search("relay on :8889 by modes/shared_vision.py") is None


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("agents/agent2_backend/game_ingest.py", "def ingest_game_summary("),
        ("agents/supervisor.py", "_port_available(BIND_HOST, port)"),
        ("agents/supervisor.py", "is already in use"),
        ("web/js/lib/items_index.js", "export function _splitItemList("),
        ("web/js/panels/item_build.js", "_splitItemList(p.item_build, true)"),
        ("web/js/panels/item_build.js", "const pathDedup ="),
        ("core/synergy_external_source.py", "parse_constant=_reject_non_finite"),
        ("tests/test_smoothed_rates_101qq_lock.py", "def test_source_stays_in_the_declared_domain("),
        ("web/js/panels/next.js", "function _renderWaveState("),
        ("app/__init__.py", "def _write_data("),
        ("agents/daemon_slayer/tests/test_effects_expansion.py", "class "),
        ("ops/claude_settings.example.json", "tools/edit_lint_check.py"),
        ("tools/liveclient_relay.py", "logging.FileHandler("),
    ],
)
def test_every_symbol_the_modules_cite_still_exists(rel, needle):
    assert needle in _read(rel), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "rel, name",
    [
        ("agents/agent3_testing/suite/test_round19.py", "``ingest_game_summary`` in agents/agent2_backend/game_ingest.py"),
        ("agents/agent3_testing/suite/test_supervisor.py", "``_port_available`` loop"),
        ("coaches/aram_coach.py", "``_splitItemList`` in web/js/lib/items_index.js"),
        ("coaches/aram_coach.py", "``pathDedup`` filter in web/js/panels/item_build.js"),
        ("core/augment_external_source.py", "``parse_constant=_reject_non_finite`` call in"),
        ("core/smoothed_rates_101qq.py", "``test_source_stays_in_the_declared_domain`` in"),
        ("dashboard/_wave_timing.py", "``_renderWaveState`` in ``web/js/panels/next.js``"),
        ("dashboard/_writers.py", "``_write_data`` in app/__init__.py"),
        ("ops/audit/p3c24_b1b_sweep.py", "agents/daemon_slayer/tests/test_effects_expansion.py"),
        ("tools/credential_patterns.py", "``edit_lint_check`` entry of `.claude/settings.json`"),
        ("tools/lcu_agent.py", "``logging.FileHandler`` setup in tools/liveclient_relay.py"),
        ("tools/phase_watcher.py", "``logging.FileHandler``\n# setup in tools/liveclient_relay.py"),
    ],
)
def test_prose_still_names_the_symbol(rel, name):
    assert name in _read(rel)
