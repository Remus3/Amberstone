"""RM-876 (a): the config-free STRUCTURAL arm reads every mount spelling of a
drive root, not only the drive-letter one.

`tools/sibling_name_sweep.py` `structural_findings` is the arm that keeps the
push gate non-inert in CI and in a fresh clone (no per-host config, so no
needles). Its regex matched only `<letter>:<sep><segment>`, so an UNDECLARED
project cited as a WSL mount (`/mnt/<x>/<name>`), a POSIX-shell drive
(`/<x>/<name>`) or a WSL UNC path (`<lead>wsl$<sep><distro><sep>mnt<sep><x>
<sep><name>`, either host, the `?` long-path or `.` device step) was not a
finding. RM-813 already gave the needle DRIVE arm those heads through
`_DRIVE_HEAD`; the structural arm now takes the same alternatives, pinned
below, so the two arms cannot drift apart again - all but ONE.

The POSIX-shell drive `/<x>/` is left out on a measurement: the real-tree
differential (11152 blobs, config-free and ARMED alike) lost 0 findings and
gained 21, every one from that head and every one false (base64 in an inlined
image, URL paths, test paths); the mount and UNC heads gained 0. With no name
to anchor it, `/<x>/<segment>` is noise, so an undeclared project cited only
that way is a DECLARED RESIDUAL of this arm (a loaded slot still halts on it
through the needle DRIVE arm). Its own test below keeps that a visible choice.

The allowlist, the C-escape class and the word cap still apply to the new
heads. "ARMED WITH A MEASURED ESCAPE RATE ABOVE ZERO" stays.

Every literal is invented and assembled at run time: no drive-rooted literal,
no sibling name and no real distro appears in this file.
"""
from __future__ import annotations

import pytest

from tools import sibling_name_sweep as sweep

_BS = "\\"
_DISTRO = "Synth-Distro"
_HOSTS = ("wsl$", "wsl.localhost")
_UNKNOWN = "Zorblax Works"


def _found(text: str, **kw):
    return sweep.structural_findings(
        text, path="probe.txt", source="TEST", status="A", **kw
    )


def _unc(host: str, sep: str, *parts: str, step: str = "") -> str:
    """`<sep><sep>[step<sep>UNC<sep>]host<sep>distro<sep>parts...`."""
    lead = sep * 2 + (step + sep + "UNC" + sep if step else "")
    return lead + sep.join((host, _DISTRO) + tuple(parts))


def _posix_drive_spellings(name: str):
    return [
        ("posix-drive", "/" + "/".join(("e", name, "ops"))),
        ("posix-drive-upper", "/" + "/".join(("E", name))),
    ]


def _mount_spellings(name: str):
    """(label, text) for every spelling of a drive root the arm reads, other
    than the drive-letter one."""
    out = [
        ("wsl-mount", "/" + "/".join(("mnt", "e", name, "ops"))),
        ("wsl-mount-upper", "/" + "/".join(("mnt", "E", name))),
    ]
    for host in _HOSTS:
        for sep_label, sep in (("bs", _BS), ("dbs", _BS * 2), ("fs", "/")):
            for step in ("", "?", "."):
                label = f"unc/{host}/{sep_label}/step{step or '-'}"
                out.append((label, _unc(host, sep, "mnt", "e", name, "ops", step=step)))
    return out


_SPELLINGS = _mount_spellings(_UNKNOWN)


@pytest.mark.parametrize("label,path", _SPELLINGS, ids=[s[0] for s in _SPELLINGS])
def test_an_undeclared_project_on_a_mount_spelling_is_a_structural_finding(label, path):
    # The path ends the line: prose after a separator-less tail would be read
    # into the segment and trip the 3-word cap, as for the drive-letter form.
    found = _found("see " + path + "\n")
    assert [f.shape for f in found] == [sweep.SHAPE_STRUCTURAL], label
    assert _UNKNOWN.split(maxsplit=1)[0] in found[0].literal, label


