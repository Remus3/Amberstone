"""The structural arm's placeholder allowlist never shadows a LOADED slot name.

THE GAP (the live-config junction pin went red, 2026-10-22)
-----------------------------------------------------------
``tests/test_junction_drive_spellings_pubrepo_f.py`` pins that the structural
arm sees a sub-path drive spelling of every configured sibling root. It went
red on every such spelling of ONE configured root. Measured cause, in
``tools/sibling_name_sweep.py`` ``structural_findings``: the arm is config-free
and subtracts a placeholder allowlist (``_ALLOW_SEGMENTS`` / ``_ALLOW_PATTERNS``),
and that root's basename is matched by an allowlist placeholder. A config-free
allowlist cannot tell a fixture root from a configured checkout that happens to
share its spelling, so the arm skipped it. Not the cause, each measured:
narrowing (it only drops ``build_needles``' bare arm, and the structural arm
never sees a slot), the slot KIND (same), a missing drive root (the slot is a
full path leaf).

In ARMED mode the needle DRIVE arm still halted every one of those spellings,
so the push verdict was HALT. What that slot had lost was the SECOND,
independent arm - the design keeps two so one arm's blind spot is not a leak.

THE FIX
-------
``structural_findings(..., slot_names=cfg.names)``: a drive-rooted first
segment that starts with a loaded slot name (any S4 spelling, right-edged) is
never subtracted by the allowlist. Every ARMED gate path passes the loaded
names (``_run_scan``, ``core/operator_push.sweep_refusal``). The allowlist
itself is unchanged, so the arm is no wider for any word that is not a loaded
slot, and the config-free call (DEGRADED, CI) is unchanged.

DECLARED RESIDUAL: with no per-host config the structural arm is still blind to
a sibling whose basename an allowlist placeholder matches. The sweep stays
ARMED WITH A MEASURED ESCAPE RATE ABOVE ZERO.

Synthetic placeholders only, chosen from the allowlist's own tracked entries;
every drive prefix is assembled at run time, so this file never trips the arm.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# HARD import: an absent gate must not read as a green run.
from tools import sibling_name_sweep as sweep  # noqa: E402

_COLON = ":"
_BS = "\\"
_SEPARATORS = (("bs", _BS), ("fs", "/"), ("dbs", _BS * 2))
_LETTERS = ("Q", "Z")
_SUBPATH = ("ops", "loop", "x.py")

# Each basename is matched by a DIFFERENT allowlist entry, so the fix is proven
# against every entry class rather than one word: a fixture-root alternative, a
# second one, a placeholder-prefix pattern (a whole two-word name), a leading
# allowlisted word under a two-word name, an RC-scaffolding pattern, and a
# segment-set entry.
_SHADOWED = ("repo", "Bin", "Example Hub", "Repo Forge", "rc-forge", "temp")


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("RC_MOON_SYNC_REPOS", raising=False)
    monkeypatch.delenv("RC_MOON_SYNC_NARROWED_NAMES", raising=False)
    monkeypatch.delenv("RC_SIBLING_SWEEP_BYPASS", raising=False)
    monkeypatch.setenv("RC_SIBLING_SWEEP_RUN_LOG", str(tmp_path / "runlog" / "runs.jsonl"))


def _spellings(name: str):
    """(label, text) for every sub-path drive spelling of ``name``."""
    out = []
    for index, letter in enumerate(_LETTERS):
        for case, drive in (("upper", letter.upper()), ("lower", letter.lower())):
            for sep_label, sep in _SEPARATORS:
                text = drive + _COLON + sep + name + sep + sep.join(_SUBPATH)
                out.append((f"drive{index}/{case}/{sep_label}", "see " + text + " here\n"))
    return out


def _structural(text: str, **kw):
    return sweep.structural_findings(text, path="probe.txt", source="TEST", status="A", **kw)


def test_every_synthetic_basename_is_really_shadowed_config_free():
    """The control: each name IS subtracted by the allowlist without a config,
    so the cases below exercise the gap, not an ordinary unknown root."""
    leaked = [name for name in _SHADOWED for _, text in _spellings(name) if _structural(text)]
    assert leaked == []


@pytest.mark.parametrize("name", _SHADOWED)
def test_a_loaded_slot_name_is_never_shadowed_by_the_allowlist(name):
    missed = [label for label, text in _spellings(name)
              if not _structural(text, slot_names=(name,))]
    assert missed == [], missed


def test_the_allowlist_is_unchanged_for_a_word_that_is_not_a_loaded_slot():
    """Not wider: a multi-word slot does not un-allowlist its first word alone,
    and an unrelated allowlisted root stays allowed beside a loaded slot."""
    d = "Q" + _COLON + _BS
    assert _structural("see " + d + "repo" + _BS + "ops\n", slot_names=("Repo Forge",)) == []
    assert _structural("see " + d + "logs" + _BS + "x\n", slot_names=("Bin",)) == []
    assert _structural("see " + d + "Repo Forge" + _BS + "ops\n", slot_names=("Repo Forge",))


def test_a_slot_is_right_edged_like_the_needle_drive_arm():
    """A longer word that merely starts with the slot spelling is not the slot,
    and it is an unknown root anyway, so it fires on its own merit."""
    d = "Q" + _COLON + _BS
    assert _structural("see " + d + "Bin" + _BS + "x\n", slot_names=("Bin",))
    assert _structural("see " + d + "Bin)" + " and more\n", slot_names=("Bin",))
    # Not a slot, not on the allowlist: the ordinary config-free finding.
    assert _structural("see " + d + "Binder" + _BS + "x\n", slot_names=("Bin",))


def test_the_word_cap_never_subtracts_a_loaded_slot():
    """Sibling skip of the same class: the greedy capture can run a slot root
    into prose past the word cap, which the config-free arm drops as a sentence."""
    text = "see " + "Q" + _COLON + _BS + "Bin and then some more words" + _BS + "x\n"
    assert _structural(text) == []
    assert _structural(text, slot_names=("Bin",))


# --------------------------------------------------------------------------
# Through the ARMED gate path, every slot kind, narrowed or not
# --------------------------------------------------------------------------
def _cfg(tmp_path: Path, narrowed: bool):
    d = "C" + _COLON + _BS
    blob = {
        "repos": [d + "repo"],
        "participants": {"QA": d + "Bin"},
        "retired": {"QB": [d + "Example Hub", "Repo Forge"]},
        "supervisor": {"QC": d + "rc-forge"},
        "narrowed_names": list(_SHADOWED) if narrowed else [],
    }
    root = tmp_path / "cfgroot"
    (root / "ops").mkdir(parents=True)
    (root / "ops" / "moon_sync_repos.json").write_text(json.dumps(blob), encoding="ascii")
    cfg = sweep.load_config(root=root, env={})
    assert cfg.mode == sweep.MODE_ARMED
    assert set(cfg.names) == set(_SHADOWED) - {"temp"}
    assert len(cfg.narrowed_names) == (len(cfg.names) if narrowed else 0)
    return cfg


@pytest.mark.parametrize("narrowed", [False, True], ids=["full", "narrowed"])
def test_the_gate_scan_runs_the_structural_arm_with_the_loaded_names(
    tmp_path, monkeypatch, narrowed
):
    """``_run_scan`` with the NEEDLE arm stubbed out, so the structural arm is
    measured alone: every slot kind keeps its second arm, and narrowing (which
    only drops the bare-word arm) changes nothing here."""
    cfg = _cfg(tmp_path, narrowed)
    monkeypatch.setattr(sweep, "scan_text", lambda *a, **k: [])
    missed = []
    for slot, name in enumerate(cfg.names):
        for label, text in _spellings(name):
            blob = sweep.Blob(source="TEST", path="probe.txt", status="A", text=text)
            found = sweep._run_scan(cfg, [blob], sweep.ScanStats())
            if not any(f.shape == sweep.SHAPE_STRUCTURAL for f in found):
                missed.append(f"slot {slot} {label}")
    assert missed == [], missed


def test_the_operator_push_gate_runs_the_structural_arm_with_the_loaded_names(
    tmp_path, monkeypatch
):
    from core import operator_push  # noqa: PLC0415

    _cfg(tmp_path, narrowed=True)
    monkeypatch.setattr(sweep, "scan_text", lambda *a, **k: [])
    text = _spellings("rc-forge")[0][1]
    refusal = operator_push.sweep_refusal(text, root=tmp_path / "cfgroot")
    assert refusal and "refused" in refusal
    assert "rc-forge" not in refusal
