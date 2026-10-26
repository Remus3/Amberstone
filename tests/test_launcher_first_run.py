"""PKG-1b: first-run provisioning of per-install secrets (PACKAGING_PLAN 3.2).

A fresh bundle has no config/vision_token.txt, so `import app` dies at
core/vision_token.py import time, and nothing created the per-install dashboard
token or the deploy key. ops/launcher/first_run.py creates each missing secret
once, owned-mode only, before the service host spawns anything:

  vision token  config/vision_token.txt         (core/vision_token.py:69 reads it)
  dash token    ops/runtime/dash_token.txt      (stored; exported as RC_DASH_TOKEN
                                                 only when the profile's
                                                 dash_token_gate is on - off by
                                                 default, PACKAGING_PLAN V3)
  deploy key    ops/runtime/deploy_request.key  (created by the deploy worker's
                                                 own --init-key / ensure_key,
                                                 ops/rc_transactional_deploy.py:108)

Every test root is tmp_path; nothing here reads or writes the live config/ or
ops/runtime/. Every secret value is generated at run time, never a literal.
"""
from __future__ import annotations

import ast
import errno
import importlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from ops.launcher import first_run as fr
from ops.launcher import service_host as sh

ROOT = Path(__file__).resolve().parent.parent
FIRST_RUN_PY = ROOT / "ops" / "launcher" / "first_run.py"
HOST_PY = ROOT / "ops" / "launcher" / "service_host.py"
SERVICES_JSON = ROOT / "ops" / "launcher" / "services.json"
DEPLOY_PY = ROOT / "ops" / "rc_transactional_deploy.py"
NO_WINDOW = 0x08000000

WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL / job object")
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file mode")


# --------------------------------------------------------------- helpers


class Recorder:
    """A fake `restrict` (ACL) callable: records each path; `result` is a
    bool or a callable(path) -> bool."""

    def __init__(self, result=True, side_effect=None):
        self.calls = []
        self.result = result
        self.side_effect = side_effect

    def __call__(self, path):
        self.calls.append(Path(path))
        if self.side_effect is not None:
            self.side_effect(Path(path))
        return self.result(Path(path)) if callable(self.result) else self.result


def _size(path: Path):
    try:
        return path.stat().st_size if path.is_file() else "dir"
    except OSError:
        return None


class Timeline:
    """One ordered event list for icacls calls (through the REAL
    restrict_to_current_user with a fake run) and secret writes (a wrapper
    around first_run._write_secret). Each icacls event records the size of
    its target at that moment, so "restricted before any secret byte" is
    checked directly."""

    SID = "S-1-5-21-1000-2000-3000-1001"

    def __init__(self, monkeypatch, rc=0):
        self.events = []
        self.rc = rc
        real_write = fr._write_secret

        def write(path, data):
            self.events.append(("write", Path(path)))
            real_write(path, data)

        monkeypatch.setattr(fr, "_write_secret", write)

    def run(self, argv, **kw):
        target = Path(argv[1])
        self.events.append(("icacls", target, _size(target)))
        return subprocess.CompletedProcess(argv, self.rc(target) if callable(self.rc) else self.rc)

    def restrict(self, path):
        return fr.restrict_to_current_user(path, run=self.run, windows=True, sid=self.SID)

    def for_name(self, prefix):
        return [e for e in self.events if e[1].name.startswith(prefix)]


def make_root(tmp_path: Path, *, deploy_module: bool = False) -> Path:
    root = tmp_path / "backend"
    (root / "ops").mkdir(parents=True)
    if deploy_module:
        shutil.copyfile(DEPLOY_PY, root / "ops" / "rc_transactional_deploy.py")
    return root


def vision_path(root: Path) -> Path:
    return root / "config" / "vision_token.txt"


def dash_path(root: Path) -> Path:
    return root / "ops" / "runtime" / "dash_token.txt"


def key_path(root: Path) -> Path:
    return root / "ops" / "runtime" / "deploy_request.key"


def first_line(path: Path) -> str:
    return path.read_text(encoding="ascii").splitlines()[0].strip()


def by_name(report) -> dict:
    return {r.name: r for r in report.results}


