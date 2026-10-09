"""Leak classes in the push gate (MAIN 2246 ORDER sections 3-4).

The README audit named the leak CLASSES the public tree carried: private-LAN
IPv4, the tailnet addresses and names, the machine host name, user-profile
paths and the absolute checkout path. HEAD was scrubbed (LEDGER 1699); these
tests pin the PREVENTION half - a push that ADDS one of them halts, a test or
fixture path does not, and no value is ever printed.

Gate (HALT) classes: private_lan_ipv4, tailnet_ipv4, tailnet_dns_name,
windows_host_name, local_host_value. Advisory (reported, never a halt):
user_profile_path, checkout_path.

Every leak-shaped literal below is ASSEMBLED AT RUNTIME, so this file holds
none and the sweep's exempt-path count does not grow because of it.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import credential_history_scan as chs
from tools import credential_patterns as cp

ROOT = Path(__file__).resolve().parent.parent
_NW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ip(*octets: int) -> str:
    return ".".join(str(o) for o in octets)


LAN_192 = _ip(192, 168, 77, 41)
LAN_10 = _ip(10, 20, 30, 40)
LAN_172 = _ip(172, 20, 1, 9)
TAILNET_IP = _ip(100, 101, 7, 8)
TAILNET_DNS = "tail" + "a1b2c3" + ".ts" + ".net"
WIN_DESKTOP = "DESKTOP" + "-" + "Q7Z3K1M"
WIN_SERVER = "WIN" + "-" + "A1B2C3D4E5F"
DRIVE = "C" + ":"
PROFILE_PATH = DRIVE + "\\" + "Users" + "\\" + "someone" + "\\" + "AppData"

PLANTED = {
    "private_lan_ipv4": (LAN_192, LAN_10, LAN_172),
    "tailnet_ipv4": (TAILNET_IP,),
    "tailnet_dns_name": (TAILNET_DNS, "node." + TAILNET_DNS),
    "windows_host_name": (WIN_DESKTOP, WIN_SERVER, WIN_DESKTOP.lower()),
}


def _classes(findings) -> set[str]:
    return {f.pattern_class for f in findings}


# --------------------------------------------------------------------------
# credential_patterns: the shape classes
# --------------------------------------------------------------------------


def test_gate_and_advisory_class_sets_are_disjoint_and_named():
    assert set(cp.LEAK_PATTERN_CLASSES) >= set(PLANTED) | {"local_host_value"}
    assert set(cp.ADVISORY_LEAK_CLASSES) == {"user_profile_path", "checkout_path"}
    assert not set(cp.LEAK_PATTERN_CLASSES) & set(cp.ADVISORY_LEAK_CLASSES)
    assert not set(cp.LEAK_PATTERN_CLASSES) & set(cp.PATTERN_CLASSES)


@pytest.mark.parametrize(
    "cls,value", [(c, v) for c, vals in sorted(PLANTED.items()) for v in vals]
)
def test_planted_value_is_caught(cls, value):
    findings = cp.scan_leaks(f"host = {value}\n")
    assert cls in _classes(findings), (cls, [f.pattern_class for f in findings])


@pytest.mark.parametrize(
    "cls,value", [(c, v) for c, vals in sorted(PLANTED.items()) for v in vals]
)
def test_prefilter_arms_the_family_it_gates(cls, value):
    lowered = value.lower()
    assert any(lit in lowered for lit in cp._LEAK_TRIGGERS[cls])


def test_every_shape_family_has_a_prefilter_row():
    assert {name for name, _ in cp._LEAK_FAMILIES} == set(cp._LEAK_TRIGGERS)


@pytest.mark.parametrize(
    "text",
    [
        _ip(192, 0, 2, 10),  # RFC 5737 documentation block
        _ip(198, 51, 100, 7),  # RFC 5737
        _ip(127, 0, 0, 1),
        _ip(0, 0, 0, 0),
        _ip(172, 15, 0, 1),  # just below 172.16/12
        _ip(172, 32, 0, 1),  # just above 172.16/12
        _ip(192, 169, 1, 1),
        _ip(110, 0, 0, 1),  # not 10/8: digit to the left
        _ip(10, 0, 0, 256),  # not an address
        "10.0.19045",  # a Windows build number, three parts
        _ip(100, 64, 0, 1),  # the tailnet placeholder block
        _ip(100, 63, 9, 9),  # below 100.64/10
        "rc-host.example-tailnet.ts.net",
        "WINDOWS-HOST",
        "WIN-CAPTURE keystone",
        "WIN-PROBABILITY",
        "DESKTOP-PLACEHOLDER",
    ],
)
def test_placeholders_and_near_misses_are_not_gate_hits(text):
    assert cp.scan_leaks(f"x = {text}\n") == []


def test_address_followed_by_a_dot_and_digit_is_not_cut_short():
    assert cp.scan_leaks(LAN_10 + ".5\n") == []
    assert _classes(cp.scan_leaks(LAN_10 + ".\n")) == {"private_lan_ipv4"}


def test_line_numbers_and_pragma():
    text = "a\n" + LAN_192 + "\n" + LAN_10 + "  # " + cp.PRAGMA + "\n"
    findings = cp.scan_leaks(text)
    assert [(f.line_no, f.pattern_class, f.arm) for f in findings] == [
        (2, "private_lan_ipv4", "leak")
    ]


def test_finding_carries_no_value_and_format_prints_none():
    findings = cp.scan_leaks(f"bind {LAN_192} and {WIN_DESKTOP}\n")
    assert findings
    assert set(findings[0]._fields) == {"line_no", "pattern_class", "arm"}
    rendered = "\n".join(cp.format_findings("f.md", findings))
    assert LAN_192 not in rendered and WIN_DESKTOP not in rendered


def test_credential_arm_is_unchanged_by_the_leak_classes():
    """The write-time credential arm (scan_text) stays credential-only."""
    assert cp.scan_text(f"host = {LAN_192} {WIN_DESKTOP}\n") == []


def test_modules_do_not_trip_the_leak_arm():
    for rel in ("tools/credential_patterns.py", "tools/credential_history_scan.py",
                "tests/test_leak_classes_push_gate.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert cp.scan_leaks(text) == [], rel


# --------------------------------------------------------------------------
# advisory classes
# --------------------------------------------------------------------------


def test_user_profile_path_is_advisory():
    findings = cp.scan_leaks(f"log = {PROFILE_PATH}\n")
    assert _classes(findings) == {"user_profile_path"}
    assert all(cp.is_advisory(f) for f in findings)
    forward = PROFILE_PATH.replace("\\", "/")
    bash = "/c/" + "Users/someone/AppData"
    assert _classes(cp.scan_leaks(forward)) == {"user_profile_path"}
    assert _classes(cp.scan_leaks(bash)) == {"user_profile_path"}


@pytest.mark.parametrize(
    "text",
    [
        "%USERPROFILE%\\AppData",
        DRIVE + "\\Users\\<user>\\AppData",
        DRIVE + "\\Users\\%USERNAME%\\AppData",
        DRIVE + "\\Users\\Public\\Desktop",
        DRIVE + "\\Users\\Default\\NTUSER",
        "$HOME/AppData",
    ],
)
def test_profile_placeholders_are_not_flagged(text):
    assert cp.scan_leaks(text + "\n") == []


def test_checkout_path_value_is_advisory_in_every_spelling():
    # Assembled so no drive-rooted literal sits in this source: the
    # sibling-name sweep's structural arm reads one as an undeclared project.
    checkout = "Q" + ":" + "\\" + "Work Tree" + "\\" + "Proj"
    variants = cp.checkout_path_variants(checkout)
    assert checkout in variants
    assert ("Q" + ":" + "/Work Tree/Proj") in variants
    assert "/q/Work Tree/Proj" in variants
    for spelled in variants:
        findings = cp.scan_leaks(f"cd {spelled}\\tools\n", checkout_paths=variants)
        assert _classes(findings) == {"checkout_path"}, spelled
        assert all(cp.is_advisory(f) for f in findings)
    # The drive is not the identity: a checkout that moved drives is still
    # cited under the old one.
    old_drive = "Z" + ":" + "\\" + "Work Tree" + "\\" + "Proj" + "\\x"
    assert _classes(cp.scan_leaks(old_drive, checkout_paths=(checkout,))) == {"checkout_path"}
    # The folder name alone, or a longer sibling folder, is not the path.
    assert cp.scan_leaks("the Work Tree Proj notes\n", checkout_paths=(checkout,)) == []
    longer = "Z" + ":" + "\\" + "Work Tree" + "\\" + "ProjX"
    assert cp.scan_leaks(longer, checkout_paths=(checkout,)) == []


# --------------------------------------------------------------------------
# the values arm (gitignored per-host config + live host name)
# --------------------------------------------------------------------------


def test_local_value_is_caught_case_insensitively_at_word_edges():
    value = "Box" + "-Node7"
    findings = cp.scan_leaks(f"see {value.upper()} now\n", values=(value,))
    assert [(f.pattern_class, f.arm) for f in findings] == [("local_host_value", "value")]
    assert cp.scan_leaks(f"see {value}9 now\n", values=(value,)) == []
    assert cp.scan_leaks(f"see x{value} now\n", values=(value,)) == []


def test_local_value_suffix_of_an_fqdn_is_caught():
    tailnet = "home" + "-net" + ".ts" + ".net"
    findings = cp.scan_leaks(f"https://rc.{tailnet}:8888/\n", values=(tailnet,))
    assert _classes(findings) == {"local_host_value"}


@pytest.mark.parametrize(
    "value",
    ["", "   ", "abc", "localhost", "LOCALHOST", _ip(127, 0, 0, 1), "::1",
     _ip(0, 0, 0, 0), "rc-host", "peer-host", "work-host", "WINDOWS-HOST",
     "example-tailnet", "x.example-tailnet.ts.net", _ip(192, 0, 2, 10),
     _ip(100, 64, 0, 1), 7, None],
)
def test_unusable_values_are_dropped(value):
    assert not cp.usable_leak_value(value)


def test_usable_value_examples():
    assert cp.usable_leak_value("Box" + "-Node7")
    assert cp.usable_leak_value(LAN_192)


# --------------------------------------------------------------------------
# path exemption (tests / fixtures)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_x.py",
        "tests/fixtures/liveclient/a.json",
        "tests/fu02_team_context/test_y.py",
        "rc-shell/test/config.test.js",
        "lane-widget/test/poll.test.js",
        "pkg/sub/test_thing.py",
        "pkg/sub/thing_test.py",
        "pkg/conftest.py",
        "agents/agent3_testing/suite/_smoke_agent0.py",
        "agents/agent3_testing/suite/test_agent0.py",
        "data/fixtures/x.json",
        "web/js/foo.spec.js",
        "tests\\windows\\style.py",
    ],
)
def test_test_and_fixture_paths_are_exempt(path):
    assert cp.is_leak_exempt(path)


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "docs/OPERATIONS.md",
        "core/local_hosts.py",
        "mc/server.py",
        "contests/x.py",
        "tools/attest_runner.py",
        "agents/agent3_testing/charter.md",
        "ops/phase3_install.ps1",
        "atlas.html",
    ],
)
def test_product_and_doc_paths_are_not_exempt(path):
    assert not cp.is_leak_exempt(path)


# --------------------------------------------------------------------------
# credential_history_scan: the push gate and the HEAD sweep
# --------------------------------------------------------------------------


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


def _commit(r: Path, name: str, body: str) -> str:
    target = r / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="ascii")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "c")
    return _git(r, "rev-parse", "HEAD")


def _push(repo: Path, base: str, **kw) -> int:
    kw.setdefault("leak_values", ())
    kw.setdefault("checkout_paths", ())
    return chs.run_push([["HEAD", "--not", base]], root=repo, **kw)


@pytest.mark.parametrize(
    "cls,value", [(c, vals[0]) for c, vals in sorted(PLANTED.items())]
)
def test_push_halts_on_a_planted_leak_in_a_doc(repo, cls, value, capsys):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "docs/NOTES.md", f"reach it at {value}\n")
    assert _push(repo, base) == chs.EXIT_HALT
    err = capsys.readouterr().err
    assert f"class={cls}" in err
    assert value not in err


def test_push_is_clean_when_the_same_value_is_in_a_test_fixture(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "tests/fixtures/hosts.json", json.dumps({"ip": LAN_192}) + "\n")
    _commit(repo, "tests/test_bind.py", f'HOST = "{LAN_10}"\n')
    assert _push(repo, base) == chs.EXIT_CLEAN


def test_push_halts_on_a_configured_local_value(repo, capsys):
    secret_host = "Box" + "-Node7"
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "core/cfg.py", f'NAME = "{secret_host.lower()}"\n')
    assert _push(repo, base, leak_values=(secret_host,)) == chs.EXIT_HALT
    err = capsys.readouterr().err
    assert "class=local_host_value" in err and secret_host.lower() not in err


def test_push_advisory_class_reports_but_does_not_halt(repo, capsys):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "docs/RUN.md", f"logs live in {PROFILE_PATH}\n")
    assert _push(repo, base) == chs.EXIT_CLEAN
    err = capsys.readouterr().err
    assert "advisory" in err and "class=user_profile_path" in err
    assert "someone" not in err


def test_push_still_halts_on_credentials(repo):
    base = _git(repo, "rev-parse", "HEAD")
    fake = "sk-" + "ant-" + "Q7" * 12
    _commit(repo, "cfg.py", f'KEY = "{fake}"\n')
    assert _push(repo, base) == chs.EXIT_HALT


def test_local_leak_values_reads_config_and_live_host(tmp_path, monkeypatch):
    cfg = tmp_path / "ops" / "local_hosts.json"
    cfg.parent.mkdir(parents=True)
    tailnet = "home" + "-net" + ".ts" + ".net"
    cfg.write_text(json.dumps({
        "_doc": "ignored prose with spaces",
        "tailnet_name": tailnet,
        "tailnet_ipv4": TAILNET_IP,
        "lan_ipv4": LAN_192,
        "lan_subnet": _ip(192, 168, 77, 0) + "/24",
        "cert_sans": ["localhost", _ip(127, 0, 0, 1), "Box" + "-Node7"],
        "tailnet_fqdn": "",
    }), encoding="ascii")
    values = chs.local_leak_values(root=tmp_path, env={"COMPUTERNAME": "HOSTX" + "99"},
                                   hostname="hostx99")
    lowered = {v.lower() for v in values}
    assert {tailnet, TAILNET_IP, LAN_192, "box-node7", "hostx99"} <= lowered
    assert "localhost" not in lowered and _ip(127, 0, 0, 1) not in lowered
    assert len(lowered) == len(values)  # de-duplicated case-insensitively


def test_local_leak_values_absent_config_is_live_host_only(tmp_path):
    values = chs.local_leak_values(root=tmp_path, env={}, hostname="")
    assert values == ()


def test_sweep_counts_exempt_hits_apart(repo):
    _commit(repo, "tests/test_bind.py", f'HOST = "{LAN_10}"\n')
    hits, exempt, _stats = chs.sweep_leaks("HEAD", root=repo, leak_values=(),
                                           checkout_paths=())
    assert hits == [] and len(exempt) == 1
    assert chs.run_leak_sweep("HEAD", root=repo, leak_values=(),
                              checkout_paths=()) == chs.EXIT_CLEAN
    _commit(repo, "docs/NET.md", f"gateway {LAN_192}\n")
    hits, exempt, _stats = chs.sweep_leaks("HEAD", root=repo, leak_values=(),
                                           checkout_paths=())
    assert [(p, f.pattern_class) for p, f in hits] == [("docs/NET.md", "private_lan_ipv4")]
    assert chs.run_leak_sweep("HEAD", root=repo, leak_values=(),
                              checkout_paths=()) == chs.EXIT_HALT


def test_sweep_bad_rev_is_a_fault(repo):
    assert chs.run_leak_sweep("deadbeef" * 5, root=repo, leak_values=(),
                              checkout_paths=()) == chs.EXIT_FAULT


def test_pre_push_hook_already_runs_the_module_that_carries_the_leak_gate():
    """No new wiring: .githooks/pre-push already invokes --pre-push."""
    hook = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert '"$ROOT/tools/credential_history_scan.py" --pre-push "$@"' in hook


# --------------------------------------------------------------------------
# acceptance guard: tracked HEAD carries no gate-class leak outside test paths
# --------------------------------------------------------------------------


# (path, class) residuals MEASURED at HEAD when this guard landed, outside this
# slice's files. Each is a real value awaiting a redaction-only edit; remove
# the row in the commit that redacts it. Keyed by class, never by value.
# - docs/history_notes.md: a decommissioned peer machine's Windows-generated
#   host name in a 2026-05-20 ledger entry (missed by the LEDGER 1699 scrub,
#   whose replace list held only this machine's names).
_HEAD_RESIDUALS = frozenset({("docs/history_notes.md", "windows_host_name")})


@pytest.fixture(scope="module")
def head_sweep():
    """One read of every file tracked at HEAD (about 13 s), shared below."""
    return chs.sweep_leaks("HEAD", root=ROOT, leak_values=(), checkout_paths=())


def test_tracked_head_has_no_private_lan_ipv4_outside_test_paths(head_sweep):
    """MAIN 2246 ORDER section 3 ACCEPT: the private-LAN sweep returns 0."""
    hits, _exempt, stats = head_sweep
    assert stats["scanned"] > 1000, stats  # non-vacuous: the tree was read
    lan = [(p, f.line_no) for p, f in hits if f.pattern_class == "private_lan_ipv4"]
    assert lan == [], lan


def test_tracked_head_has_no_new_gate_class_leak_outside_test_paths(head_sweep):
    hits, _exempt, _stats = head_sweep
    new = sorted({(p, f.pattern_class) for p, f in hits if not cp.is_advisory(f)}
                 - _HEAD_RESIDUALS)
    assert new == [], new
