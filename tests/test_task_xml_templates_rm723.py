"""RM-723: the tracked scheduled-task XMLs are machine-free templates.

Defect (repo review 2026-10-09, LEDGER 1703; re-probed s144): three tracked
task definitions - ``ops/RC-Supervisor.xml``, ``ops/RC-DaemonSlayer.xml`` and
``ops/RC-CostHealthWatchdog.xml`` - were raw ``schtasks /Query /XML`` exports
in UTF-16 LE. They named the pre-move checkout root and a Windows account home
directory on a drive letter, the machine's computer name in ``<Author>``, a
per-machine user SID in ``<UserId>``, and the DS description still said
``127.0.0.1:8893`` (DS runs on :8860). The repo is PUBLIC, so this is the leak
class, and the one installer that imports one of them
(``tools/install_daemon_slayer_task.ps1``) fed the file to schtasks as-is.

Same root cause, sibling: UTF-16 makes a file invisible to every text guard
that reads UTF-8. ``tests/test_no_hardcoded_home_path.py`` lists ``.xml`` as a
runnable suffix and still passed over these three home paths, because a
UTF-16 path read as UTF-8 is ``C\\0:\\0\\\\0...`` and matches nothing. Its
reader is fixed in the same slice; this file pins the templates themselves.

Fix shape (the ``ops/RC-CIWatchdog.xml`` precedent): every tracked task XML is
7-bit ASCII with LF line ends, carries ``__RC_REPO__`` / ``__RC_USER__`` /
``__RC_PYTHONW__`` placeholders instead of machine values, and
``tools/install_render_task_xml.ps1`` renders one into the UTF-16 file schtasks
imports. ``__RC_PYTHONW__`` is rendered at install time rather than written as
``%LOCALAPPDATA%``: two of these tasks run as SYSTEM, whose LOCALAPPDATA is the
system profile, so an unexpanded variable would name an absent interpreter and
the task would silently do nothing.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

import pytest

ROOT = Path(__file__).resolve().parent.parent
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
PLACEHOLDERS = ("__RC_REPO__", "__RC_USER__", "__RC_PYTHONW__")
KNOWN_TASK_XMLS = (
    "ops/RC-CIWatchdog.xml",
    "ops/RC-CostHealthWatchdog.xml",
    "ops/RC-DaemonSlayer.xml",
    "ops/RC-Supervisor.xml",
)
#: The well-known service SIDs (LocalSystem, LocalService, NetworkService)
#: name no machine and no person, so a template may carry them verbatim.
WELL_KNOWN_SIDS = frozenset({"S-1-5-18", "S-1-5-19", "S-1-5-20"})
DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
MACHINE_SID = re.compile(r"S-1-5-21(?:-\d+)+")
LEFTOVER = re.compile(r"__RC_[A-Z0-9_]+__")
RENDERER = ROOT / "tools" / "install_render_task_xml.ps1"
DS_INSTALLER = ROOT / "tools" / "install_daemon_slayer_task.ps1"
NO_WINDOW = 0x08000000
#: What the existence check renders ``__RC_REPO__`` as. A task XML is a
#: Windows Task Scheduler definition, so its targets are Windows paths on
#: every host. Rendering with the host's own root (``str(ROOT)``) and reading
#: the result back with the host's ``Path`` only worked on Windows: on the
#: Linux CI runner ``<root>\tools\x.py`` is ONE file name with backslashes in
#: it, so every target "did not exist" (s157, CI runs 42580217676,
#: 42580217721, 42673808730). So the check renders under this fixed Windows
#: root - with a space, so an unquoted target still fails - and maps what
#: follows it onto ROOT by its Windows parts. Assembled at run time, not
#: spelled as one drive-rooted literal.
WIN_REPO = PureWindowsPath("C:" + "\\", "Rc Checkout")


def _repo_file(target: str, root: PurePath = ROOT) -> PurePath | None:
    """The checkout file a rendered Windows target names under ``root``, or
    None when the target is not under :data:`WIN_REPO`."""
    win = PureWindowsPath(target)
    if not win.is_relative_to(WIN_REPO):
        return None
    return root.joinpath(*win.relative_to(WIN_REPO).parts)


def _tracked_task_xmls() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "ops/"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    rels = [p.decode("utf-8") for p in out.split(b"\0") if p]
    return sorted(r for r in rels
                  if r.count("/") == 1 and r.lower().endswith(".xml"))


def _decode(raw: bytes) -> str:
    """Honour a BOM, so a check below can never be blind the way the
    home-path guard was."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def _text(rel: str) -> str:
    return _decode((ROOT / rel).read_bytes())


