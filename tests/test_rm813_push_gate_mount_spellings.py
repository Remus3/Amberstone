"""RM-813: push-gate spelling residuals left by RM-780.

(a) `tools/sibling_name_sweep.py`. A NARROWED slot gives up its bare arm and
    keeps the DRIVE and URL arms, but the DRIVE arm read only the drive-letter
    spelling of a checkout root. The same root spelled as a WSL mount
    (`/mnt/<x>/<name>`), a POSIX-shell drive (`/<x>/<name>`) or a WSL UNC path
    (`<lead>wsl$<sep><distro><sep>mnt<sep><x><sep><name>`, either host, the
    Win32 `?` long-path step or the `.` device step) passed the push. A
    non-narrowed slot was covered by its bare arm, which is why only the
    narrowed slots on a host were exposed.
(b) `tools/credential_patterns.py`. The WSL UNC lead accepted the long-path
    step `?<sep>UNC<sep>` but not the Win32 DEVICE step `.<sep>UNC<sep>`, so
    `\\\\.\\UNC\\wsl$\\<distro>\\mnt\\<x>\\<rest>` with single separators was
    not read as drive-rooted (the doubled-separator form was caught only by
    accident: its inner `\\\\wsl$` is itself a two-separator lead).

Both fixes only ADD alternatives (monotone by construction); the "ARMED WITH
A MEASURED ESCAPE RATE ABOVE ZERO" phrasing stays true - this closes named
spellings, not the class.

Every literal is invented and assembled at run time: no drive-rooted literal,
no sibling name and no real distro appears in this file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import credential_patterns as cp
from tools import sibling_name_sweep as sweep

_BS = "\\"
_D = "C:" + _BS
_DISTRO = "Synth-Distro"
_HOSTS = ("wsl$", "wsl.localhost")

_NARROW_ONE = "Grommet"
_NARROW_TWO = "Tindal Sprocket"
_FULL_NAME = "Widget Foundry"


@pytest.fixture()
def narrow(tmp_path: Path):
    root = tmp_path / "fakeroot"
    (root / "ops").mkdir(parents=True)
    blob = {
        "repos": [_D + _NARROW_ONE, _D + _NARROW_TWO, _D + _FULL_NAME],
        "participants": {"GRM": _D + _NARROW_ONE},
        "narrowed_names": [_NARROW_ONE, _NARROW_TWO],
    }
    (root / "ops" / "moon_sync_repos.json").write_text(
        json.dumps(blob), encoding="utf-8"
    )
    cfg = sweep.load_config(root=root, env={})
    needles = sweep.build_needles(cfg)
    assert {n.name for n in needles if n.narrowed} == {_NARROW_ONE, _NARROW_TWO}
    return cfg, needles


def _findings(narrow, text: str):
    cfg, needles = narrow
    return sweep.scan_text(
        needles, cfg.codes, text, path="probe.txt", source="TEST", status="A"
    )


def _slots(narrow, text: str) -> set:
    cfg, needles = narrow
    names = {n.slot: n.name for n in needles}
    return {names[f.slot] for f in _findings(narrow, text)}


def _unc(host: str, sep: str, *parts: str, step: str = "") -> str:
    """`<sep><sep>[step<sep>UNC<sep>]host<sep>distro<sep>parts...`."""
    lead = sep * 2 + (step + sep + "UNC" + sep if step else "")
    return lead + sep.join((host, _DISTRO) + tuple(parts))


def _mount_spellings(name: str):
    """(label, text) for every mount spelling of a drive-root checkout."""
    out = [
        ("wsl-mount", "/" + "/".join(("mnt", "e", name, "ops"))),
        ("wsl-mount-root", "/" + "/".join(("mnt", "E", name))),
        ("posix-drive", "/" + "/".join(("e", name, "ops"))),
        ("posix-drive-upper", "/" + "/".join(("E", name))),
    ]
    for host in _HOSTS:
        for sep_label, sep in (("bs", _BS), ("dbs", _BS * 2), ("fs", "/")):
            for step in ("", "?", "."):
                label = f"unc/{host}/{sep_label}/step{step or '-'}"
                out.append((label, _unc(host, sep, "mnt", "e", name, "ops", step=step)))
    return out


_FAMILIES = {
    "one-word": _NARROW_ONE,
    "spaced": _NARROW_TWO,
    "hyphen": "-".join(_NARROW_TWO.split()),
    "under": "_".join(_NARROW_TWO.split()),
    "concat": "".join(_NARROW_TWO.split()),
    "pct20": "%20".join(_NARROW_TWO.split()),
}


# --- (a) every mount spelling of a NARROWED slot's root halts --------------
@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_a_narrowed_slot_halts_on_every_mount_spelling_of_its_root(narrow, family):
    spelled = _FAMILIES[family]
    expected = _NARROW_ONE if family == "one-word" else _NARROW_TWO
    missed = [
        label
        for label, path in _mount_spellings(spelled)
        if expected not in _slots(narrow, "see " + path + " here\n")
    ]
    assert missed == [], missed


def test_a_mount_spelling_halts_with_the_drive_shape(narrow):
    """The hit is the DRIVE arm (the one a narrowed slot keeps), not an
    accident of some other arm."""
    text = "cd " + "/" + "/".join(("mnt", "d", _NARROW_ONE)) + "\n"
    shapes = {f.shape.split("/", 1)[0] for f in _findings(narrow, text)}
    assert shapes == {sweep.SHAPE_DRIVE}


def test_a_mount_spelling_split_across_a_wrapped_comment_halts(narrow):
    """The TIGHT view's drive arm takes the mount heads too. Cut MID-TOKEN so
    the space view cannot see it, after `path:` so the tight text keeps a
    non-word char before the head (the idiom of the drive-letter case in
    tests/test_sibling_name_sweep.py)."""
    whole = "".join(_NARROW_TWO.split())
    head, tail = whole[:5], whole[5:]
    text = "path: " + "/" + "/".join(("mnt", "d", head)) + "\n#   " + tail + "/ops\n"
    found = _findings(narrow, text)
    assert any(
        f.view == sweep.VIEW_TIGHT and f.shape.startswith(sweep.SHAPE_DRIVE)
        for f in found
    ), [(f.shape, f.view) for f in found]


def test_a_non_narrowed_slot_still_halts_on_a_mount_spelling(narrow):
    """Regression control: full-strength slots keep halting (bare arm or drive)."""
    text = "see " + "/" + "/".join(("mnt", "e", "Widget Foundry")) + "\n"
    assert _FULL_NAME in _slots(narrow, text)


# --- (a) the widening never widens the NAME or the drive -------------------
@pytest.mark.parametrize(
    "label,text",
    [
        ("bare-prose", "a " + _NARROW_ONE + " sits here"),
        ("two-letter-mount", "/" + "/".join(("mnt", "qz", _NARROW_ONE))),
        ("word-mount", "/" + "/".join(("mnt", "data", _NARROW_ONE))),
        ("url-segment", "https://example.org/" + "/".join(("e", _NARROW_ONE))),
        ("path-inside-path", "/" + "/".join(("srv", "e", _NARROW_ONE))),
        ("longer-name", "/" + "/".join(("mnt", "e", _NARROW_ONE + "X"))),
        ("longer-name-posix", "/" + "/".join(("e", _NARROW_ONE + "s"))),
        ("unc-not-mount", _unc("wsl$", _BS, "home", _NARROW_ONE)),
        ("unc-word-mount", _unc("wsl$", _BS, "mnt", "qz", _NARROW_ONE)),
    ],
)
def test_a_narrowed_slot_does_not_halt_off_a_drive_root(narrow, label, text):
    assert _findings(narrow, "x " + text + " y\n") == [], label


def test_every_needle_stays_non_vacuous(narrow):
    sweep.assert_non_vacuous(narrow[1])


def test_the_two_wsl_unc_leads_are_one_spelling():
    """Same root cause, two gates: the sweep's lead and the leak scanner's
    lead must read the same UNC spellings, so a fix to one cannot leave the
    other behind."""
    assert sweep._WSL_UNC_LEAD == cp._WSL_UNC_LEAD


# --- (b) the Win32 device step of the WSL UNC lead -------------------------
_SYNTH_NAME = "Synth Checkout Root"


def _synth_checkout() -> str:
    return "Q" + ":" + _BS + _SYNTH_NAME


def _gate(findings, cls):
    return [f for f in findings if f.pattern_class == cls]


@pytest.mark.parametrize("sep", [_BS, "/"], ids=["bs", "fs"])
@pytest.mark.parametrize("host", _HOSTS, ids=["wsl-dollar", "wsl-localhost"])
def test_the_device_unc_step_of_the_wsl_spelling_halts(host, sep):
    variants = cp.checkout_path_variants(_synth_checkout())
    text = "see " + _unc(host, sep, "mnt", "z", _SYNTH_NAME, "ops", step=".") + " here\n"
    assert _gate(cp.scan_leaks(text, (), variants), "checkout_path")


def test_the_device_unc_step_halts_a_posix_checkout_root():
    """Sibling: the drive-free head takes the same optional lead."""
    variants = cp.checkout_path_variants("/" + "/".join(("srv", "synth", _SYNTH_NAME)))
    text = "see " + _unc("wsl$", _BS, "srv", "synth", _SYNTH_NAME, step=".") + "\n"
    assert _gate(cp.scan_leaks(text, (), variants), "checkout_path")


def test_the_device_unc_step_is_read_by_the_profile_class():
    """Sibling: the advisory profile class shares the lead."""
    text = "see " + _unc("wsl$", _BS, "mnt", "c", "Users", "synthacct", step=".") + "\n"
    assert _gate(cp.scan_leaks(text, (), ()), "user_profile_path")


def test_the_device_step_never_widens_the_root_identity():
    variants = cp.checkout_path_variants(_synth_checkout())
    longer = "see " + _unc("wsl$", _BS, "mnt", "z", _SYNTH_NAME + "X", step=".") + "\n"
    other_step = "see " + _unc("wsl$", _BS, "mnt", "z", _SYNTH_NAME, step="x") + "\n"
    assert _gate(cp.scan_leaks(longer, (), variants), "checkout_path") == []
    assert _gate(cp.scan_leaks(other_step, (), variants), "checkout_path") == []
