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
    "dashboard/server.py": "import importlib\nimportlib.import_module('core.late')\n",
    "core/late.py": "",
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
    "ops/rc_supervisor.py": "import json\n",
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
    # Written after the add: on disk, never in the index (the gitignored ones
    # could not be added anyway; stray_untracked.py simply never was).
    for rel, text in UNTRACKED.items():
        _write(root, rel, text)
    return root


def _replace_lfs_with_real(root: Path) -> None:
    _write(root, "data/daemon_slayer/laning_scenarios/1.0.1/laning_scenarios_sr.json",
           '{"schema": "laning_scenarios/v4"}\n')


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
])
def test_dev_only_and_operator_only_paths_are_excluded_with_a_reason(rel):
    reason = bp.exclusion_reason(rel)
    assert reason, f"{rel} would ship"


@pytest.mark.parametrize("rel", [
    "main.py", "web_dashboard.py", "moon_vision_server.py", "app/__init__.py",
    "dashboard/server.py", "web/index.html", "agents/daemon_slayer/server.py",
    "data/static.json", "tools/lcu_agent.py", "ops/rc_supervisor.py",
    "requirements.txt", "start.bat", "LICENSE", "NOTICE",
    "agents/agent3_testing/agent.py",
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
                "data/scrape.log", "ops/tls/rc.pem", "data/cache/big.json"):
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
def test_closure_follows_absolute_relative_and_literal_dynamic_imports(fake_repo):
    universe = frozenset(bp.git_index_files(fake_repo))
    closure = bp.import_closure(fake_repo, bp.CLOSURE_ENTRIES, universe)
    for rel in ("app/__init__.py", "core/util.py", "core/helper.py",
                "core/late.py", "dashboard/server.py", "vision_server/__init__.py",
                "agents/daemon_slayer/server.py", "agents/daemon_slayer/__init__.py"):
        assert rel in closure.files, rel


def test_closure_violation_fails_the_build(fake_repo, tmp_path):
    _replace_lfs_with_real(fake_repo)
    _write(fake_repo, "app/__init__.py", "from core import util\nimport ops.loop.thing\n")
    _git(fake_repo, "add", "-A")
    out = tmp_path / "out"
    assert bp.build(fake_repo, out, embed="none") == 1


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
    closure = bp.import_closure(REPO, bp.CLOSURE_ENTRIES, frozenset(index))
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
# Post-build verification and output-dir safety
# --------------------------------------------------------------------------- #
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
    _git(fake_repo, "add", "-A")
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


@pytest.mark.parametrize("rel", [
    "tools/build_portable.py", "tools/build_python_embed.py",
    "tools/package_portable.py", "tools/build_installer.py",
])
def test_retired_brand_is_gone_and_source_is_ascii_lf(rel):
    raw = (REPO / rel).read_bytes()
    assert raw.isascii() and b"\r" not in raw
    assert b"RiotCommander" not in raw and b"Riot Commander" not in raw