def _render(text: str, repo: str, user: str, pythonw: str) -> str:
    return (text.replace("__RC_REPO__", repo)
                .replace("__RC_USER__", user)
                .replace("__RC_PYTHONW__", pythonw))


#: Every tracked task XML directly under ops/, so a new one is checked too.
TASK_XMLS = _tracked_task_xmls()


def test_the_listing_reads_every_known_task_xml() -> None:
    """An empty listing and a clean tree give the same green verdict."""
    missing = [k for k in KNOWN_TASK_XMLS if k not in TASK_XMLS]
    assert not missing, f"tracked task XML listing lost {missing} (got {TASK_XMLS})"


@pytest.mark.parametrize("rel", TASK_XMLS)
def test_no_placeholder_is_spelled_inside_a_comment(rel: str) -> None:
    """The renderer fills every occurrence, so a placeholder named in a
    comment would write the checkout root and account into it."""
    comments = re.findall(r"<!--.*?-->", _text(rel), flags=re.S)
    named = [m for c in comments for m in LEFTOVER.findall(c)]
    assert not named, f"{rel} names {named} inside a comment"


@pytest.mark.parametrize("rel", TASK_XMLS)
def test_every_task_xml_is_ascii_with_lf_line_ends(rel: str) -> None:
    raw = (ROOT / rel).read_bytes()
    assert raw[:2] not in (b"\xff\xfe", b"\xfe\xff"), (
        f"{rel} is UTF-16: every text guard in this repo reads UTF-8 and is "
        "blind to it (RM-723)")
    bad = [i for i, b in enumerate(raw) if b > 0x7F]
    assert not bad, f"{rel} has non-ASCII bytes at offsets {bad[:5]}"
    assert b"\r" not in raw, f"{rel} has CR bytes; LF only"


@pytest.mark.parametrize("rel", TASK_XMLS)
def test_no_task_xml_names_a_machine_path_account_or_sid(rel: str) -> None:
    text = _text(rel)
    drive = [m.group(0) for m in DRIVE_PATH.finditer(text)]
    assert not drive, f"{rel} carries drive-letter paths: {drive}"
    sids = [m.group(0) for m in MACHINE_SID.finditer(text)]
    assert not sids, f"{rel} carries a per-machine account SID: {sids}"
    root = ET.fromstring(_render(text, "R", "U", "P"))
    for author in root.iterfind(".//t:RegistrationInfo/t:Author", NS):
        assert author.text == "U", (
            f"{rel} <Author> is {author.text!r}; a template names no account "
            "or computer, use __RC_USER__")
    for user in root.iterfind(".//t:Principal/t:UserId", NS):
        assert user.text == "U" or user.text in WELL_KNOWN_SIDS, (
            f"{rel} <UserId> is {user.text!r}; use __RC_USER__ or a well-known "
            "service SID")


@pytest.mark.parametrize("rel", TASK_XMLS)
def test_each_template_renders_to_a_task_whose_targets_exist(rel: str) -> None:
    text = _text(rel)
    head = text.split("?>", 1)[0]
    assert "UTF-16" not in head.upper(), (
        f"{rel} declares UTF-16 but is stored as ASCII; the renderer writes "
        "the UTF-16 file schtasks imports")
    rendered = _render(text, str(WIN_REPO), "someone", "C:" + r"\py\pythonw.exe")
    assert not LEFTOVER.search(rendered), (
        f"{rel} uses a placeholder the renderer does not fill: "
        f"{LEFTOVER.findall(rendered)}")
    root = ET.fromstring(rendered)
    execs = root.findall(".//t:Actions/t:Exec", NS)
    assert execs, f"{rel} has no Exec action"
    for ex in execs:
        args = ex.findtext("t:Arguments", default="", namespaces=NS)
        targets = re.findall(r'"([^"]+\.py)"', args)
        assert targets, f"{rel} Exec names no .py target: {args!r}"
        for target in targets:
            assert PureWindowsPath(target).is_absolute(), (
                f"{rel} target is not rooted: {target}")
            path = _repo_file(target)
            assert path is not None, (
                f"{rel} target is not under __RC_REPO__: {target}")
            assert Path(path).is_file(), f"{rel} target does not exist: {target}"


def test_a_rendered_target_maps_by_its_windows_parts_on_any_host() -> None:
    """The s157 Linux red, pinned so a Windows run catches it too: the target
    is split on the WINDOWS separator whatever the host, never joined onto a
    POSIX root as text."""
    posix_root = PurePosixPath("/srv/rc checkout")
    target = str(WIN_REPO / "tools" / "ci_watchdog.py")
    got = _repo_file(target, posix_root)
    assert got == posix_root / "tools" / "ci_watchdog.py", got
    assert "\\" not in str(got), got
    outside = str(PureWindowsPath("C:" + "\\", "elsewhere", "tools", "x.py"))
    assert _repo_file(outside, posix_root) is None


