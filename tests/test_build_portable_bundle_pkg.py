"""PKG-4: the Amberstone bundle builder (docs/PACKAGING_PLAN.md section 4).

MUST-FIX M6 measured the old pipeline building a bundle that could not start:
a hand-kept list naming files that no longer exist and omitting
web_dashboard.py, app/, dashboard/, web/ and agents/, under the retired
`RiotCommander-portable` name. These tests pin the rewrite:

* inclusion = the git INDEX minus an explicit, reasoned exclusion list (never
  a hand-kept inclusion list, never a disk walk, so gitignored secrets, logs
  and caches cannot ride along);
* the import closure of every process the backend runs is inside the bundle;
* no key file, no ops/runtime/, no boot-start installer, no LFS pointer;
* artifacts named Amberstone-*;
* the embedded runtime comes from a pinned, SHA-256 verified python.org zip
  plus the hashed lock, with the opencv ffmpeg DLL strip and the certifi
  inclusion as explicit, recorded, configurable steps (M10).

Every build goes into tmp_path. No network: the embed zip "download" is a
fake opener and pip is a fake runner, both injected (never a process-wide
stdlib patch, tests/test_no_process_wide_stdlib_fakes_rm801.py).
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import build_installer as bi  # noqa: E402
from tools import build_portable as bp  # noqa: E402
from tools import build_python_embed as bpe  # noqa: E402
from tools import package_portable as pp  # noqa: E402

LFS_POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    "oid sha256:" + "ab" * 32 + "\n"
    "size 66961895\n"
)


# --------------------------------------------------------------------------- #
# Fixtures: a tiny git repo shaped like RC, and fakes for the network and pip
# --------------------------------------------------------------------------- #
def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True)


def _commit(root: Path, *new_files: str) -> None:
    """Stage tracked changes (plus the named new files) and commit, so the
    fixture source is clean against HEAD. Hooks point at an empty folder."""
    nohooks = root.parent / "nohooks"
    nohooks.mkdir(exist_ok=True)
    if new_files:
        _git(root, "add", *new_files)
    _git(root, "add", "-u")
    _git(root, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
         "-c", f"core.hooksPath={nohooks}", "-c", "commit.gpgsign=false",
         "commit", "-q", "--allow-empty", "-m", "fixture")


def _write(root: Path, rel: str, text: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


TRACKED = {
    "main.py": "import app\nimport web_dashboard\n",
    "web_dashboard.py": "from dashboard import server\n",
    "moon_vision_server.py": "from vision_server import main\n",
    "app/__init__.py": "from core import util\n",
    "core/__init__.py": "",
    "core/util.py": "from . import helper\n",
    "core/helper.py": "X = 1\n",
    "dashboard/__init__.py": "",
    "dashboard/server.py": ("import importlib\nimportlib.import_module('core.late')\n"
                            "_TARGET = 'core.const_target'\n"
                            "def load():\n    return importlib.import_module(_TARGET)\n"),
    "core/late.py": "",
    "core/const_target.py": "",
    "core/coach_registry.py": ('MODE_COACH_MAP = {\n'
                               '    "_x_mode": ("coaches.x_coach", "Coach", "x.json"),\n'
                               '}\n'),
    "coaches/__init__.py": "",
    "coaches/x_coach.py": "from core import helper\n",
    "vision_server/__init__.py": "def main():\n    return 0\n",
    "tools/__init__.py": "",
    "tools/lcu_agent.py": "from core import helper\n",
    "tools/liveclient_relay.py": "import core\n",
    "tools/hotkey_listener.py": "from core.helper import X\n",
    "tools/start_daemon_slayer.py": "from agents.daemon_slayer.server import run\n",
    "agents/__init__.py": "",
    "agents/daemon_slayer/__init__.py": "",
    "agents/daemon_slayer/server.py": "def run():\n    return 0\n",
    "agents/daemon_slayer/tests/test_ds.py": "def test_x():\n    pass\n",
    "ops/__init__.py": "",
    "ops/rc_supervisor.py": "import json\nCMD = ['schtasks', '/Run', '/TN', 'X']\n",
    "agents/supervisor.py": "from agents import _supervisor_ephemeral\n",
    "agents/_supervisor_ephemeral.py": "from ops.loop import thing\n",
    "tools/install_ds_keepalive_task.ps1": "New-ScheduledTaskTrigger -AtStartup\n",
    "tools/legion_on.ps1": "Start-ScheduledTask -TaskName X\n",
    "ops/install_startup.bat": "@echo off\n",
    "ops/autostart_on_login.bat": "@echo off\n",
    "ops/loop/__init__.py": "",
    "ops/loop/thing.py": "",
    "ops/fleet_kit/fleet_x.py": "",
    "scripts/kill.bat": "@echo off\n",
    "scripts/restart.bat": "@echo off\n",
    "tests/test_a.py": "def test_a():\n    pass\n",
    "tests/conftest.py": "",
    "docs/A.md": "# a\n",
    ".github/workflows/ci.yml": "on: push\n",
    "web/index.html": "<html></html>\n",
    "data/static.json": "{}\n",
    "data/scrape.log": "noise\n",
    "data/daemon_slayer/laning_scenarios/1.0.1/laning_scenarios_sr.json":
        LFS_POINTER,
    "requirements.txt": "anthropic==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\n",
    "start.bat": "@echo off\n",
    "LICENSE": "Apache\n",
    "NOTICE": "Amberstone\n",
    "CLAUDE.md": "# rules\n",
    ".gitignore": ("API-Key-Claude.txt\nAPI-Key-Riot.txt\nlogs/\nops/runtime/\n"
                   "ops/local_hosts.json\nops/moon_sync_repos.json\nops/tls/*.pem\n"
                   "data/cache/\ndist/\n"),
}

UNTRACKED = {
    "API-Key-Claude.txt": "sk-ant-NOTAREALKEY",  # rc-credential-scan: allow-fixture
    "API-Key-Riot.txt": "RGAPI-NOTAREALKEY",  # rc-credential-scan: allow-fixture
    "ops/local_hosts.json": "{}\n",
    "ops/moon_sync_repos.json": "{}\n",
    "ops/runtime/health.json": "{}\n",
    "ops/tls/rc.pem": "pem\n",
    "logs/2026-10-26.log": "log\n",
    "data/cache/big.json": "{}\n",
    "stray_untracked.py": "",
}


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for rel, text in TRACKED.items():
        _write(root, rel, text)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _commit(root)
    # Written after the commit: on disk, never in the index (the gitignored
    # ones could not be added anyway; stray_untracked.py simply never was).
    for rel, text in UNTRACKED.items():
        _write(root, rel, text)
    return root


def _replace_lfs_with_real(root: Path) -> None:
    _write(root, "data/daemon_slayer/laning_scenarios/1.0.1/laning_scenarios_sr.json",
           '{"schema": "laning_scenarios/v4"}\n')
    _commit(root)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _fake_embed_zip_bytes(tag: str = "314") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("python.exe", b"MZ fake")
        zf.writestr("pythonw.exe", b"MZ fake")
        zf.writestr(f"python{tag}.dll", b"MZ fake")
        zf.writestr(f"python{tag}.zip", b"PK fake")
        zf.writestr("LICENSE.txt", "PSF LICENSE AGREEMENT\n")
        zf.writestr(f"python{tag}._pth",
                    f"python{tag}.zip\n.\n\n# Uncomment to run site.main() "
                    "automatically\n#import site\n")
    return buf.getvalue()


@pytest.fixture()
def fake_pin() -> tuple:
    data = _fake_embed_zip_bytes()
    pin = bpe.EmbedPin(
        version="3.14.4",
        url="https://www.python.org/ftp/python/3.14.4/python-3.14.4-embeddable-amd64.zip",
        sha256=hashlib.sha256(data).hexdigest(),
    )
    return pin, data


def _opener_for(data: bytes, calls: list):
    def opener(url, timeout=None):
        calls.append(url)
        return FakeResponse(data)
    return opener


def _write_dist(sp: Path, name: str, version: str, license_line: str) -> None:
    d = sp / f"{name}-{version}.dist-info"
    d.mkdir(parents=True, exist_ok=True)
    (d / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n{license_line}\n",
        encoding="utf-8")


def _fake_pip(calls: list):
    """Stands in for `pip install --target`: lays down what the real lock
    would, including the two M10 payloads the builder must act on."""
    def runner(cmd):
        calls.append(list(cmd))
        target = Path(cmd[cmd.index("--target") + 1])
        (target / "cv2").mkdir(parents=True, exist_ok=True)
        (target / "cv2" / "__init__.py").write_text("", encoding="utf-8")
        (target / "cv2" / "opencv_videoio_ffmpeg500_64.dll").write_bytes(b"MZ")
        _write_dist(target, "opencv_python", "5.0.0.93", "License-Expression: Apache-2.0 AND MIT")
        (target / "certifi").mkdir(parents=True, exist_ok=True)
        (target / "certifi" / "__init__.py").write_text("", encoding="utf-8")
        (target / "certifi" / "cacert.pem").write_text("pem", encoding="utf-8")
        _write_dist(target, "certifi", "2026.10.19", "License: MPL-2.0")
        _write_dist(target, "anthropic", "1.11.0", "License-Expression: MIT")
        return 0
    return runner


# --------------------------------------------------------------------------- #
# Inclusion: the git index minus a reasoned exclusion list
# --------------------------------------------------------------------------- #
def test_inclusion_is_the_git_index_not_the_disk(fake_repo):
    plan = bp.plan_bundle(fake_repo, bp.git_index_files(fake_repo))
    assert "main.py" in plan.include
    assert "web_dashboard.py" in plan.include
    assert "stray_untracked.py" not in plan.include
    for rel in UNTRACKED:
        assert rel not in plan.include, rel


@pytest.mark.parametrize("rel", [
    "tests/test_a.py", "tests/conftest.py", "docs/A.md", "ops/loop/thing.py",
    "ops/fleet_kit/fleet_x.py", ".github/workflows/ci.yml",
    "agents/daemon_slayer/tests/test_ds.py", "CLAUDE.md",
    "ops/install_startup.bat", "ops/autostart_on_login.bat",
    "scripts/kill.bat", "scripts/restart.bat", "data/scrape.log", ".gitignore",
    # fix round: the installers the first verifier found shipping
    "tools/install_ds_keepalive_task.ps1", "tools/install_mission_control_task.ps1",
    "tools/phase_watcher_install.ps1", "tools/install_daemon_slayer_task.ps1",
    "tools/legion_on.ps1", "tools/legion_off.ps1", "tools/legion_agent_boot.ps1",
    "tools/install_lane_widget_shortcut.ps1",
    # belt and braces beyond the git index
    "data/coach_trace.jsonl", "moon_sync_inbox/note.md", "memory/MEMORY.md",
    # Phase 3 (dev profile only) and Mission Control-only route tables
    "agents/supervisor.py", "agents/_supervisor_ephemeral.py", "agents/_minimap_bbox.py",
    "agents/agent3_testing/agent.py", "agents/state/resolved_decisions.json",
    "dashboard/routes_loop_control.py", "dashboard/routes_loop_status.py",
    # build-time tools and tool docs / agent prompts
    "tools/build_portable.py", "tools/run_packaged_smoke.py", "tools/headless-ds.md",
])
def test_dev_only_and_operator_only_paths_are_excluded_with_a_reason(rel):
    reason = bp.exclusion_reason(rel)
    assert reason, f"{rel} would ship"


@pytest.mark.parametrize("rel", [
    "main.py", "web_dashboard.py", "moon_vision_server.py", "app/__init__.py",
    "dashboard/server.py", "web/index.html", "agents/daemon_slayer/server.py",
    "data/static.json", "tools/lcu_agent.py", "ops/rc_supervisor.py",
    "requirements.txt", "start.bat", "LICENSE", "NOTICE", "agents/__init__.py",
    "tools/liveclient_relay.py", "tools/hotkey_listener.py", "core/coach_registry.py",
])
def test_runtime_paths_are_not_excluded(rel):
    assert bp.exclusion_reason(rel) is None, rel


@pytest.mark.parametrize("rel", [
    "API-Key-Claude.txt", "api-key-claude.txt", "sub/API-Key-Claude.txt",
    "API-Key-Riot.txt", "ops/local_hosts.json", "ops/moon_sync_repos.json",
    "ops/runtime/health.json", "ops/tls/rc.pem", "ops/tls/rc-key.pem",
    "logs/2026-10-26.log", "certs/x.pfx", "x/.env",
])
def test_secrets_and_runtime_state_are_excluded_even_if_tracked(rel):
    assert bp.exclusion_reason(rel), rel


def test_force_added_secret_is_still_not_bundled(fake_repo, tmp_path):
    _git(fake_repo, "add", "-f", "API-Key-Claude.txt", "ops/local_hosts.json")
    _replace_lfs_with_real(fake_repo)
    out = tmp_path / "out"
    rc = bp.build(fake_repo, out, embed="none")
    assert rc == 0
    assert not (out / "API-Key-Claude.txt").exists()
    assert not (out / "ops" / "local_hosts.json").exists()
    assert bp.verify_bundle(out) == []


def test_build_copies_the_index_and_writes_a_manifest(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none", version="9.9.9") == 0
    for rel in ("main.py", "web_dashboard.py", "app/__init__.py",
                "dashboard/server.py", "web/index.html",
                "agents/daemon_slayer/server.py", "data/static.json"):
        assert (out / rel).is_file(), rel
    for rel in ("tests", "docs", "ops/loop", "ops/fleet_kit", ".github",
                "agents/daemon_slayer/tests", "ops/runtime", "logs"):
        assert not (out / rel).exists(), rel
    for rel in ("ops/install_startup.bat", "CLAUDE.md", "stray_untracked.py",
                "data/scrape.log", "ops/tls/rc.pem", "data/cache/big.json",
                "tools/install_ds_keepalive_task.ps1", "tools/legion_on.ps1",
                "agents/supervisor.py", "agents/_supervisor_ephemeral.py"):
        assert not (out / rel).exists(), rel
    man = json.loads((out / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    assert man["bundle"] == "Amberstone"
    assert man["version"] == "9.9.9"
    assert man["files"]["main.py"] == hashlib.sha256(
        (fake_repo / "main.py").read_bytes()).hexdigest()
    assert man["excluded_counts"]
    # A shipped manifest must not leak the build machine's folder layout.
    text = json.dumps(man)
    assert str(fake_repo) not in text and str(out) not in text
    assert text.isascii()


def test_lfs_pointer_refuses_the_build_by_default(fake_repo, tmp_path):
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none") == 1
    assert not (out / "BUILD_MANIFEST.json").exists()


def test_skip_lfs_pointers_omits_and_records_them(fake_repo, tmp_path):
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none", skip_lfs_pointers=True) == 0
    rel = "data/daemon_slayer/laning_scenarios/1.0.1/laning_scenarios_sr.json"
    assert not (out / rel).exists()
    man = json.loads((out / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    assert man["lfs_pointers_skipped"] == [rel]


def test_real_lfs_content_ships(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none") == 0
    rel = "data/daemon_slayer/laning_scenarios/1.0.1/laning_scenarios_sr.json"
    assert (out / rel).is_file() and not bp.is_lfs_pointer(out / rel)


def test_git_failure_fails_closed(tmp_path):
    def broken(cmd, cwd):
        return 128, b""
    with pytest.raises(bp.BundleError):
        bp.git_index_files(tmp_path, git_runner=broken)


# --------------------------------------------------------------------------- #
# Import closure
# --------------------------------------------------------------------------- #
def test_closure_follows_absolute_relative_and_dynamic_imports(fake_repo):
    universe = frozenset(bp.git_index_files(fake_repo))
    roots = bp.closure_roots(fake_repo, universe)
    assert "coaches/x_coach.py" in roots  # parsed from MODE_COACH_MAP
    closure = bp.import_closure(fake_repo, roots, universe)
    for rel in ("app/__init__.py", "core/util.py", "core/helper.py",
                "core/late.py", "dashboard/server.py", "vision_server/__init__.py",
                "agents/daemon_slayer/server.py", "agents/daemon_slayer/__init__.py",
                "core/const_target.py",   # import_module(<module-level constant>)
                "coaches/x_coach.py", "coaches/__init__.py"):
        assert rel in closure.files, rel
    assert "dashboard/server.py: core.const_target -> core/const_target.py" in \
        closure.dynamic_imports


def test_closure_violation_fails_the_build(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    _write(fake_repo, "app/__init__.py", "from core import util\nimport ops.loop.thing\n")
    _commit(fake_repo)
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none") == 1


def test_a_registry_coach_the_rules_exclude_fails_the_build(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    _write(fake_repo, "core/coach_registry.py",
           'MODE_COACH_MAP = {"_x_mode": ("coaches.tests.x_coach", "Coach", "x.json")}\n')
    _write(fake_repo, "coaches/tests/__init__.py", "")
    _write(fake_repo, "coaches/tests/x_coach.py", "")
    _commit(fake_repo, "coaches/tests/__init__.py", "coaches/tests/x_coach.py")
    assert bp.build(fake_repo, tmp_path / "out", embed="none") == 1


def test_an_unparseable_registry_fails_closed(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    _write(fake_repo, "core/coach_registry.py", "MODE_COACH_MAP = build_map()\n")
    _commit(fake_repo)
    with pytest.raises(bp.BundleError):
        bp.registry_roots(fake_repo, frozenset(bp.git_index_files(fake_repo)))
    assert bp.build(fake_repo, tmp_path / "out", embed="none") == 1


def test_real_repo_closure_holds_the_registry_coaches():
    """app/_game_lifecycle.py loads these through import_module(mp), which no
    static walk can read; they reach the closure only as registry roots."""
    index = bp.git_index_files(REPO)
    universe = frozenset(index)
    roots = bp.closure_roots(REPO, universe)
    closure = bp.import_closure(REPO, roots, universe)
    for rel in ("coaches/tft_coach.py", "coaches/arena_coach.py",
                "coaches/brawl_coach.py", "coaches/aram_coach.py"):
        assert rel in roots and rel in closure.files, rel


def test_closure_entries_cover_the_plan_named_processes():
    need = {"main.py", "web_dashboard.py", "moon_vision_server.py",
            "tools/lcu_agent.py", "tools/liveclient_relay.py",
            "tools/hotkey_listener.py"}
    assert need <= set(bp.CLOSURE_ENTRIES)


def test_real_repo_plan_holds_the_import_closure_and_no_secret():
    """The acceptance criterion on THIS tree, measured from its git index."""
    index = bp.git_index_files(REPO)
    assert len(index) > 1000  # an empty index would pass every check below
    plan = bp.plan_bundle(REPO, index)
    included = set(plan.include) | set(plan.lfs_pointers)
    closure = bp.import_closure(REPO, bp.closure_roots(REPO, frozenset(index)),
                                frozenset(index))
    assert len(closure.files) > 100
    missing = sorted(closure.files - included)
    assert not missing, f"import closure files the bundle would omit: {missing}"
    for rel in ("main.py", "web_dashboard.py", "moon_vision_server.py",
                "app/__init__.py", "dashboard/server.py", "web/index.html",
                "agents/daemon_slayer/server.py", "tools/start_daemon_slayer.py"):
        assert rel in included, rel
    for rel in included:
        assert not rel.startswith(("ops/runtime/", "tests/", "docs/",
                                   "ops/loop/", "ops/fleet_kit/", ".github/")), rel
        assert rel.rsplit("/", 1)[-1].lower() != "api-key-claude.txt", rel
    assert "ops/install_startup.bat" not in included
    # M6: the names the old hand-kept list carried no longer exist anywhere.
    for gone in ("coaching_timestamps.py", "run_watchdog.bat", "config/rc_config.json"):
        assert gone not in index


# --------------------------------------------------------------------------- #
# Never at boot: the boot-signature content scan
# --------------------------------------------------------------------------- #
def test_no_tracked_file_with_a_boot_signature_ships():
    """Fails if ANY tracked file that would ship carries a scheduled-task or
    boot signature the allow-list does not name (derived by content, not by
    a hand list of installer names)."""
    index = bp.git_index_files(REPO)
    plan = bp.plan_bundle(REPO, index)
    hits = bp.boot_signature_hits(REPO, plan.include)
    assert bp.boot_violations(hits) == []
    # The scan is live: the excluded installers DO carry signatures.
    excluded = [rel for rels in plan.excluded.values() for rel in rels]
    every = bp.boot_signature_hits(REPO, excluded)
    for rel in ("tools/install_ds_keepalive_task.ps1", "tools/install_mission_control_task.ps1",
                "tools/phase_watcher_install.ps1", "tools/install_daemon_slayer_task.ps1",
                "tools/legion_on.ps1"):
        assert rel in every, f"{rel}: signature scan went blind"


def test_boot_allow_list_is_not_stale():
    index = bp.git_index_files(REPO)
    plan = bp.plan_bundle(REPO, index)
    hits = bp.boot_signature_hits(REPO, plan.include)
    for rel, (allowed, reason) in bp.BOOT_SCAN_ALLOW.items():
        assert reason and rel in plan.include, rel
        assert rel in hits and set(hits[rel]) == set(allowed), (rel, hits.get(rel))


@pytest.mark.parametrize("text, name", [
    ("schtasks /Run /TN X", "schtasks"),
    ('subprocess.run(["schtasks", "/Create", "/SC", "ONLOGON"])', "schtasks /Create"),
    ("Register-ScheduledTask -TaskName X", "Register-ScheduledTask"),
    ("$t = New-ScheduledTaskTrigger -Daily", "New-ScheduledTaskTrigger"),
    ("Start-ScheduledTask -TaskName X", "ScheduledTask cmdlet"),
    ("New-ScheduledTaskTrigger -AtStartup", "-AtStartup"),
    ("New-ScheduledTaskTrigger -AtLogOn", "-AtLogOn"),
    (r"Registry::HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
     "Run registry key"),
    ("key = r'Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\RunOnce'", "Run registry key"),
    (r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\x.lnk", "Startup folder"),
    ("$d = [Environment]::GetFolderPath('Startup')", "Startup folder"),
    ("explorer shell:startup", "Startup folder"),
    ("app.setLoginItemSettings({openAtLogin: true})", "login item"),
    ('CreateObject("Schedule.Service")', "Task Scheduler COM"),
])
def test_each_boot_signature_is_detected(tmp_path, text, name):
    (tmp_path / "f.txt").write_text(text + "\n", encoding="utf-8")
    assert name in bp.boot_signature_hits(tmp_path, ["f.txt"]).get("f.txt", [])


def test_plain_words_are_not_boot_signatures(tmp_path):
    (tmp_path / "f.py").write_text("# on startup the app logs on and runs tasks\n",
                                   encoding="utf-8")
    assert bp.boot_signature_hits(tmp_path, ["f.py"]) == {}


def test_an_unlisted_installer_fails_the_build(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    _write(fake_repo, "core/autorun.py",
           "CMD = ['schtasks', '/Create', '/SC', 'ONLOGON', '/TN', 'X']\n")
    _write(fake_repo, "scripts/add_task.ps1",
           "Register-ScheduledTask -Trigger (New-ScheduledTaskTrigger -AtLogOn)\n")
    _commit(fake_repo, "core/autorun.py", "scripts/add_task.ps1")
    assert bp.build(fake_repo, tmp_path / "out", embed="none") == 1


def test_an_allow_listed_file_gaining_a_new_signature_fails():
    hits = {"ops/rc_supervisor.py": ["schtasks", "-AtLogOn"]}
    assert bp.boot_violations(hits) == ["ops/rc_supervisor.py: -AtLogOn"]
    assert bp.boot_violations({"ops/rc_supervisor.py": ["schtasks"]}) == []


# --------------------------------------------------------------------------- #
# Clean source
# --------------------------------------------------------------------------- #
def test_a_modified_included_file_refuses_the_build(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    _write(fake_repo, "core/helper.py", "X = 2\n")
    assert bp.build(fake_repo, tmp_path / "out", embed="none") == 1
    out = tmp_path / "out2"
    assert bp.build(fake_repo, out, embed="none", allow_dirty=True) == 0
    man = json.loads((out / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    assert man["dirty_included"] == ["core/helper.py"]
    assert man["allow_dirty"] is True and man["source_included_clean"] is False


def test_a_modified_excluded_file_does_not_block(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    _write(fake_repo, "docs/A.md", "# changed\n")
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none") == 0
    man = json.loads((out / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    assert man["source_tree_clean"] is False and man["source_included_clean"] is True
    assert man["dirty_included"] == []


def test_git_status_failure_refuses_the_build(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)

    def runner(cmd, cwd):
        if cmd[1] == "status":
            return 128, b""
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True)
        return proc.returncode, proc.stdout
    assert bp.build(fake_repo, tmp_path / "out", embed="none", git_runner=runner) == 1


def test_porcelain_parse_handles_renames(tmp_path):
    out = b" M a.py\0R  new.py\0old.py\0A  added.py\0"
    got = bp.modified_tracked_files(tmp_path, git_runner=lambda cmd, cwd: (0, out))
    assert got == ["a.py", "added.py", "new.py"]


# --------------------------------------------------------------------------- #
# Post-build verification and output-dir safety
# --------------------------------------------------------------------------- #
def test_verify_bundle_flags_a_planted_unnamed_installer(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none") == 0
    (out / "tools" / "sneaky.ps1").write_text(
        "Register-ScheduledTask -TaskName X\n", encoding="utf-8")
    problems = "\n".join(bp.verify_bundle(out))
    assert "tools/sneaky.ps1" in problems
def test_verify_bundle_flags_planted_problems(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none") == 0
    (out / "API-Key-Claude.txt").write_text("x", encoding="utf-8")
    (out / "ops" / "runtime").mkdir(parents=True)
    (out / "ops" / "runtime" / "health.json").write_text("{}", encoding="utf-8")
    (out / "ops" / "install_startup.bat").write_text("x", encoding="utf-8")
    (out / "data" / "p.json").write_text(LFS_POINTER, encoding="utf-8")
    problems = "\n".join(bp.verify_bundle(out))
    for needle in ("API-Key-Claude.txt", "ops/runtime", "install_startup.bat", "data/p.json"):
        assert needle in problems, needle


def test_output_dir_safety(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    assert bp.build(fake_repo, fake_repo, embed="none") == 1
    assert bp.build(fake_repo, fake_repo.parent, embed="none") == 1
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("irreplaceable", encoding="utf-8")
    assert bp.build(fake_repo, foreign, embed="none") == 1
    assert (foreign / "keep.txt").read_text(encoding="utf-8") == "irreplaceable"
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none") == 0
    assert bp.build(fake_repo, out, embed="none") == 0  # a previous build is replaceable


def test_dry_run_writes_nothing(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none", dry_run=True) == 2
    assert not out.exists()


# --------------------------------------------------------------------------- #
# Embedded runtime (tools/build_python_embed.py)
# --------------------------------------------------------------------------- #
def test_default_pin_is_https_python_org_with_a_full_sha256():
    pin = bpe.PINS[bpe.DEFAULT_VERSION]
    assert pin.url.startswith("https://www.python.org/ftp/python/")
    assert pin.version in pin.url
    assert len(pin.sha256) == 64 and int(pin.sha256, 16) >= 0
    assert pin.major_minor == (3, 14)  # plan section 3.5: the dev tree's 3.14
    assert pin.pth_name == "python314._pth"


def test_fetch_verifies_the_sha256(tmp_path, fake_pin):
    pin, data = fake_pin
    calls: list = []
    got = bpe.fetch_embed_zip(pin, tmp_path / "cache", opener=_opener_for(data, calls))
    assert got.read_bytes() == data and calls == [pin.url]
    # Cached and still matching: no second download.
    bpe.fetch_embed_zip(pin, tmp_path / "cache", opener=_opener_for(data, calls))
    assert calls == [pin.url]


def test_fetch_refuses_a_hash_mismatch_and_keeps_nothing(tmp_path, fake_pin):
    pin, data = fake_pin
    with pytest.raises(bpe.EmbedError):
        bpe.fetch_embed_zip(pin, tmp_path / "cache",
                            opener=_opener_for(data + b"tampered", []))
    assert not any((tmp_path / "cache").glob("*.zip"))


def test_fetch_refuses_a_non_https_pin(tmp_path, fake_pin):
    pin, data = fake_pin
    bad = bpe.EmbedPin(version=pin.version, url=pin.url.replace("https:", "http:"),
                       sha256=pin.sha256)
    with pytest.raises(bpe.EmbedError):
        bpe.fetch_embed_zip(bad, tmp_path / "cache", opener=_opener_for(data, []))


def test_local_zip_is_verified_too(tmp_path, fake_pin):
    pin, data = fake_pin
    z = tmp_path / "local.zip"
    z.write_bytes(data + b"x")
    with pytest.raises(bpe.EmbedError):
        bpe.fetch_embed_zip(pin, tmp_path / "cache", local_zip=z)


def test_host_python_must_match_the_pin(fake_pin):
    pin, _ = fake_pin
    with pytest.raises(bpe.EmbedError):
        bpe.check_host_python(pin, version_info=(3, 11, 9))
    bpe.check_host_python(pin, version_info=(3, 14, 2))


def test_pip_command_installs_the_hashed_lock_for_the_pinned_runtime(tmp_path, fake_pin):
    pin, _ = fake_pin
    cmd = bpe.pip_install_command(pin, tmp_path / "requirements.txt",
                                  tmp_path / "sp", "py.exe")
    assert "--require-hashes" in cmd and "--only-binary=:all:" in cmd
    assert cmd[cmd.index("-r") + 1] == str(tmp_path / "requirements.txt")
    assert cmd[cmd.index("--target") + 1] == str(tmp_path / "sp")
    assert cmd[cmd.index("--python-version") + 1] == "3.14"
    assert cmd[cmd.index("--platform") + 1] == "win_amd64"
    assert "--isolated" in cmd


def test_build_embed_defaults_strip_ffmpeg_and_keep_certifi(fake_repo, tmp_path, fake_pin):
    pin, data = fake_pin
    target = tmp_path / "python-embed"
    pip_calls: list = []
    stamp = bpe.build_embed(
        target, requirements=fake_repo / "requirements.txt", pin=pin,
        cache_dir=tmp_path / "cache", opener=_opener_for(data, []),
        runner=_fake_pip(pip_calls), version_info=(3, 14, 4))
    sp = target / "Lib" / "site-packages"
    assert not list(sp.rglob("opencv_videoio_ffmpeg*.dll"))
    assert (sp / "certifi" / "cacert.pem").is_file()
    assert stamp["opencv_ffmpeg"]["stripped"] is True
    assert stamp["opencv_ffmpeg"]["removed"] == ["cv2/opencv_videoio_ffmpeg500_64.dll"]
    assert stamp["certifi"]["included"] is True
    assert stamp["requirements_sha256"] == bpe.sha256_file(fake_repo / "requirements.txt")
    pth = (target / "python314._pth").read_text(encoding="utf-8").splitlines()
    assert "Lib\\site-packages" in pth and ".." in pth and "import site" in pth
    names = {p["name"]: p for p in stamp["packages"]}
    assert names["certifi"]["copyleft"] is True
    assert names["anthropic"]["copyleft"] is False
    assert stamp["cpython"]["sha256"] == pin.sha256
    assert (target / bpe.STAMP_NAME).is_file()
    assert bpe.verify_embed_dir(target, requirements=fake_repo / "requirements.txt",
                                pin=pin) == []


def test_build_embed_options_keep_ffmpeg_and_drop_certifi(fake_repo, tmp_path, fake_pin):
    pin, data = fake_pin
    target = tmp_path / "python-embed"
    opts = bpe.EmbedOptions(strip_opencv_ffmpeg=False, include_certifi=False)
    stamp = bpe.build_embed(
        target, requirements=fake_repo / "requirements.txt", pin=pin, options=opts,
        cache_dir=tmp_path / "cache", opener=_opener_for(data, []),
        runner=_fake_pip([]), version_info=(3, 14, 4))
    sp = target / "Lib" / "site-packages"
    assert list(sp.rglob("opencv_videoio_ffmpeg*.dll"))
    assert not (sp / "certifi").exists()
    assert not list(sp.glob("certifi-*.dist-info"))
    assert stamp["opencv_ffmpeg"]["stripped"] is False
    assert stamp["certifi"]["included"] is False
    assert "certifi" not in {p["name"] for p in stamp["packages"]}


def test_licence_inventory_reads_expression_then_short_field_then_classifiers(tmp_path):
    sp = tmp_path / "sp"
    _write_dist(sp, "a", "1", "License-Expression: LGPL-2.1-or-later")
    _write_dist(sp, "b", "1", "License: BSD-3-Clause")
    # json5 0.15.0 shape: a pasted multi-line text whose first line names no licence.
    _write_dist(sp, "c", "1", "License: Files: Everything except the benchmarks.\n"
                              " Copyright: 2014 someone\n"
                              "Classifier: License :: OSI Approved :: Apache Software License")
    _write_dist(sp, "d", "1", "Summary: nothing declared")
    rows = {r["name"]: r for r in bpe.license_inventory(sp)}
    assert rows["a"]["licence"] == "LGPL-2.1-or-later" and rows["a"]["copyleft"]
    assert rows["b"]["licence"] == "BSD-3-Clause" and not rows["b"]["copyleft"]
    assert rows["c"]["licence"] == "Apache Software License"
    assert rows["d"]["licence"] == "UNDECLARED"


def test_pip_failure_fails_the_embed_build(fake_repo, tmp_path, fake_pin):
    pin, data = fake_pin
    with pytest.raises(bpe.EmbedError):
        bpe.build_embed(tmp_path / "pe", requirements=fake_repo / "requirements.txt",
                        pin=pin, cache_dir=tmp_path / "cache",
                        opener=_opener_for(data, []), runner=lambda cmd: 1,
                        version_info=(3, 14, 4))


def test_extract_refuses_zip_slip(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "x")
    z = tmp_path / "evil.zip"
    z.write_bytes(buf.getvalue())
    with pytest.raises(bpe.EmbedError):
        bpe.extract_embed(z, tmp_path / "t")
    assert not (tmp_path / "evil.txt").exists()


def test_verify_embed_dir_refuses_a_stale_lock_or_a_kept_dll(fake_repo, tmp_path, fake_pin):
    pin, data = fake_pin
    target = tmp_path / "python-embed"
    bpe.build_embed(target, requirements=fake_repo / "requirements.txt", pin=pin,
                    cache_dir=tmp_path / "cache", opener=_opener_for(data, []),
                    runner=_fake_pip([]), version_info=(3, 14, 4))
    other = tmp_path / "requirements-other.txt"
    other.write_text("changed\n", encoding="utf-8")
    assert bpe.verify_embed_dir(target, requirements=other, pin=pin)
    (target / "Lib" / "site-packages" / "cv2" / "opencv_videoio_ffmpeg500_64.dll"
     ).write_bytes(b"MZ")
    assert bpe.verify_embed_dir(target, requirements=fake_repo / "requirements.txt",
                                pin=pin)
    assert bpe.verify_embed_dir(tmp_path / "nothing-here",
                                requirements=fake_repo / "requirements.txt", pin=pin)


def test_bundle_build_with_the_embedded_runtime(fake_repo, tmp_path, fake_pin):
    _replace_lfs_with_real(fake_repo)
    pin, data = fake_pin
    out = tmp_path / "out"
    rc = bp.build(fake_repo, out, embed="build", embed_pin=pin,
                  embed_cache=tmp_path / "cache", opener=_opener_for(data, []),
                  pip_runner=_fake_pip([]), host_version=(3, 14, 4))
    assert rc == 0
    assert (out / "python-embed" / "python.exe").is_file()
    assert (out / "python-embed" / bpe.STAMP_NAME).is_file()
    man = json.loads((out / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    assert man["python"]["mode"] == "build"
    assert man["python"]["cpython"]["version"] == "3.14.4"
    steps = man["licence_steps"]
    assert steps["opencv_ffmpeg_dll"]["stripped"] is True
    assert steps["certifi"]["included"] is True
    assert "python-embed/python.exe" not in man["files"]  # runtime listed by stamp
    assert bp.verify_bundle(out) == []


def test_bundle_build_from_a_prebuilt_embed_dir(fake_repo, tmp_path, fake_pin):
    _replace_lfs_with_real(fake_repo)
    pin, data = fake_pin
    pre = tmp_path / "prebuilt"
    bpe.build_embed(pre, requirements=fake_repo / "requirements.txt", pin=pin,
                    cache_dir=tmp_path / "cache", opener=_opener_for(data, []),
                    runner=_fake_pip([]), version_info=(3, 14, 4))
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="dir", embed_dir=pre, embed_pin=pin) == 0
    assert (out / "python-embed" / "python.exe").is_file()
    # A prebuilt runtime from a different lock is refused.
    (fake_repo / "requirements.txt").write_text("other\n", encoding="utf-8")
    _commit(fake_repo)
    assert bp.build(fake_repo, tmp_path / "out2", embed="dir", embed_dir=pre,
                    embed_pin=pin) == 1


# --------------------------------------------------------------------------- #
# Artifacts: Amberstone-* zip and installer staging
# --------------------------------------------------------------------------- #
def test_package_names_and_root_folder(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    staged = tmp_path / "staged"
    assert bp.build(fake_repo, staged, embed="none") == 0
    dist = tmp_path / "dist"
    rc = pp.package(out_dir=dist, version="1.2.3", staged_dir=staged)
    assert rc == 0
    archive = dist / "Amberstone-portable-1.2.3.zip"
    assert archive.is_file()
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert all(n.startswith("Amberstone-portable/") for n in names)
    assert "Amberstone-portable/main.py" in names
    assert "Amberstone-portable/PACKAGE_MANIFEST.json" in names


def test_package_refuses_a_staged_dir_with_a_secret(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    staged = tmp_path / "staged"
    assert bp.build(fake_repo, staged, embed="none") == 0
    (staged / "API-Key-Claude.txt").write_text("x", encoding="utf-8")
    dist = tmp_path / "dist"
    assert pp.package(out_dir=dist, version="1", staged_dir=staged) == 1
    assert not list(dist.glob("*.zip")) if dist.exists() else True


def test_installer_staging_uses_the_amberstone_archive(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    archive = dist / "Amberstone-portable-1.2.3.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Amberstone-portable/main.py", "")
    assert bi.find_archive(dist) == archive
    out = tmp_path / "installer"
    assert bi.build(out, dry=False, archive_override=None, dist_dir=dist) == 0
    setup = (out / "setup.bat").read_text(encoding="utf-8")
    assert "Amberstone-portable" in setup
    # Never-at-boot (plan intent 3): the setup creates no boot hook.
    for banned in ("Startup", "schtasks", "CurrentVersion\\Run", "RunOnce"):
        assert banned not in setup, banned
    man = json.loads((out / "INSTALL_MANIFEST.json").read_text(encoding="utf-8"))
    assert man["zip_root_folder"] == "Amberstone-portable"


def _archive_in(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / "Amberstone-portable-1.0.0.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Amberstone-portable/main.py", "")
    return archive


def test_installer_refuses_to_wipe_a_foreign_folder(tmp_path):
    archive = _archive_in(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("irreplaceable", encoding="utf-8")
    assert bi.build(foreign, archive_override=archive) == 1
    assert (foreign / "keep.txt").read_text(encoding="utf-8") == "irreplaceable"
    # The repo root, a folder holding it, and the archive's own folder too.
    assert bi.build(REPO, archive_override=archive) == 1
    assert bi.build(REPO.parent, archive_override=archive) == 1
    assert bi.build(archive.parent, archive_override=archive) == 1
    assert archive.is_file()


def test_installer_replaces_only_its_own_previous_output(tmp_path):
    archive = _archive_in(tmp_path)
    out = tmp_path / "installer"
    assert bi.build(out, archive_override=archive) == 0
    assert bi.build(out, archive_override=archive) == 0
    (out / "INSTALL_MANIFEST.json").write_text('{"installer_tool": "other"}',
                                               encoding="utf-8")
    assert bi.build(out, archive_override=archive) == 1


# --------------------------------------------------------------------------- #
# tools/run_packaged_smoke.py
# --------------------------------------------------------------------------- #
def test_smoke_finds_only_amberstone_archives(tmp_path):
    from tools import run_packaged_smoke as rps
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "RiotCommander-portable-20260101.zip").write_bytes(b"old")
    assert rps.find_archive(dist) is None
    new = dist / "Amberstone-portable-1.zip"
    new.write_bytes(b"new")
    assert rps.find_archive(dist) == new


def test_smoke_requires_nothing_the_builder_excludes():
    from tools import run_packaged_smoke as rps
    for rel, _label in rps.REQUIRED_FILES:
        if rel in (bp.MANIFEST_NAME, pp.PACKAGE_MANIFEST, "PREREQUISITES.md") or \
                rel.startswith("python-embed/"):
            continue  # generated by the build, not taken from the index
        assert bp.exclusion_reason(rel) is None, rel
        assert (REPO / rel).is_file(), rel
    names = {rel for rel, _ in rps.REQUIRED_FILES}
    assert "scripts/restart_clean.bat" not in names
    assert "ops/rc_league_watcher.ps1" not in names


def test_smoke_structure_check_passes_a_complete_entry_set():
    from tools import run_packaged_smoke as rps
    rps.reset()
    root = "Amberstone-portable/"
    entries = {root + rel for rel, _ in rps.REQUIRED_FILES}
    entries |= {root + tree + "x" for tree in rps.REQUIRED_TREES}
    assert rps.check_archive_structure(entries) == "Amberstone-portable"
    assert rps.failures() == []
    rps.reset()
    assert rps.check_archive_structure({"RiotCommander-portable/main.py"}) == ""
    assert rps.failures()


def test_smoke_tolerates_bootstrap_issues_about_excluded_files_only():
    from tools import run_packaged_smoke as rps
    # The exact lines bootstrap_env_check printed against a live bundle.
    for line in ("ISSUE: scripts/restart_clean.bat missing",
                 "ISSUE: API-Key-Claude.txt  [REQUIRED]",
                 "ISSUE: config/coach_settings.json  [config]",
                 "ISSUE: audit/ (proof bundles, baseline outputs)",
                 "ISSUE: ops/runtime/ (supervisor artifacts)"):
        assert rps._tolerated_issue(line), line
    assert rps._tolerated_issue("ISSUE: main.py -- missing") is None
    assert rps._tolerated_issue("ISSUE: core/ (source)") is None
    assert rps._tolerated_issue("ISSUE: something else broke") is None


def test_smoke_exclusion_check_uses_the_builder_verify(fake_repo, tmp_path):
    from tools import run_packaged_smoke as rps
    _replace_lfs_with_real(fake_repo)
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none") == 0
    z = tmp_path / "a.zip"
    z.write_bytes(b"0" * 16)
    rps.reset()
    rps.check_exclusions(out, z)
    assert rps.failures() == []
    (out / "ops" / "install_startup.bat").write_text("x", encoding="utf-8")
    rps.reset()
    rps.check_exclusions(out, z)
    assert rps.failures()


@pytest.mark.parametrize("rel", [
    "tools/build_portable.py", "tools/build_python_embed.py",
    "tools/package_portable.py", "tools/build_installer.py",
    "tools/run_packaged_smoke.py",
])
def test_retired_brand_is_gone_and_source_is_ascii_lf(rel):
    raw = (REPO / rel).read_bytes()
    assert raw.isascii() and b"\r" not in raw
    assert b"RiotCommander" not in raw and b"Riot Commander" not in raw