def provision(root, **kw):
    kw.setdefault("environ", {})
    kw.setdefault("restrict", Recorder())
    return fr.provision(root, **kw)


def snapshot(paths):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}


def leftover_tmp(root: Path) -> list:
    return [p for p in root.rglob("*.tmp")]


# ------------------------------------------------------- vision token


def test_vision_token_is_created_where_and_how_the_reader_reads_it(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    report = provision(root)
    res = by_name(report)["vision_token"]
    assert res.state == "created"
    path = vision_path(root)
    assert res.path == path
    raw = path.read_bytes()
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1, "one line, LF"
    token = first_line(path)
    assert re.fullmatch(r"[0-9a-f]{32}", token), "secrets.token_hex(16), the rotation recipe"
    # The REAL reader resolves it: core/vision_token.py _resolve (:91), file
    # branch (:96-99), printable check (:83). Its import-time resolution is
    # covered by tests/conftest.py's RC_VISION_TOKEN test default (RM-383).
    vt = sys.modules.get("core.vision_token") or importlib.import_module("core.vision_token")
    monkeypatch.setattr(vt, "_CONFIG_PATH", path)
    monkeypatch.delenv("RC_VISION_TOKEN", raising=False)
    assert vt._resolve() == (token, "config")


def test_vision_token_location_is_the_readers_constant():
    # core/vision_token.py:69 builds the path from the repo root.
    text = (ROOT / "core" / "vision_token.py").read_text(encoding="utf-8")
    assert '"config" / "vision_token.txt"' in text
    assert fr.VISION_TOKEN_REL == ("config", "vision_token.txt")
    assert fr.VISION_TOKEN_ENV == "RC_VISION_TOKEN"
    assert 'os.environ.get("RC_VISION_TOKEN")' in text


def test_an_env_vision_token_wins_and_no_file_is_written(tmp_path):
    root = make_root(tmp_path)
    report = provision(root, environ={"RC_VISION_TOKEN": secrets.token_hex(16)})
    assert by_name(report)["vision_token"].state == "env"
    assert not vision_path(root).exists()


def test_a_blank_env_vision_token_does_not_count(tmp_path):
    root = make_root(tmp_path)
    report = provision(root, environ={"RC_VISION_TOKEN": "   "})
    assert by_name(report)["vision_token"].state == "created"


def test_an_invalid_existing_vision_token_is_reported_never_rewritten(tmp_path):
    root = make_root(tmp_path)
    path = vision_path(root)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"has a space\n")
    before = snapshot([path])
    restrict = Recorder()
    report = provision(root, restrict=restrict)
    res = by_name(report)["vision_token"]
    assert res.state == "invalid"
    assert snapshot([path]) == before
    assert path not in restrict.calls
    assert any("vision_token" in line and "invalid" in line for line in report.lines(root))


# ------------------------------------------------------- dash token


def test_dash_token_is_stored_per_install_and_not_exported_by_default(tmp_path):
    root = make_root(tmp_path)
    report = provision(root)
    res = by_name(report)["dash_token"]
    assert res.state == "created" and res.path == dash_path(root)
    assert re.fullmatch(r"[0-9a-f]{64}", first_line(dash_path(root)))
    assert report.env == {}, "the gate is OFF unless the profile turns it on"


def test_dash_token_gate_on_exports_the_stored_token(tmp_path):
    root = make_root(tmp_path)
    report = provision(root, dash_token_gate=True)
    token = first_line(dash_path(root))
    assert report.env == {"RC_DASH_TOKEN": token}


def test_dash_token_gate_on_reuses_an_existing_token(tmp_path):
    root = make_root(tmp_path)
    existing = secrets.token_hex(32)
    dash_path(root).parent.mkdir(parents=True)
    dash_path(root).write_text(existing + "\n", encoding="ascii")
    report = provision(root, dash_token_gate=True)
    assert by_name(report)["dash_token"].state == "present"
    assert report.env == {"RC_DASH_TOKEN": existing}


