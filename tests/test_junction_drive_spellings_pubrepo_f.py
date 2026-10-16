"""PUBREPO 1f (MAIN ORDER 2026-10-15): the path guard refuses a drive-root
project path in BOTH drive-letter spellings of the junctioned project roots.

On the operator's host several project roots exist twice: a junction on one
drive whose target sits on another. Text can therefore cite one checkout under
either drive letter, so a guard keyed on the spelling `git rev-parse` happens
to return would pass the other spelling silently. MEASURED at this commit, per
guard (the matrix is in the commit body):

* Sibling roots - `tools/sibling_name_sweep.py`. The needle arm's DRIVE shape
  matches any drive letter in either case, one or two separators, either
  slash; the config-free structural arm does too. Both halt a push.
* RC's own root - `tools/credential_patterns.py` class `checkout_path`, run by
  `tools/credential_history_scan.py --pre-push`. The drive is not part of the
  identity, so every drive letter matches. It was ADVISORY (reported, never a
  halt) with the recorded reversal "promote at HEAD count 0"; the HEAD leak
  sweep now counts 0 outside test/fixture paths, so it is a GATE class. The
  sweep's structural arm allowlists RC's own name by design and is not the arm
  for this root.

Two halves:

1. Config-free (runs everywhere, CI included): synthetic roots under two
   synthetic drive letters prove the leak arm halts in every spelling.
2. Per-host: the real roots and drive letters come from the gitignored
   per-host config at run time. Skipped when the config is absent, and NOT
   vacuous when it is present - it must find at least two drive letters.

No drive-rooted literal and no sibling name is spelled in this file: every
probe is assembled at run time, and assertion messages carry slot numbers and
spelling labels only, never a matched literal.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tools import credential_history_scan as chs
from tools import credential_patterns as cp
from tools import sibling_name_sweep as sweep

ROOT = Path(__file__).resolve().parent.parent
_NW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_COLON = ":"
_BS = "\\"
_SEPARATORS = (("bs", _BS), ("fs", "/"), ("dbs", _BS * 2))
_SUBPATH = ("ops", "loop", "x.py")


def _spellings(letters, name):
    """(label, text) for every spelling of ``name`` as a drive-root path.

    Each letter in upper and lower case; single backslash, forward slash and
    the doubled (JSON / Python-escaped) backslash; the bare root and the root
    with a trailing subpath. Labels carry an index, never the letter.
    """
    out = []
    for index, letter in enumerate(sorted({str(x).upper() for x in letters})):
        for case, drive in (("upper", letter.upper()), ("lower", letter.lower())):
            for sep_label, sep in _SEPARATORS:
                head = drive + _COLON + sep + name
                label = f"drive{index}/{case}/{sep_label}"
                out.append((label, head))
                out.append((label + "/sub", head + sep + sep.join(_SUBPATH)))
    return out


def _gate(findings, cls):
    return [f for f in findings if f.pattern_class == cls and not cp.is_advisory(f)]


# --------------------------------------------------------------------------
# 1. config-free: synthetic roots, synthetic drive letters
# --------------------------------------------------------------------------

_SYNTH_LETTERS = ("Q", "Z")
_SYNTH_NAME = "Synth Proj"


def _synth_checkout() -> str:
    return _SYNTH_LETTERS[0] + _COLON + _BS + _SYNTH_NAME


def test_checkout_path_is_a_gate_class_and_user_profile_stays_advisory():
    """The recorded reversal: checkout_path promoted at HEAD count 0. The
    user-profile class keeps its advisory status (MAIN: the home-shape lines
    are placeholders, no change)."""
    assert "checkout_path" in cp.LEAK_PATTERN_CLASSES
    assert "checkout_path" not in cp.ADVISORY_LEAK_CLASSES
    assert "user_profile_path" in cp.ADVISORY_LEAK_CLASSES


def test_synthetic_checkout_root_halts_in_every_drive_spelling():
    variants = cp.checkout_path_variants(_synth_checkout())
    forms = _spellings(_SYNTH_LETTERS, _SYNTH_NAME)
    assert len(forms) == 24
    missed = [
        label
        for label, text in forms
        if not _gate(cp.scan_leaks("see " + text + " here\n", (), variants), "checkout_path")
    ]
    assert missed == [], missed


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, check=True, creationflags=_NW).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "core.autocrlf", "false")
    (r / "a.py").write_text("x = 1\n", encoding="ascii")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    return r


def _commit(r: Path, rel: str, body: str) -> None:
    target = r / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="ascii")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "c")


def _push(r: Path, base: str, checkout_paths) -> int:
    return chs.run_push([["HEAD", "--not", base]], root=r, leak_values=(),
                        checkout_paths=tuple(checkout_paths))


@pytest.mark.parametrize("letter_index", [0, 1])
def test_push_halts_on_either_drive_spelling_of_the_checkout_root(repo, letter_index, capsys):
    letter = _SYNTH_LETTERS[letter_index]
    spelled = letter.lower() + _COLON + "/" + _SYNTH_NAME + "/ops/x.py"
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "docs/NOTES.md", "the file is " + spelled + "\n")
    variants = cp.checkout_path_variants(_synth_checkout())
    rc = _push(repo, base, variants)
    assert rc == chs.EXIT_HALT
    err = capsys.readouterr().err
    assert "class=checkout_path" in err
    assert _SYNTH_NAME not in err


def test_push_still_exempts_the_checkout_root_in_a_test_path(repo):
    spelled = _SYNTH_LETTERS[1] + _COLON + _BS + _SYNTH_NAME + _BS + "x"
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "tests/test_paths.py", "P = " + json.dumps(spelled) + "\n")
    variants = cp.checkout_path_variants(_synth_checkout())
    rc = _push(repo, base, variants)
    assert rc == chs.EXIT_CLEAN


# --------------------------------------------------------------------------
# 2. per-host: the real roots, both drive letters of the junction pairs
# --------------------------------------------------------------------------


def _drive_letter(path_text: str):
    text = str(path_text).strip()
    if len(text) >= 2 and text[1] == _COLON and text[0].isalpha():
        return text[0].upper()
    return None


@pytest.fixture(scope="module")
def host():
    """Roots and drive letters from the gitignored per-host config.

    Drive letters come from every configured root AND from where each existing
    root resolves to, so a junction contributes both its link drive and its
    target drive. RC's own checkout contributes its resolved drive.
    """
    if (os.environ.get("RC_MOON_SYNC_REPOS") or "").strip():
        pytest.skip("RC_MOON_SYNC_REPOS override set; this pin reads the per-host file")
    config_path = sweep.resolve_config_path(ROOT)
    if not config_path.exists():
        pytest.skip("no per-host ops/moon_sync_repos.json on this machine (fresh clone / CI)")
    cfg = sweep.load_config(root=ROOT, env={})
    assert cfg.mode == sweep.MODE_ARMED, cfg.detail
    blob = json.loads(config_path.read_text(encoding="utf-8"))
    paths = [str(p) for p in (blob.get("repos") or [])]
    paths += [str(p) for p in (blob.get("participants") or {}).values()]
    letters = set()
    for raw in paths:
        configured = _drive_letter(raw)
        if configured:
            letters.add(configured)
        if os.path.exists(raw):
            resolved = _drive_letter(os.path.realpath(raw))
            if resolved:
                letters.add(resolved)
    main_tree = sweep.main_working_tree(ROOT) or ROOT
    rc_resolved = main_tree.resolve()
    rc_letter = _drive_letter(str(rc_resolved))
    if rc_letter:
        letters.add(rc_letter)
    return {"cfg": cfg, "letters": letters, "rc_name": rc_resolved.name}


def test_host_pin_is_not_vacuous(host):
    """Config present means the pin must have something to pin."""
    assert len(host["letters"]) >= 2, (
        "the per-host config is present but yields fewer than two drive "
        "letters, so no second spelling was exercised"
    )
    assert len(host["cfg"].names) >= 1
    assert host["rc_name"]


def test_every_sibling_root_halts_the_needle_drive_arm_in_both_spellings(host):
    cfg = host["cfg"]
    needles = sweep.build_needles(cfg)
    sweep.assert_non_vacuous(needles)
    checked = 0
    missed = []
    for slot, name in enumerate(cfg.names):
        for label, text in _spellings(host["letters"], name):
            found = sweep.scan_text(needles, cfg.codes, "see " + text + " here\n",
                                    path="probe.txt", source="TEST", status="A")
            mine = [f for f in found if f.slot == slot]
            if not any(f.shape.startswith(sweep.SHAPE_DRIVE) for f in mine):
                missed.append(f"slot {slot} {label}")
            checked += 1
    assert checked == len(cfg.names) * 12 * len(host["letters"])
    assert missed == [], missed


def test_every_sibling_root_with_a_subpath_halts_the_structural_arm(host):
    """The config-free arm also sees both spellings of a sibling root."""
    missed = []
    for slot, name in enumerate(host["cfg"].names):
        for label, text in _spellings(host["letters"], name):
            if not label.endswith("/sub"):
                continue
            found = sweep.structural_findings("see " + text + " here\n",
                                              path="probe.txt", source="TEST", status="A")
            if not found:
                missed.append(f"slot {slot} {label}")
    assert missed == [], missed


def test_rc_root_halts_the_leak_gate_in_both_spellings(host):
    checkout_paths = chs.checkout_leak_paths(ROOT)
    assert checkout_paths, "no checkout spelling resolved for this tree"
    forms = _spellings(host["letters"], host["rc_name"])
    assert len(forms) == 12 * len(host["letters"])
    missed = [
        label
        for label, text in forms
        if not _gate(cp.scan_leaks("see " + text + " here\n", (), checkout_paths),
                     "checkout_path")
    ]
    assert missed == [], missed


def test_a_push_adding_the_rc_root_under_any_host_drive_letter_halts(host, repo, capsys):
    checkout_paths = chs.checkout_leak_paths(ROOT)
    for index, letter in enumerate(sorted(host["letters"])):
        base = _git(repo, "rev-parse", "HEAD")
        spelled = letter + _COLON + _BS + host["rc_name"] + _BS + "ops"
        _commit(repo, f"docs/N{index}.md", "cd " + spelled + "\n")
        # Bound to a local first: asserting on the call directly makes pytest
        # render its arguments, which are this host's real checkout spellings.
        rc = _push(repo, base, checkout_paths)
        assert rc == chs.EXIT_HALT, f"drive{index}"
        err = capsys.readouterr().err
        assert "class=checkout_path" in err
        assert host["rc_name"] not in err