def test_the_ds_task_description_names_the_live_port() -> None:
    root = ET.fromstring(_render(_text("ops/RC-DaemonSlayer.xml"), "R", "U", "P"))
    desc = root.findtext(".//t:RegistrationInfo/t:Description", default="",
                         namespaces=NS)
    assert "127.0.0.1:8860" in desc, desc
    assert "8893" not in desc, desc


def test_the_ds_installer_imports_a_rendered_file_not_the_template() -> None:
    src = DS_INSTALLER.read_text(encoding="utf-8")
    assert "install_render_task_xml.ps1" in src, (
        "install_daemon_slayer_task.ps1 must render the template first")
    assert not re.search(r"/XML\s+\"?\$XmlPath", src), (
        "install_daemon_slayer_task.ps1 still hands the raw template to schtasks")


_PS51 = shutil.which("powershell.exe") if os.name == "nt" else None
needs_ps51 = pytest.mark.skipif(_PS51 is None,
                                reason="Windows PowerShell 5.1 not available")


def _ps51(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_PS51, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
        creationflags=NO_WINDOW if os.name == "nt" else 0,
    )


@needs_ps51
@pytest.mark.parametrize("script", [RENDERER, DS_INSTALLER],
                         ids=lambda p: p.name)
def test_the_scripts_parse_under_windows_powershell_51(script: Path) -> None:
    assert script.is_file(), f"{script.name} is missing"
    command = (
        "$e = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{script}', [ref]$null, [ref]$e); Write-Output ('ERRORS=' + $e.Count)"
    )
    proc = _ps51(["-Command", command])
    assert "ERRORS=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"


@needs_ps51
@pytest.mark.parametrize("rel", TASK_XMLS)
def test_the_renderer_writes_an_importable_utf16_task(rel: str,
                                                      tmp_path: Path) -> None:
    name = Path(rel).stem
    out = tmp_path / f"{name}.xml"
    proc = _ps51(["-File", str(RENDERER), "-Name", name, "-OutFile", str(out),
                  "-PythonW", sys.executable])
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    raw = out.read_bytes()
    assert raw[:2] == b"\xff\xfe", "schtasks /XML is fed UTF-16 LE with a BOM"
    text = raw.decode("utf-16")
    assert not LEFTOVER.search(text), LEFTOVER.findall(text)
    root = ET.fromstring(text.encode("utf-16"))
    for ex in root.findall(".//t:Actions/t:Exec", NS):
        command = ex.findtext("t:Command", default="", namespaces=NS).strip('"')
        assert "%" in command or Path(command) == Path(sys.executable), command
        args = ex.findtext("t:Arguments", default="", namespaces=NS)
        for target in re.findall(r'"([^"]+\.py)"', args):
            assert Path(target).is_file(), target
            assert Path(target).resolve().is_relative_to(ROOT), target
    for author in root.iterfind(".//t:RegistrationInfo/t:Author", NS):
        # Read the one value first: an environ read inside the assert would
        # render the whole environment into a failure (test_no_environ_in_assert_operands).
        expected = os.environ.get("USERNAME", author.text)
        assert author.text == expected


@needs_ps51
def test_the_renderer_refuses_an_absent_interpreter(tmp_path: Path) -> None:
    out = tmp_path / "x.xml"
    proc = _ps51(["-File", str(RENDERER), "-Name", "RC-DaemonSlayer",
                  "-OutFile", str(out), "-PythonW",
                  str(tmp_path / "absent" / "pythonw.exe")])
    assert proc.returncode != 0
    assert not out.exists(), "a refused render must not leave a file behind"


@needs_ps51
def test_the_renderer_refuses_a_name_that_leaves_ops(tmp_path: Path) -> None:
    # A real task XML outside ops/, so only the name check can refuse it.
    escape = "..\\docs\\_archive\\2026-06-11_RC-VisionServer_schtask_removed"
    # Split on the Windows separator, not handed to the host Path as text
    # (the s157 root cause; this test only runs where PS 5.1 exists).
    parts = PureWindowsPath(escape + ".xml").parts
    assert ROOT.joinpath("ops", *parts).resolve().is_file()
    out = tmp_path / "x.xml"
    proc = _ps51(["-File", str(RENDERER), "-Name", escape,
                  "-OutFile", str(out), "-PythonW", sys.executable])
    assert proc.returncode != 0
    assert not out.exists()