def test_the_drive_letter_spelling_still_fires():
    """Regression control: the widening only ADDS heads."""
    found = _found("see " + "Q" + ":" + _BS + _UNKNOWN + _BS + "ops\n")
    assert [f.shape for f in found] == [sweep.SHAPE_STRUCTURAL]


def test_the_structural_head_is_the_needle_drive_head_less_the_posix_drive():
    """One set of alternatives for both arms: a spelling the DRIVE arm reads,
    the config-free arm reads too, except the one measured-noisy head. A
    future widening of the DRIVE head reaches this arm with no second edit."""
    assert sweep._POSIX_DRIVE in sweep._DRIVE_HEAD_PARTS
    assert sweep._STRUCTURAL_HEAD_PARTS == tuple(
        p for p in sweep._DRIVE_HEAD_PARTS if p != sweep._POSIX_DRIVE
    )
    assert sweep._DRIVE_HEAD == (
        "(?<![A-Za-z0-9_])(?:" + "|".join(sweep._DRIVE_HEAD_PARTS) + ")"
    )
    assert len(sweep._STRUCTURAL_RES) == len(sweep._STRUCTURAL_HEAD_PARTS)
    for rx, part in zip(sweep._STRUCTURAL_RES, sweep._STRUCTURAL_HEAD_PARTS):
        assert rx.pattern.startswith("(?<![A-Za-z0-9_])(?:" + part + ")")
    assert sweep.STRUCTURAL_RE is sweep._STRUCTURAL_RES[0]
    for rx in sweep._STRUCTURAL_RES[1:]:
        assert rx.flags & sweep.re.I and rx.flags & sweep.re.A, rx.pattern


def test_the_drive_letter_pass_carries_no_flag():
    """`re.I` alone widens `[A-Za-z]` to four non-ASCII letters, which moved
    the drive pass's edges and lost old findings."""
    assert sweep.STRUCTURAL_RE.flags == sweep.re.compile("").flags


@pytest.mark.parametrize("cp", [0x130, 0x131, 0x17F, 0x212A])
def test_a_non_ascii_letter_never_moves_a_drive_letter_edge(cp):
    """Each case was a finding before RM-876 and must stay one (the left
    edge), and must not swallow the letter into the segment (the right edge)."""
    left = _found(chr(cp) + "Q:" + _BS + "Zorblax\n")
    assert [f.literal for f in left] == ["Q:" + _BS + "Zorblax"]
    right = _found("Q:" + _BS + "Zorblax" + chr(cp) + " a b c\n")
    assert [f.literal for f in right] == ["Q:" + _BS + "Zorblax"]
    assert _found(chr(cp) + ":" + _BS + "Zorblax\n") == []


def test_the_drive_letter_pass_is_the_arms_original_regex():
    """Monotone by construction: the first pass is the pre-RM-876 regex
    (modulo the named segment group), so no earlier finding can be lost."""
    assert sweep.STRUCTURAL_RE.pattern == (
        r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]{1,2})(?P<seg>[A-Za-z0-9 ()+._\-]{1,80})"
    )


def test_a_mount_head_never_swallows_a_drive_letter_path_after_it():
    """In ONE alternation `/mnt/<x>/Q` ate the `Q` of the drive path after it
    and the drive-letter finding was lost (synthetic differential)."""
    text = '"' + "/" + "/".join(("mnt", "e", "Q")) + ":" + _BS + _UNKNOWN + '"\n'
    literals = [f.literal for f in _found(text)]
    assert "Q:" + _BS + _UNKNOWN in literals, literals


def test_a_mixed_separator_run_is_not_read_as_a_single_backslash():
    """`Q:/\\nZ...` was a finding before RM-876 (its separator run is `/\\`,
    not one backslash), and stays one."""
    assert _found("Q:/" + _BS + "nZorblax\n")