def test_dash_token_gate_on_with_an_invalid_token_exports_nothing(tmp_path):
    root = make_root(tmp_path)
    dash_path(root).parent.mkdir(parents=True)
    dash_path(root).write_bytes(b"\n")
    report = provision(root, dash_token_gate=True)
    assert by_name(report)["dash_token"].state == "invalid"
    assert report.env == {}
    assert any("ungated" in line for line in report.lines(root))


# ------------------------------------------------------- deploy key


def test_deploy_key_is_the_workers_key_in_the_workers_format(tmp_path):
    from ops import rc_transactional_deploy as td

    root = make_root(tmp_path)
    restrict = Recorder()
    report = provision(root, restrict=restrict)
    res = by_name(report)["deploy_key"]
    assert res.state == "created", res
    key = key_path(root)
    assert res.path == key
    # The worker's own ensure_key output (ops/rc_transactional_deploy.py:115)
    # is the format reference: the same 64-hex value. Its text-mode
    # write_text ends the line CRLF on Windows; _read_key strips (:96), and
    # this tree writes LF, so only the stripped value has to match.
    ref = td.ensure_key(tmp_path / "ref" / "deploy_request.key")
    hex64 = re.compile(r"[0-9a-f]{64}")
    assert hex64.fullmatch(ref.read_text(encoding="ascii").strip())
    assert re.fullmatch(rb"[0-9a-f]{64}\n", key.read_bytes()), "one line, LF"
    # The worker reads, signs and verifies with it (:94 _read_key, :125, :133).
    signed = td.sign_request({"request_id": "pkg1b", "files": []}, key_path=key)
    td.verify_request(signed, key_path=key)
    assert td.DEFAULT_KEY_PATH.relative_to(ROOT) == Path(*fr.DEPLOY_KEY_REL), \
        "the worker verifies with exactly this file"


def test_deploy_key_is_restricted_before_a_key_byte_exists(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    tl = Timeline(monkeypatch)
    report = provision(root, restrict=tl.restrict)
    assert by_name(report)["deploy_key"].state == "created"
    events = tl.for_name("deploy_request.key")
    assert [e[0] for e in events] == ["icacls", "write"], events
    assert events[0][2] == 0, "the scratch was empty when its ACL was set"
    assert events[1][1] == events[0][1], "the secret went into the restricted scratch"


def test_provisioning_spawns_no_deploy_worker(tmp_path, monkeypatch):
    def no_spawn(*a, **k):
        raise AssertionError("no subprocess besides icacls")

    monkeypatch.setattr(fr.subprocess, "Popen", no_spawn)
    root = make_root(tmp_path, deploy_module=True)
    report = provision(root)
    assert by_name(report)["deploy_key"].state == "created"


def test_create_no_window_is_the_per_os_constant():
    assert fr.CREATE_NO_WINDOW == (NO_WINDOW if os.name == "nt" else 0)


# ------------------------------------------- never overwrite, idempotent


def _seed_all(root: Path) -> dict:
    values = {"vision": secrets.token_hex(16), "dash": secrets.token_hex(32),
              "key": secrets.token_hex(32)}
    for path, value in ((vision_path(root), values["vision"]),
                        (dash_path(root), values["dash"]),
                        (key_path(root), values["key"])):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="ascii")
    return values


@pytest.mark.parametrize("gate", [False, True])
def test_legion_with_every_secret_present_changes_nothing(tmp_path, gate):
    root = make_root(tmp_path, deploy_module=True)
    values = _seed_all(root)
    paths = [vision_path(root), dash_path(root), key_path(root)]
    before = snapshot(paths)
    restrict = Recorder()
    report = provision(root, restrict=restrict, dash_token_gate=gate)
    assert {r.name: r.state for r in report.results} == {
        "vision_token": "present", "dash_token": "present", "deploy_key": "present"}
    assert snapshot(paths) == before, "bytes and mtimes untouched"
    assert restrict.calls == [], "no ACL change"
    assert not (root / "ops" / "runtime" / "first_run").exists(), "no scratch folder made"
    assert report.env == ({"RC_DASH_TOKEN": values["dash"]} if gate else {})
    assert leftover_tmp(root) == []


