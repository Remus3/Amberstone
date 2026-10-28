"""Guard: cast_propensity.py cites its consumers by symbol, not line (RM-1051).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring and
``propensity_adjusted_dps_delta`` cited ``ability_dps.py:1220`` /
``:1252`` / ``:1261``, ``dps.py:1023`` and ``hps.py:679``. The three
ability_dps cites were true at the 1.244.0 landing (d6894db3d): the
``(form.damage_type or "MAGIC").upper()`` fallback, the measured
``get_spell_casts_per_sec`` lookup and ``dps = post_mit * measured``, all
inside ``compute_ability_dps``. They now sit at :1388 / :1420 / :1429, and the
old lines hold the damage-amp and LDR comments. ``dps.py:1023`` and
``hps.py:679`` were copied from the RM-98 spec (4c76993e2, 2026-07-19), where
they named the Malignance ``get_ult_casts_per_sec`` lookup in ``compute_dps``
and the ``ability_hps_total`` fold in ``compute_hps``; both had already moved
by the landing. A line cite into an engine file other commits keep editing
resolves to SOME line forever, so it never fails loudly.

Scope: cast_propensity.py only. The other tracked .py cites into
ability_dps.py / dps.py / hps.py are a separate, wider sweep.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
CAST_PROPENSITY = DS / "cast_propensity.py"

# ``ability_dps.py:1261``, ``dps.py:1023``, ``hps.py:679``; the leading
# boundary keeps ``onhit_dps.py`` (RM-1050's guard) out of this one.
_LINE_CITE = re.compile(r"(?<![A-Za-z_])(?:ability_dps|dps|hps)\.py:\d")

# The symbols the replacement prose names, per file. A rename leaves the prose
# stale exactly as a moved line does, so pin them.
_CITED_SYMBOLS = {
    "ability_dps.py": (
        "def compute_ability_dps(",
        'dt = (form.damage_type or "MAGIC").upper()',
        "measured = get_spell_casts_per_sec(resolved.champion_name, key, mode)",
        "dps = post_mit * measured",
        "casts_per_sec=measured,",
    ),
    "dps.py": (
        "def compute_dps(",
        "ult_casts_per_sec = get_ult_casts_per_sec(resolved.champion_name, mode)",
    ),
    "hps.py": (
        "def compute_hps(",
        "total = direct + buff_credit + ability_hps_total * ability_hps_amp_mult",
    ),
}

_NAMED_IN_PROSE = (
    "compute_ability_dps",
    "compute_dps",
    "get_ult_casts_per_sec",
    "compute_hps",
    "ability_hps_total",
)


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "``ability_dps.py:1261``",
        "(``ability_dps.py:1220`` - ...)",
        "``dps.py:1023`` (Malignance ult rate)",
        "``hps.py:679``",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "onhit_dps.py:494",
        "ability_dps.py",
        "ability_dps.compute_ability_dps",
        "SPEC:109-114",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_number_cites_into_engine_consumers():
    text = CAST_PROPENSITY.read_text(encoding="utf-8")
    hits = [
        f"cast_propensity.py:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_prose_names_the_consumer_symbols():
    text = CAST_PROPENSITY.read_text(encoding="utf-8")
    missing = [name for name in _NAMED_IN_PROSE if name not in text]
    assert not missing, missing


def test_cited_symbols_still_exist():
    missing = []
    for fname, needles in _CITED_SYMBOLS.items():
        src = (DS / fname).read_text(encoding="utf-8")
        missing.extend(f"{fname}: {n}" for n in needles if n not in src)
    assert not missing, missing