@pytest.mark.parametrize(
    "label,path",
    _posix_drive_spellings(_UNKNOWN),
    ids=[s[0] for s in _posix_drive_spellings(_UNKNOWN)],
)
def test_the_posix_drive_spelling_is_a_declared_residual(label, path):
    """NOT a finding, on purpose (module docstring). If this goes red because
    the head was added, re-run the real-tree differential first: the shapes
    in the next test are what it measured. The same text on a drive-letter
    head IS a finding, so this cannot pass for an unrelated reason."""
    assert _found("see " + path + "\n") == [], label
    drive = "Q:" + _BS + path.split("/", 2)[2]
    assert _found("see " + drive + "\n"), label


@pytest.mark.parametrize(
    "text",
    [
        "a profile at reddit.com " + "/" + "/".join(("u", "Some-mod-bot")),
        'src="' + "/" + "/".join(("x", "bnb.png")) + '"',
        "(" + "/" + "/".join(("m", ".git")) + ")",
        '"' + "/" + "/".join(("h", "match-history-query")) + '"',
        "base64,AAAA+" + "/" + "/".join(("Z", "zp")) + "+QQ",
    ],
)
def test_the_measured_posix_drive_false_positive_shapes_stay_clean(text):
    assert _found(text + "\n") == [], text


@pytest.mark.parametrize(
    "segment",
    ["Users", "Program Files", "Riot Commander", "Windows", "tmp", "<repo>", "rc-worktrees"],
)
def test_an_allowlisted_root_on_a_mount_spelling_stays_clean(segment):
    for label, path in _mount_spellings(segment):
        assert _found("see " + path + " here\n") == [], (label, segment)


@pytest.mark.parametrize(
    "label,text",
    [
        ("two-letter-mount", "/" + "/".join(("mnt", "qz", _UNKNOWN))),
        ("word-mount", "/" + "/".join(("mnt", "data", _UNKNOWN))),
        ("url-segment", "https://example.org/" + "/".join(("e", _UNKNOWN))),
        ("path-inside-path", "/" + "/".join(("srv", "e", _UNKNOWN))),
        ("word-before-drive", "x/" + "/".join(("e", _UNKNOWN))),
        ("unc-not-mount", _unc("wsl$", _BS, "home", _UNKNOWN)),
        ("unc-word-mount", _unc("wsl$", _BS, "mnt", "qz", _UNKNOWN)),
        ("sed-expression", "s/" + "/".join(("a", _UNKNOWN, "g"))),
    ],
)
def test_an_off_drive_root_path_is_not_a_structural_finding(label, text):
    assert _found("x " + text + " y\n") == [], label


def test_the_c_escape_class_still_applies_under_a_unc_backslash_head():
    """`...\\mnt\\r\\nShe will` in a JSON string is a newline escape, exactly
    the drive-letter class the arm already rejects by name."""
    text = _unc("wsl$", _BS, "mnt", "r", "nShe will strike")
    assert _found('"' + text + '"\n') == []


def test_a_doubled_backslash_unc_head_is_not_read_as_an_escape():
    text = _unc("wsl$", _BS * 2, "mnt", "r", "nWholly Unknown")
    assert _found(text + "\n")


def test_a_loaded_slot_on_a_mount_spelling_is_never_subtracted():
    """ARMED passes the slot names; a slot whose basename an allowlist pattern
    matches (`data`) still fires on its mount spelling, as on the drive one."""
    for label, path in _mount_spellings("data"):
        assert _found("see " + path + "\n") == [], label
        assert _found("see " + path + "\n", slot_names=["data"]), label


@pytest.mark.parametrize(
    "head",
    ["/" + "/".join(("mnt", "e", "")), _unc("wsl$", _BS, "mnt", "e", "")],
    ids=["wsl-mount", "unc"],
)
def test_the_word_cap_still_applies_to_a_mount_head(head):
    assert _found("x " + head + "Zorblax Works\n")  # positive control
    assert _found("x " + head + "this is a long sentence that is not a path\n") == []