def test_second_run_is_idempotent(tmp_path):
    root = make_root(tmp_path, deploy_module=True)
    first = provision(root)
    assert {r.state for r in first.results} == {"created"}
    paths = [vision_path(root), dash_path(root), key_path(root)]
    before = snapshot(paths)
    second = provision(root)
    assert {r.state for r in second.results} == {"present"}
    assert snapshot(paths) == before
    assert leftover_tmp(root) == []


def test_the_acl_is_set_on_the_scratch_file_before_it_is_published(tmp_path):
    root = make_root(tmp_path)
    seen = []
    target = vision_path(root)
    restrict = Recorder(side_effect=lambda p: seen.append((p, target.exists(), _size(p))))
    provision(root, restrict=restrict)
    scratch, existed, size = next(s for s in seen if s[0].name.startswith("vision_token.txt"))
    assert scratch != target and scratch.name.endswith(".tmp")
    assert existed is False, "restricted before the secret has its real name"
    assert size == 0, "restricted before a secret byte is in it"
    assert scratch.parent == root / "ops" / "runtime" / "first_run", \
        "a killed write leaves its scratch under the ignored ops/runtime/, never in config/"
    assert leftover_tmp(root) == []


def test_icacls_runs_before_any_secret_byte_is_written(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    tl = Timeline(monkeypatch)
    report = provision(root, restrict=tl.restrict)
    assert {r.state for r in report.results} == {"created"}
    scratch_dir = root / "ops" / "runtime" / "first_run"
    first = tl.events[0]
    assert first[:2] == ("icacls", scratch_dir) and first[2] == "dir", \
        "the scratch FOLDER is restricted before anything is created in it"
    for prefix in ("vision_token.txt", "dash_token.txt", "deploy_request.key"):
        events = tl.for_name(prefix)
        assert [e[0] for e in events] == ["icacls", "write"], (prefix, events)
        assert events[0][2] == 0, (prefix, "restricted while still empty")
        assert events[0][1].parent == scratch_dir and events[1][1] == events[0][1]
    for event in tl.events:
        if event[0] == "icacls" and event[2] != "dir":
            assert event[2] == 0, event


@pytest.mark.parametrize("which", ["vision_token.txt", "dash_token.txt", "deploy_request.key"])
def test_a_failed_acl_fails_closed_for_that_secret_only(tmp_path, monkeypatch, which):
    root = make_root(tmp_path)
    tl = Timeline(monkeypatch, rc=lambda p: 5 if p.name.startswith(which) else 0)
    report = provision(root, restrict=tl.restrict)
    name = {"vision_token.txt": "vision_token", "dash_token.txt": "dash_token",
            "deploy_request.key": "deploy_key"}[which]
    res = by_name(report)[name]
    assert res.state == "error" and res.acl is False
    assert not res.path.exists(), "no secret published"
    assert [e for e in tl.for_name(which) if e[0] == "write"] == [], "no secret byte written"
    assert leftover_tmp(root) == []
    others = {r.name: r.state for r in report.results if r.name != name}
    assert set(others.values()) == {"created"}, others
    line = next(line for line in report.lines(root) if line.startswith(f"first run: {name} "))
    assert "not written" in line


def test_every_secret_and_scratch_path_is_gitignored():
    # Literal .gitignore lines (checked as text: a fresh clone may have no
    # git binary on PATH in CI).
    lines = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert "config/vision_token.txt" in lines
    assert "ops/runtime/" in lines
    for rel in (fr.DASH_TOKEN_REL, fr.DEPLOY_KEY_REL, fr.SCRATCH_REL):
        assert rel[:2] == ("ops", "runtime"), rel


def test_a_concurrent_writer_wins_and_is_kept(tmp_path):
    root = make_root(tmp_path)
    target = vision_path(root)
    winner = secrets.token_hex(16)

    def race(path):
        if path.name.startswith("vision_token.txt"):
            target.write_text(winner + "\n", encoding="ascii")

    report = provision(root, restrict=Recorder(side_effect=race))
    assert by_name(report)["vision_token"].state == "present"
    assert first_line(target) == winner
    assert leftover_tmp(root) == []


def test_no_hard_links_exclusive_create_restricts_before_writing(tmp_path, monkeypatch):
    root = make_root(tmp_path)

    def no_link(src, dst):
        raise OSError(errno.EXDEV, "hard links not supported here")

    monkeypatch.setattr(fr.os, "link", no_link)
    tl = Timeline(monkeypatch)
    report = provision(root, restrict=tl.restrict)
    assert {r.state for r in report.results} == {"created"}
    assert re.fullmatch(r"[0-9a-f]{32}", first_line(vision_path(root)))
    final = [e for e in tl.events if e[1] == vision_path(root)]
    assert [e[0] for e in final] == ["icacls", "write"], final
    assert final[0][2] == 0, "the final file was empty when its ACL was set"
    assert leftover_tmp(root) == []


def test_no_hard_links_never_clobbers_a_file_created_in_between(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    target = vision_path(root)
    winner = secrets.token_hex(16)

    def no_link_and_a_racer(src, dst):
        if Path(dst) == target:
            target.write_text(winner + "\n", encoding="ascii")   # lands between steps
        raise OSError(errno.EXDEV, "hard links not supported here")

    monkeypatch.setattr(fr.os, "link", no_link_and_a_racer)
    replaced = []
    monkeypatch.setattr(fr.os, "replace", lambda *a: replaced.append(a))
    report = provision(root)
    assert by_name(report)["vision_token"].state == "present", "already provisioned"
    assert first_line(target) == winner, "the racer's secret is kept"
    assert replaced == [], "os.replace is never a publish path"
    assert leftover_tmp(root) == []


def test_a_link_error_that_is_not_unsupported_does_not_fall_back(tmp_path, monkeypatch):
    root = make_root(tmp_path)

    def denied(src, dst):
        raise PermissionError(errno.EACCES, "access denied")

    monkeypatch.setattr(fr.os, "link", denied)
    report = provision(root)
    for res in report.results:
        assert res.state == "error" and "PermissionError" in res.detail, res
        assert not res.path.exists()
    assert leftover_tmp(root) == []


@pytest.mark.parametrize("exc, unsupported", [
    (OSError(errno.EXDEV, "cross-device"), True),
    (OSError(errno.EPERM, "fs refuses links"), True),
    (PermissionError(errno.EACCES, "denied"), False),
    (OSError(errno.ENOSPC, "disk full"), False),
])
def test_links_unsupported_is_narrow(exc, unsupported):
    assert fr._links_unsupported(exc) is unsupported


@WINDOWS_ONLY
@pytest.mark.parametrize("winerror, unsupported", [(1, True), (17, True), (50, True),
                                                   (5, False), (112, False)])
def test_links_unsupported_reads_the_windows_error(winerror, unsupported):
    exc = OSError(None, "link", None, winerror)
    assert exc.winerror == winerror
    assert fr._links_unsupported(exc) is unsupported


# ------------------------------------------------- no secret in a log


def test_report_lines_never_carry_a_secret_value(tmp_path):
    root = make_root(tmp_path, deploy_module=True)
    report = provision(root, dash_token_gate=True)
    values = [first_line(vision_path(root)), first_line(dash_path(root)),
              first_line(key_path(root))]
    lines = report.lines(root)
    assert len(lines) >= 4
    for line in lines:
        for value in values:
            assert value not in line
    assert "RC_DASH_TOKEN" in " ".join(lines)
    text = repr(report.results)
    for value in values:
        assert value not in text, "the results carry names and paths only"


# ------------------------------------------------------------- ACL


def test_restrict_runs_icacls_windowless_with_the_current_user_sid(tmp_path):
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0)

    path = tmp_path / "s.txt"
    path.write_text("x", encoding="ascii")
    sid = "S-1-5-21-1000-2000-3000-1001"
    assert fr.restrict_to_current_user(path, run=run, windows=True, sid=sid) is True
    (argv, kw), = calls
    assert Path(argv[0]).name.lower() in ("icacls", "icacls.exe")
    assert argv[1] == str(path)
    assert argv[2:] == ["/inheritance:r", "/grant:r", f"*{sid}:(F)"]
    assert kw["creationflags"] == fr.CREATE_NO_WINDOW
    assert kw["stdout"] is subprocess.DEVNULL and kw["timeout"] > 0


def test_restrict_on_a_folder_grants_an_inheritable_ace(tmp_path):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    sid = "S-1-5-21-1000-2000-3000-1001"
    assert fr.restrict_to_current_user(tmp_path, run=run, windows=True, sid=sid) is True
    assert calls[0][2:] == ["/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)(F)"]


def test_restrict_reports_failure_without_raising(tmp_path):
    path = tmp_path / "s.txt"
    path.write_text("x", encoding="ascii")
    sid = "S-1-5-21-1-2-3-1001"

    def failing(argv, **kw):
        return subprocess.CompletedProcess(argv, 5)

    def missing(argv, **kw):
        raise FileNotFoundError("icacls")

    assert fr.restrict_to_current_user(path, run=failing, windows=True, sid=sid) is False
    assert fr.restrict_to_current_user(path, run=missing, windows=True, sid=sid) is False


def test_restrict_refuses_a_malformed_identity(tmp_path, monkeypatch):
    path = tmp_path / "s.txt"
    path.write_text("x", encoding="ascii")
    calls = []
    monkeypatch.setattr(fr, "current_user_sid", lambda: None)
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("USERDOMAIN", raising=False)
    ok = fr.restrict_to_current_user(path, run=lambda a, **k: calls.append(a), windows=True)
    assert ok is False and calls == [], "no identity, no icacls call"
    assert fr.restrict_to_current_user(path, run=lambda a, **k: calls.append(a), windows=True,
                                       sid="S-1-5-21 & calc") is False
    assert calls == []


@WINDOWS_ONLY
def test_current_user_sid_is_a_real_sid():
    sid = fr.current_user_sid()
    assert sid and re.fullmatch(r"S-1(-\d+)+", sid)


@WINDOWS_ONLY
def test_real_icacls_leaves_only_the_current_user(tmp_path):
    path = tmp_path / "secret.txt"
    path.write_text(secrets.token_hex(8), encoding="ascii")
    assert fr.restrict_to_current_user(path) is True
    out = subprocess.run(["icacls", str(path)], capture_output=True, text=True,
                         creationflags=NO_WINDOW, timeout=30).stdout
    aces = [line for line in out.splitlines() if ":(" in line]
    assert len(aces) == 1, out
    assert "(I)" not in out, "inheritance removed"
    assert "(F)" in aces[0]


@WINDOWS_ONLY
def test_real_restricted_folder_hands_new_files_only_the_current_user(tmp_path):
    folder = tmp_path / "scratch"
    folder.mkdir()
    assert fr.restrict_to_current_user(folder) is True
    child = folder / "new.txt"
    child.write_bytes(b"")
    out = subprocess.run(["icacls", str(child)], capture_output=True, text=True,
                         creationflags=NO_WINDOW, timeout=30).stdout
    aces = [line for line in out.splitlines() if ":(" in line]
    assert len(aces) == 1 and "(F)" in aces[0], out


@POSIX_ONLY
def test_posix_restrict_is_owner_only(tmp_path):
    path = tmp_path / "secret.txt"
    path.write_text("x", encoding="ascii")
    assert fr.restrict_to_current_user(path) is True
    assert (path.stat().st_mode & 0o777) == 0o600
    folder = tmp_path / "scratch"
    folder.mkdir()
    assert fr.restrict_to_current_user(folder) is True
    assert (folder.stat().st_mode & 0o777) == 0o700


# ------------------------------------------------- static guards


def test_every_spawn_site_in_first_run_passes_creationflags():
    tree = ast.parse(FIRST_RUN_PY.read_text(encoding="utf-8"))
    sites = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run":
            sites += 1
            assert "creationflags" in {k.arg for k in node.keywords}, node.lineno
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = node.func.value.id if isinstance(node.func.value, ast.Name) else None
            if base == "subprocess":
                assert node.func.attr not in {"Popen", "call", "check_call", "check_output"}, \
                    node.lineno
            if base == "os":
                assert node.func.attr not in {"system", "popen", "startfile"}, node.lineno
    assert sites >= 1, "the icacls site must be found, or this guard is empty"


def test_first_run_is_stdlib_only():
    tree = ast.parse(FIRST_RUN_PY.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative import: it is loaded by path under -I"
            names.add((node.module or "").split(".")[0])
    names.discard("__future__")
    assert names and names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_first_run_source_is_ascii_lf():
    raw = FIRST_RUN_PY.read_bytes()
    assert b"\r" not in raw
    raw.decode("ascii")


# ------------------------------------------------- manifest flag


def test_shipped_profiles_keep_the_dash_token_gate_off():
    doc = json.loads(SERVICES_JSON.read_text(encoding="utf-8"))
    for prof in ("packaged", "dev"):
        assert doc["profiles"][prof]["dash_token_gate"] is False, prof
        assert sh.load_config(SERVICES_JSON, prof).dash_token_gate is False


def test_the_gate_flag_parses_per_profile_and_defaults_off():
    doc = json.loads(SERVICES_JSON.read_text(encoding="utf-8"))
    doc["profiles"]["packaged"]["dash_token_gate"] = True
    assert sh.parse_config(doc, "packaged").dash_token_gate is True
    assert sh.parse_config(doc, "dev").dash_token_gate is False
    del doc["profiles"]["dev"]["dash_token_gate"]
    assert sh.parse_config(doc, "dev").dash_token_gate is False, "absent = off"


@pytest.mark.parametrize("value", ["true", 1, None, "yes"])
def test_the_gate_flag_must_be_a_boolean(value):
    doc = json.loads(SERVICES_JSON.read_text(encoding="utf-8"))
    doc["profiles"]["packaged"]["dash_token_gate"] = value
    with pytest.raises(sh.ConfigError) as err:
        sh.parse_config(doc, "dev")
    assert "dash_token_gate" in str(err.value)


# ------------------------------------------------- service host hook


class _Proc:
    def __init__(self, pid, argv):
        self.pid = pid
        self.argv = list(argv)
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 1

    def kill(self):
        self.returncode = 1


class _Popen:
    def __init__(self, events):
        self.calls = []
        self.events = events
        self._pid = 7000

    def __call__(self, argv, **kw):
        self._pid += 1
        self.calls.append((list(argv), dict(kw)))
        self.events.append(("spawn", argv[1] if len(argv) > 1 else argv[0]))
        return _Proc(self._pid, argv)


def _config(gate: bool = False):
    doc = {
        "schema": 1, "dashboard_port": 1, "tick_s": 0.5, "stop_grace_s": 0,
        "profiles": {"packaged": {"env": {}, "dash_token_gate": gate}},
        "services": [
            {"name": "supervisor", "role": "supervisor", "argv": ["sup.py"],
             "restart": "on-failure"},
            {"name": "agent_a", "argv": ["a.py"], "restart": "always"},
        ],
    }
    return sh.parse_config(doc, "packaged")


def _host(root, cfg, *, events, probe_mode="owned", provision=None, logs=None):
    kw = {}
    if provision is not None:
        kw["provision"] = provision
    popen = _Popen(events)
    host = sh.ServiceHost(
        root, cfg, popen=popen, job_factory=lambda: None,
        clock=lambda: 1000.0, sleep=lambda s: None, parent_alive=lambda: True,
        probe=lambda: sh.Probe(probe_mode, "probe",
                               "http://127.0.0.1:1" if probe_mode == "attach" else None, None),
        health=lambda: None, python_exe="PYEXE",
        log=(logs.append if logs is not None else None), **kw)
    return host, popen


def test_owned_start_provisions_once_before_anything_spawns(tmp_path):
    root = make_root(tmp_path)
    events = []

    def fake(r, cfg, environ, log):
        events.append(("provision", Path(r)))
        return {}

    host, popen = _host(root, _config(), events=events, provision=fake)
    host.start()
    host.start()
    assert events[0] == ("provision", root)
    assert [e for e in events if e[0] == "provision"] == [("provision", root)]
    assert [e[0] for e in events[1:]] == ["spawn", "spawn"]


@pytest.mark.parametrize("mode", ["attach", "blocked"])
def test_attach_and_blocked_modes_never_provision(tmp_path, mode):
    root = make_root(tmp_path)
    events = []

    def fake(*a):
        events.append("provision")
        return {}

    host, popen = _host(root, _config(), events=events, probe_mode=mode, provision=fake)
    host.start()
    assert events == [] and popen.calls == []
    assert not vision_path(root).exists()


@pytest.mark.parametrize("gate", [False, True])
def test_the_gate_decides_whether_services_see_rc_dash_token(tmp_path, monkeypatch, gate):
    monkeypatch.delenv("RC_DASH_TOKEN", raising=False)
    monkeypatch.delenv("RC_VISION_TOKEN", raising=False)   # conftest's test default
    monkeypatch.setattr(fr, "restrict_to_current_user", lambda p, **k: True)
    root = make_root(tmp_path)
    events = []
    host, popen = _host(root, _config(gate), events=events)   # the DEFAULT provisioner
    host.start()
    token = first_line(dash_path(root))
    assert len(popen.calls) == 2
    for _argv, kw in popen.calls:
        env = kw["env"]
        if gate:
            assert env is not None and env["RC_DASH_TOKEN"] == token
        else:
            assert env is None or not any(k.upper() == "RC_DASH_TOKEN" for k in env)
    assert "RC_DASH_TOKEN" not in os.environ, "the host's own environment is untouched"


def test_default_provisioning_logs_names_never_values(tmp_path, monkeypatch):
    monkeypatch.delenv("RC_VISION_TOKEN", raising=False)   # conftest's test default
    monkeypatch.setattr(fr, "restrict_to_current_user", lambda p, **k: True)
    root = make_root(tmp_path, deploy_module=True)
    logs, events = [], []
    host, popen = _host(root, _config(True), events=events, logs=logs)
    host.start()
    values = [first_line(vision_path(root)), first_line(dash_path(root)),
              first_line(key_path(root))]
    assert any(line.startswith("first run:") for line in logs)
    status = (root / "ops" / "runtime" / "launcher_status.json").read_text(encoding="utf-8")
    for value in values:
        assert all(value not in line for line in logs)
        assert value not in status


def test_a_provisioning_crash_is_logged_and_services_still_start(tmp_path):
    root = make_root(tmp_path)
    logs, events = [], []

    def boom(*a):
        raise RuntimeError("provisioning bug")

    host, popen = _host(root, _config(), events=events, provision=boom, logs=logs)
    host.start()
    assert len(popen.calls) == 2
    assert any("first run" in line and "RuntimeError" in line for line in logs)


# ------------------------------------------- real host under -I


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@WINDOWS_ONLY
def test_real_isolated_host_provisions_a_fresh_root(tmp_path):
    root = make_root(tmp_path, deploy_module=True)
    (root / "sleeper.py").write_text("import time\ntime.sleep(60)\n", encoding="ascii")
    svc = tmp_path / "services.json"
    svc.write_text(json.dumps({
        "schema": 1, "dashboard_port": _free_port(), "tick_s": 0.2, "stop_grace_s": 2,
        "services": [{"name": "sleeper", "argv": ["sleeper.py"], "restart": "never"}],
    }), encoding="ascii")
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("RC_VISION_TOKEN", "RC_DASH_TOKEN")}
    host = subprocess.Popen(
        [sys.executable, "-I", str(HOST_PY), "--root", str(root), "--services", str(svc),
         "--parent-pid", str(parent.pid), "--no-stdin"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env, creationflags=NO_WINDOW)
    try:
        parent.wait(30)
        assert host.wait(60) == 0
    finally:
        for proc in (host, parent):
            if proc.poll() is None:
                proc.kill()
                proc.wait(10)
    values = [first_line(vision_path(root)), first_line(dash_path(root)),
              first_line(key_path(root))]
    log = (root / "ops" / "runtime" / "logs" / "service_host.log").read_text(encoding="utf-8")
    assert "first run: vision_token created" in log
    assert "first run: deploy_key created" in log
    for value in values:
        assert value not in log
    status = (root / "ops" / "runtime" / "launcher_status.json").read_text(encoding="utf-8")
    assert json.loads(status)["state"] == "halted"
    for value in values:
        assert value not in status
