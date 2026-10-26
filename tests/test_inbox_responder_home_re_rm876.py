"""RM-876 (b): the responder's outbound home-path scrub reads every RM-813 spelling.

`tools/inbox_responder_exec.py` `_HOME_RE` is used twice: `scrub_output`
folds a profile path out of measured stdout before it reaches a note, and
`filter_body` refuses an assembled note that still carries one (gate
`home-path`). It read `<letter>:<sep>Users<sep>`, `/home/` and `/Users/`, so
every forward-slash spelling was caught (the WSL mount `/mnt/<x>/Users/`, the
POSIX-shell drive `/<x>/Users/` and the forward-slash WSL UNC path all carry
`/Users/` or `/home/`), but the BACKSLASH WSL UNC spelling
`<lead>wsl$<sep><distro><sep>mnt<sep><x><sep>Users<sep><acct>` - either host,
the Win32 `?` long-path or `.` device step, single or doubled separators - and
the distro's own `<lead>wsl$<sep><distro><sep>home<sep><acct>` passed both.

The fix only ADDS an alternative (the gate's `search` is monotone by
construction; a scrub span may start earlier, never leaving the account
visible), and its lead is
the same string as `tools/credential_patterns.py` `_WSL_UNC_LEAD`, pinned
equal here so the three readers of the lead cannot drift apart.

Every literal is invented and assembled at run time: no drive-rooted literal,
no real distro and no real account appears in this file.
"""
from __future__ import annotations

import itertools

import pytest

from tools import credential_patterns as cp
from tools import inbox_responder_exec as rexec

_BS = "\\"
_DISTRO = "Synth-Distro"
_ACCT = "zzacct"
_HOSTS = ("wsl$", "wsl.localhost")
_STEPS = ("", "?", ".")
_SEPS = (_BS, _BS * 2, "/")


def _unc(host: str, sep: str, step: str, *parts: str) -> str:
    """`<sep><sep>[step<sep>UNC<sep>]host<sep>distro<sep>parts...`."""
    lead = sep * 2 + (step + sep + "UNC" + sep if step else "")
    return lead + sep.join((host, _DISTRO) + tuple(parts))


def _unc_profiles() -> list:
    out = []
    for host, sep, step in itertools.product(_HOSTS, _SEPS, _STEPS):
        out.append(_unc(host, sep, step, "mnt", "c", "Users", _ACCT, "x"))
        out.append(_unc(host, sep, step, "home", _ACCT, "x"))
    return out


def _drive_profiles() -> list:
    drive = "C" + ":"
    out = []
    for sep in _SEPS:
        out.append(sep.join((drive, "Users", _ACCT, "x")))
    out.append("/".join(("", "mnt", "c", "Users", _ACCT, "x")))
    out.append("/".join(("", "c", "Users", _ACCT, "x")))
    out.append("/".join(("", "home", _ACCT, "x")))
    out.append("/".join(("", "Users", _ACCT, "x")))
    return out


_ALL = _drive_profiles() + _unc_profiles()


def test_the_probe_set_carries_the_backslash_unc_spellings():
    # Anchor: an empty or forward-slash-only probe set would pass vacuously.
    backslash_unc = [p for p in _ALL if p.startswith(_BS * 2)]
    assert len(backslash_unc) == 2 * 2 * 2 * 3
    assert all(_ACCT in p for p in _ALL)


@pytest.mark.parametrize("path", _ALL)
def test_scrub_output_folds_every_profile_spelling(path):
    text, count = rexec.scrub_output(("read " + path + " ok").encode("ascii"))
    assert "<home>" in text
    assert _ACCT not in text
    assert count >= 1


@pytest.mark.parametrize("path", _ALL)
def test_filter_body_refuses_every_profile_spelling(path):
    assembled = "[RC-RESPONDER] reply\n\nI read " + path + "\n"
    hits = rexec.filter_body(
        assembled, "I read " + path, ["RSC"], ["RSC"], rexec.GRAMMAR_A5
    )
    assert "home-path" in hits


@pytest.mark.parametrize("sep", [_BS, _BS * 2])
def test_a_unc_path_outside_a_profile_is_not_a_home_path(sep):
    # The new arm names the profile roots only; a distro path that is not a
    # profile stays readable, so the scrub does not swallow every UNC path.
    path = _unc("wsl$", sep, "", "mnt", "c", "Windows", "Temp", "x")
    text, _ = rexec.scrub_output(path.encode("ascii"))
    assert "<home>" not in text
    assert rexec._HOME_RE.search(path) is None


def test_the_unc_lead_is_pinned_equal_to_the_push_gate_lead():
    assert rexec._WSL_UNC_LEAD == cp._WSL_UNC_LEAD
