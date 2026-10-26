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
  deploy key    ops/runtime/deploy_request.key  (written by first_run itself in
                                                 ensure_key's format,
                                                 ops/rc_transactional_deploy.py:115;
                                                 parity pinned against the real
                                                 ensure_key / sign / verify)

Every secret is staged in a pinned, verified-private run folder under the
gitignored ops/runtime/first_run/ and published by hard link.

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
from tests._module_view import this_thread_only

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
    """A fake `restrict` (ACL) callable: records the path of each HELD
    object it is given; `result` is a bool or a callable(path) -> bool."""

    def __init__(self, result=True, side_effect=None):
        self.calls = []
        self.result = result
        self.side_effect = side_effect

    def __call__(self, held):
        path = Path(held.path)
        self.calls.append(path)
        if self.side_effect is not None:
            self.side_effect(path)
        return self.result(path) if callable(self.result) else self.result


def _size(path: Path):
    try:
        return path.stat().st_size if path.is_file() else "dir"
    except OSError:
        return None


class Timeline:
    """One ordered event list for restricts and verifies (both of a HELD
    object), file opens (first_run._open_new) and secret writes
    (first_run._write_secret, which takes the creating handle). Each event
    records the size of its target at that moment, so "private before any
    secret byte" is checked directly. `restrict` answers rc == 0 and
    changes nothing; `verify` answers `verified` (the real verifier would -
    correctly - refuse a folder this fake restrict never touched)."""

    def __init__(self, monkeypatch, rc=0, verified=True):
        self.events = []
        self.rc = rc
        self.verified = verified
        self.fds = {}
        real_open, real_write = fr._open_new, fr._write_secret

        def open_new(path, *rest):
            fd = real_open(path, *rest)
            self.fds[fd] = Path(path)
            self.events.append(("open", Path(path)))
            return fd

        def write(fd, data):
            self.events.append(("write", self.fds[fd]))
            real_write(fd, data)

        monkeypatch.setattr(fr, "_open_new", open_new)
        monkeypatch.setattr(fr, "_write_secret", write)

    def restrict(self, held):
        path = Path(held.path)
        assert held.handle or held.fd is not None, "restrict is only ever given a HELD object"
        self.events.append(("restrict", path, _size(path)))
        return (self.rc(path) if callable(self.rc) else self.rc) == 0

    def verify(self, held):
        path = Path(held.path)
        self.events.append(("verify", path, _size(path)))
        return self.verified(path) if callable(self.verified) else self.verified

    def run_folder(self):
        return next(e[1] for e in self.events
                    if e[0] == "verify" and e[1].name.startswith("run-"))

    def for_name(self, prefix):
        return [e for e in self.events if e[1].name.startswith(prefix)]

    def kwargs(self):
        return {"restrict": self.restrict, "verify": self.verify}


def run_dirs(root: Path) -> list:
    base = root / "ops" / "runtime" / "first_run"
    return sorted(base.iterdir()) if base.is_dir() else []


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
    kw.setdefault("verify", lambda p: True)   # a Recorder changes no real ACL
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
    report = provision(root, **tl.kwargs())
    assert by_name(report)["deploy_key"].state == "created"
    events = tl.for_name("deploy_request.key")
    assert [e[0] for e in events] == FILE_STEPS, events
    assert events[1][2] == 0, "the scratch read back private while still empty"
    assert events[2][1] == events[0][1], "the secret went into that scratch"


# Per scratch file: exclusive private-from-birth create, read-back through the
# open handle, then the one write through that same handle. No icacls.
FILE_STEPS = ["open", "verify", "write"]


def test_provisioning_spawns_no_process_at_all(tmp_path, monkeypatch):
    def no_spawn(*a, **k):
        raise AssertionError("first_run spawns nothing (no worker, no icacls)")

    # first_run binds no `subprocess` name (no module view to scope to), so the
    # tripwire is thread-scoped: this test's thread and every thread it starts
    # get it, another test's leftover thread keeps the real Popen (RM-801).
    monkeypatch.setattr(subprocess, "Popen", this_thread_only(no_spawn, subprocess.Popen))
    root = make_root(tmp_path, deploy_module=True)
    report = fr.provision(root, environ={})          # real restrict + real verify
    assert {r.state for r in report.results} == {"created"}, report.results


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


def test_the_scratch_file_is_verified_private_before_it_is_published(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    seen = []
    target = vision_path(root)

    def verified(path):
        seen.append((path, target.exists(), _size(path)))
        return True

    tl = Timeline(monkeypatch, verified=verified)
    provision(root, **tl.kwargs())
    scratch, existed, size = next(s for s in seen if s[0].name.startswith("vision_token.txt"))
    assert scratch != target and scratch.name.endswith(".tmp")
    assert existed is False, "verified before the secret has its real name"
    assert size == 0, "verified before a secret byte is in it"
    base = root / "ops" / "runtime" / "first_run"
    assert scratch.parent.parent == base and scratch.parent.name.startswith("run-"), \
        "a fresh per-run folder under the ignored ops/runtime/, never config/"
    assert leftover_tmp(root) == []
    assert run_dirs(root) == [], "the per-run folder is removed after publishing"


BASE_NAME = "first_run"


def test_base_is_restricted_and_verified_then_a_fresh_run_folder_before_any_file(
        tmp_path, monkeypatch):
    root = make_root(tmp_path)
    tl = Timeline(monkeypatch)
    report = provision(root, **tl.kwargs())
    assert {r.state for r in report.results} == {"created"}
    base = root / "ops" / "runtime" / "first_run"
    kinds = [e[0] for e in tl.events[:3]]
    assert kinds == ["restrict", "verify", "verify"], tl.events[:4]
    assert all(e[1] == base for e in tl.events[:2]) and tl.events[0][2] == "dir", \
        "the BASE is restricted (through its pin) and verified first, on every run"
    folder = tl.events[2][1]
    assert folder.parent == base and folder.name.startswith("run-")
    for prefix in ("vision_token.txt", "dash_token.txt", "deploy_request.key"):
        events = tl.for_name(prefix)
        assert [e[0] for e in events] == FILE_STEPS, (prefix, events)
        assert events[1][2] == 0, (prefix, "verified private while still empty")
        assert events[0][1].parent == folder and events[2][1] == events[0][1]
    assert [e for e in tl.events if e[0] == "restrict" and e[1] != base] == [], \
        "only the base is ever re-ACLed; run folder and files are private from birth"
    folder_verifies = [e for e in tl.events if e[0] == "verify" and e[1] in (base, folder)]
    assert len(folder_verifies) == 2, "one base + one run folder"
    assert run_dirs(root) == [], "removed after publishing"


def test_every_run_gets_a_new_folder_and_re_restricts_the_base(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    tl = Timeline(monkeypatch)
    provision(root, **tl.kwargs())
    vision_path(root).unlink()
    provision(root, **tl.kwargs())
    folders = [e[1] for e in tl.events if e[0] == "verify" and e[1].name.startswith("run-")]
    assert len(folders) == 2 and folders[0] != folders[1]
    base_restricts = [e for e in tl.events if e[0] == "restrict" and e[1].name == BASE_NAME]
    assert len(base_restricts) == 2, "the base is restricted at the start of every run"
    assert run_dirs(root) == []


def test_a_stale_scratch_folder_is_never_reused(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    base = root / "ops" / "runtime" / "first_run"
    base.mkdir(parents=True)
    (base / "left-over.tmp").write_bytes(b"")   # e.g. an older layout, unrestricted
    tl = Timeline(monkeypatch)
    provision(root, **tl.kwargs())
    folder = tl.run_folder()
    assert folder != base and folder.parent == base
    assert all(e[1].parent == folder for e in tl.events if e[0] in ("open", "write")), \
        "files only ever go into this run's own folder"


@pytest.mark.parametrize("failure", ["base-restrict", "base-verify", "run-verify", "mkdir"])
def test_an_unprivate_scratch_folder_writes_nothing_at_all(tmp_path, monkeypatch, failure):
    root = make_root(tmp_path)
    rc = (lambda p: 5 if p.name == BASE_NAME else 0) if failure == "base-restrict" else 0
    verified = {"base-verify": lambda p: p.name != BASE_NAME,
                "run-verify": lambda p: not p.name.startswith("run-")}.get(failure, True)
    tl = Timeline(monkeypatch, rc=rc, verified=verified)
    if failure == "mkdir":
        def no_mkdir(*a, **k):
            raise PermissionError(errno.EACCES, "denied")
        monkeypatch.setattr(fr.os, "mkdir", no_mkdir)
    report = provision(root, **tl.kwargs())
    for res in report.results:
        assert res.state == "error" and res.acl is False, res
        assert "not written" in res.detail
        assert not res.path.exists()
    assert [e for e in tl.events if e[0] in ("open", "write")] == [], "no file, no byte"
    assert run_dirs(root) == [], "a refused run folder is removed"
    lines = report.lines(root)
    for name in ("vision_token", "dash_token", "deploy_key"):
        assert any(line.startswith(f"first run: {name} error") for line in lines), lines


def _all_bytes(top: Path) -> list:
    return [(p, p.read_bytes()) for p in top.rglob("*") if p.is_file()]


@WINDOWS_ONLY
def test_the_held_run_folder_and_base_cannot_be_renamed(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    refused = []

    def try_swap(scratch):
        for path in (scratch.path, scratch.base):
            try:
                os.rename(path, path.with_name(path.name + "-moved"))
            except PermissionError as exc:
                refused.append((path.name, exc.winerror))
            else:
                raise AssertionError(f"{path} was renamed while pinned")

    monkeypatch.setattr(fr, "_after_scratch_verified", try_swap)
    report = fr.provision(root, environ={})            # real restrict + real verify
    assert len(refused) == 2, refused
    assert {r.state for r in report.results} == {"created"}, report.results
    for path in (vision_path(root), dash_path(root), key_path(root)):
        assert fr.verify_private(path), path
    assert run_dirs(root) == []


@POSIX_ONLY
def test_posix_swap_after_verify_cannot_redirect_a_scratch_file(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    planted = []

    def swap(scratch):
        moved = scratch.path.with_name(scratch.path.name + "-moved")
        os.rename(scratch.path, moved)
        scratch.path.mkdir()
        os.chmod(scratch.path, 0o777)                    # a permissive look-alike
        planted.append(scratch.path)

    monkeypatch.setattr(fr, "_after_scratch_verified", swap)
    report = fr.provision(root, environ={})
    assert {r.state for r in report.results} == {"created"}, report.results
    assert list(planted[0].iterdir()) == [], "nothing ever landed in the planted folder"
    for path in (vision_path(root), dash_path(root), key_path(root)):
        assert (path.stat().st_mode & 0o777) == 0o600


def test_a_run_folder_that_is_not_empty_is_refused(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    real_make = fr._make_private_dir

    def make_with_a_plant(path, sid, parent):
        real_make(path, sid, parent)
        if Path(path).name.startswith("run-"):
            (Path(path) / "planted.lnk").write_bytes(b"")

    monkeypatch.setattr(fr, "_make_private_dir", make_with_a_plant)
    tl = Timeline(monkeypatch)
    report = provision(root, **tl.kwargs())
    for res in report.results:
        assert res.state == "error" and "not written" in res.detail, res
    assert [e for e in tl.events if e[0] in ("open", "write")] == []


def test_a_name_that_is_not_the_open_file_is_refused(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    monkeypatch.setattr(fr, "_identity_of_name", lambda *a: (-1, -1))
    tl = Timeline(monkeypatch)
    report = provision(root, **tl.kwargs())
    for res in report.results:
        assert res.state == "error" and res.detail == fr.MOVED, res
    assert [e for e in tl.events if e[0] in ("verify", "write") and e[1].suffix == ".tmp"] == []
    assert leftover_tmp(root) == []


def test_a_published_name_that_is_not_the_written_file_is_removed(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    planted = secrets.token_hex(16)

    def evil_link(src, dst, **kw):
        Path(dst).write_text(planted + "\n", encoding="ascii")   # not our file

    monkeypatch.setattr(fr.os, "link", evil_link)
    report = provision(root)
    for res in report.results:
        assert res.state == "error" and res.detail == fr.MOVED, res
        assert not res.path.exists(), "the foreign file is not left as the secret"
    assert leftover_tmp(root) == []


@WINDOWS_ONLY
def test_real_verify_held_reads_through_the_handle(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    held = fr.hold_dir(plain)
    try:
        assert held is not None and fr.verify_held(held) is False
    finally:
        held.close()
    private = tmp_path / "private"
    fr._make_private_dir(private, fr.current_user_sid(), None)
    held = fr.hold_dir(private)
    try:
        assert held is not None and fr.verify_held(held) is True
    finally:
        held.close()


def test_a_swap_past_the_pins_is_detected_and_writes_nothing(tmp_path, monkeypatch):
    # Model an attacker who got PAST the pins: release them, rename the
    # verified run folder away and plant a permissive same-name folder.
    root = make_root(tmp_path)
    planted = []

    def swap(scratch):
        scratch._release_pins()
        moved = scratch.path.with_name(scratch.path.name + "-moved")
        os.rename(scratch.path, moved)
        scratch.path.mkdir()
        if os.name != "nt":
            os.chmod(scratch.path, 0o777)
        planted.append(scratch.path)

    monkeypatch.setattr(fr, "_after_scratch_verified", swap)
    tl = Timeline(monkeypatch)
    report = provision(root, **tl.kwargs())
    for res in report.results:
        assert res.state == "error" and res.detail == fr.MOVED, res
        assert not res.path.exists()
    assert [e for e in tl.events if e[0] == "write"] == [], "no secret byte written"
    if os.name == "nt":
        assert [e for e in tl.events if e[0] == "open"], \
            "Windows reached the parent-identity check (files opened in the planted folder)"
    assert [p for p, data in _all_bytes(tmp_path) if data] == [], "no secret bytes anywhere"
    assert list(planted[0].iterdir()) == []


def test_the_secret_is_written_through_the_creating_handle(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    opened = []
    real_open = os.open

    def counting_open(path, flags, *a, **k):
        opened.append((Path(path).name, flags))
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(fr.os, "open", counting_open)
    tl = Timeline(monkeypatch)                  # its write wrapper needs the creating fd
    report = provision(root, **tl.kwargs())
    assert {r.state for r in report.results} == {"created"}
    for prefix in ("vision_token.txt", "dash_token.txt", "deploy_request.key"):
        events = tl.for_name(prefix)
        assert [e[0] for e in events] == FILE_STEPS and events[2][1] == events[0][1]
        mine = [flags for name, flags in opened if name.startswith(prefix)]
        # Windows creates through CreateFileW (no os.open at all); POSIX
        # through one dir_fd-relative os.open. Never a reopen by name.
        assert len(mine) == (0 if os.name == "nt" else 1), (prefix, mine)
        assert all(flags & os.O_CREAT and flags & os.O_EXCL for flags in mine)


@pytest.mark.parametrize("which", ["vision_token.txt", "dash_token.txt", "deploy_request.key"])
def test_a_failed_acl_fails_closed_for_that_secret_only(tmp_path, monkeypatch, which):
    root = make_root(tmp_path)
    tl = Timeline(monkeypatch, verified=lambda p: not p.name.startswith(which))
    report = provision(root, **tl.kwargs())
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


def test_a_concurrent_writer_wins_and_is_kept(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    target = vision_path(root)
    winner = secrets.token_hex(16)

    def race(path):
        if path.name.startswith("vision_token.txt"):
            target.write_text(winner + "\n", encoding="ascii")
        return True

    tl = Timeline(monkeypatch, verified=race)
    report = provision(root, **tl.kwargs())
    assert by_name(report)["vision_token"].state == "present"
    assert first_line(target) == winner
    assert leftover_tmp(root) == []


@pytest.mark.parametrize("exc", [OSError(errno.EXDEV, "cross-volume"),
                                 OSError(errno.EPERM, "FAT refuses hard links")])
def test_no_hard_links_fails_closed_and_creates_nothing_in_place(tmp_path, monkeypatch, exc):
    root = make_root(tmp_path)

    def no_link(src, dst, **kw):
        raise exc

    monkeypatch.setattr(fr.os, "link", no_link)
    replaced = []
    monkeypatch.setattr(fr.os, "replace", lambda *a: replaced.append(a))
    tl = Timeline(monkeypatch)
    report = provision(root, **tl.kwargs())
    for res in report.results:
        assert res.state == "error" and "hard link" in res.detail, res
        assert not res.path.exists(), "never created in place under an inherited ACL"
    assert not any(e[1].parent != tl.run_folder() for e in tl.events if e[0] == "open"), \
        "files are only ever opened inside the private folder"
    assert replaced == [] and leftover_tmp(root) == [] and run_dirs(root) == []


def test_no_hard_links_never_touches_a_file_created_in_between(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    target = vision_path(root)
    winner = secrets.token_hex(16)

    def no_link_and_a_racer(src, dst, **kw):
        if Path(dst) == target:
            target.write_text(winner + "\n", encoding="ascii")   # lands between steps
        raise OSError(errno.EXDEV, "hard links not supported here")

    monkeypatch.setattr(fr.os, "link", no_link_and_a_racer)
    report = provision(root)
    assert by_name(report)["vision_token"].state == "error"
    assert first_line(target) == winner, "the racer's secret is kept"
    assert leftover_tmp(root) == []


def test_a_link_error_that_is_not_unsupported_does_not_fall_back(tmp_path, monkeypatch):
    root = make_root(tmp_path)

    def denied(src, dst, **kw):
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


def _restrict_path(path: Path) -> bool:
    """Test helper: pin `path` (refusing a reparse point) and restrict it
    THROUGH the pin, the only way first_run changes an ACL."""
    held = fr.hold_dir(path, write_acl=True)
    if held is None:
        return False
    try:
        return fr.restrict_held(held)
    finally:
        held.close()


def test_restrict_held_refuses_an_object_that_is_not_held(tmp_path):
    loose = fr.HeldDir(tmp_path, tmp_path.name)             # no handle, no fd
    assert fr.restrict_held(loose) is False
    assert fr.verify_held(loose) is False


@WINDOWS_ONLY
def test_restrict_held_needs_the_user_sid(tmp_path, monkeypatch):
    held = fr.hold_dir(tmp_path, write_acl=True)
    try:
        monkeypatch.setattr(fr, "current_user_sid", lambda: None)
        assert fr.restrict_held(held) is False
    finally:
        held.close()


@WINDOWS_ONLY
def test_restrict_held_needs_write_acl_on_the_pin(tmp_path):
    held = fr.hold_dir(tmp_path)                            # READ_CONTROL only
    try:
        assert fr.restrict_held(held) is False
    finally:
        held.close()


_ME = "S-1-5-21-1000-2000-3000-1001"


@pytest.mark.parametrize("ace_type, ace_flags, ace_sid, ok", [
    (0, 0x00, _ME, True),                     # explicit allow, this user
    (0, 0x03, _ME, True),                     # (OI)(CI) on a folder is still explicit
    (0, 0x10, _ME, False),                    # INHERITED_ACE
    (0, 0x13, _ME, False),
    (1, 0x00, _ME, False),                    # a deny ACE
    (0, 0x00, "S-1-5-18", False),             # SYSTEM
    (0, 0x00, "S-1-5-32-544", False),         # Administrators
    (0, 0x00, None, False),                   # unreadable SID
])
def test_ace_rule_is_explicit_allow_for_this_user_only(ace_type, ace_flags, ace_sid, ok):
    assert fr._ace_is_private(ace_type, ace_flags, ace_sid, _ME) is ok
    assert fr._is_private_descriptor(_ME, True, [(ace_type, ace_flags, ace_sid)], _ME) is ok


_GOOD_ACE = (0, 0x03, _ME)


@pytest.mark.parametrize("owner, protected, aces, ok", [
    (_ME, True, [_GOOD_ACE], True),
    (_ME, True, [_GOOD_ACE, _GOOD_ACE], True),
    ("S-1-5-32-544", True, [_GOOD_ACE], False),      # owner = Administrators
    (None, True, [_GOOD_ACE], False),                # owner unreadable
    (_ME, False, [_GOOD_ACE], False),                # DACL not protected
    (_ME, True, [], False),                          # an empty DACL proves nothing
    (_ME, True, [_GOOD_ACE, (0, 0, "S-1-5-18")], False),
])
def test_descriptor_rule(owner, protected, aces, ok):
    assert fr._is_private_descriptor(owner, protected, aces, _ME) is ok


@WINDOWS_ONLY
def test_real_verify_refuses_an_unprotected_inherited_user_only_acl(tmp_path):
    parent = tmp_path / "private"
    fr._make_private_dir(parent, fr.current_user_sid(), None)
    child = parent / "child"
    child.mkdir()          # inherits the single user ACE, DACL not protected
    sid = fr.current_user_sid()
    subprocess.run(["icacls", str(child), "/setowner", f"*{sid}"], capture_output=True,
                   creationflags=NO_WINDOW, timeout=30, check=True)
    assert fr.verify_private(child) is False


@WINDOWS_ONLY
def test_real_verify_refuses_inherited_and_accepts_a_private_folder(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    assert fr.verify_private(folder) is False, "inherited ACEs"
    assert _restrict_path(folder) is True
    assert fr.verify_private(folder) is True


def _icacls_explicit(folder: Path, sid: str, *extra_sids: str) -> None:
    """Owner = SID, protected DACL, one explicit full-control allow for SID
    and for each of EXTRA_SIDS - nothing inherited. The DACL goes first: a
    /setowner on a folder still inheriting from a 0o700 parent (pytest's own
    tmp tree on 3.13+) re-writes the parent's ACEs as explicit ones, which a
    later /inheritance:r then keeps (measured 2026-10-26, Python 3.14)."""
    grants = [f"*{s}:(OI)(CI)F" for s in (sid, *extra_sids)]
    for args in (["/inheritance:r", "/grant:r", *grants], ["/setowner", f"*{sid}"]):
        subprocess.run(["icacls", str(folder), *args], capture_output=True,
                       creationflags=NO_WINDOW, timeout=30, check=True)


@WINDOWS_ONLY
def test_real_extra_explicit_principals_are_refused_then_replaced(tmp_path):
    # Python 3.13+ mkdir(mode=0o700) writes EXPLICIT ACEs for SYSTEM and
    # Administrators too (an earlier Python leaves the folder inheriting):
    # either way the read-back refuses it, and restrict_held replaces the
    # WHOLE descriptor (unlike an icacls /grant:r edit).
    folder = tmp_path / "explicit"
    os.mkdir(folder, 0o700)
    assert fr.verify_private(folder) is False
    assert _restrict_path(folder) is True
    assert fr.verify_private(folder) is True
    # The same descriptor shape built on ANY Python, so no interpreter skips
    # the extra-principal refusal. Control first: the identical recipe with
    # only this user's ACE reads back private, so the refusal below is the
    # extra principals (SYSTEM, Administrators) and nothing else.
    sid = fr.current_user_sid()
    control, extra = tmp_path / "control", tmp_path / "extra"
    for path in (control, extra):
        path.mkdir()
    _icacls_explicit(control, sid)
    assert fr.verify_private(control) is True
    _icacls_explicit(extra, sid, "S-1-5-18", "S-1-5-32-544")
    assert fr.verify_private(extra) is False
    assert _restrict_path(extra) is True
    assert fr.verify_private(extra) is True


@WINDOWS_ONLY
def test_real_provisioning_publishes_single_ace_files_and_cleans_up(tmp_path):
    root = make_root(tmp_path)
    report = fr.provision(root, environ={})          # real restrict + real verify
    assert {r.state for r in report.results} == {"created"}, report.results
    for path in (vision_path(root), dash_path(root), key_path(root)):
        out = subprocess.run(["icacls", str(path)], capture_output=True, text=True,
                             creationflags=NO_WINDOW, timeout=30).stdout
        aces = [line for line in out.splitlines() if ":(" in line]
        assert len(aces) == 1 and "(I)" not in out, out
    assert run_dirs(root) == [] and leftover_tmp(root) == []


@POSIX_ONLY
def test_posix_verify_wants_owner_only_mode(tmp_path):
    folder = tmp_path / "scratch"
    folder.mkdir(mode=0o755)
    os.chmod(folder, 0o755)
    assert fr.verify_private(folder) is False
    os.chmod(folder, 0o700)
    assert fr.verify_private(folder) is True


@WINDOWS_ONLY
def test_current_user_sid_is_a_real_sid():
    sid = fr.current_user_sid()
    assert sid and re.fullmatch(r"S-1(-\d+)+", sid)


@WINDOWS_ONLY
def test_real_restricted_folder_hands_new_files_only_the_current_user(tmp_path):
    folder = tmp_path / "scratch"
    folder.mkdir()
    assert _restrict_path(folder) is True
    child = folder / "new.txt"
    child.write_bytes(b"")
    out = subprocess.run(["icacls", str(child)], capture_output=True, text=True,
                         creationflags=NO_WINDOW, timeout=30).stdout
    aces = [line for line in out.splitlines() if ":(" in line]
    assert len(aces) == 1 and "(F)" in aces[0], out


@POSIX_ONLY
def test_posix_restrict_held_is_owner_only(tmp_path):
    folder = tmp_path / "scratch"
    folder.mkdir()
    os.chmod(folder, 0o755)
    assert _restrict_path(folder) is True
    assert (folder.stat().st_mode & 0o777) == 0o700


def _sddl_of(path: Path) -> str:
    """The target's ACL as icacls prints it (test-side reading only)."""
    return subprocess.run(["icacls", str(path)], capture_output=True, text=True,
                          creationflags=NO_WINDOW, timeout=30, check=True).stdout


@WINDOWS_ONLY
def test_a_junction_planted_at_the_base_is_refused_before_any_acl_change(tmp_path):
    import _winapi

    root = make_root(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_bytes(b"")
    base = root / "ops" / "runtime" / "first_run"
    base.parent.mkdir(parents=True)
    _winapi.CreateJunction(str(target), str(base))
    before = _sddl_of(target)
    report = fr.provision(root, environ={})          # real restrict + real verify
    for res in report.results:
        assert res.state == "error" and "not written" in res.detail, res
        assert not res.path.exists()
    assert _sddl_of(target) == before, "the junction's TARGET ACL is untouched"
    assert sorted(p.name for p in target.iterdir()) == ["keep.txt"]
    assert [p for p, data in _all_bytes(tmp_path) if data] == [], "no secret bytes anywhere"


def _handle_count() -> int:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetProcessHandleCount.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    count = wintypes.DWORD()
    assert k32.GetProcessHandleCount(k32.GetCurrentProcess(), ctypes.byref(count))
    return count.value


@WINDOWS_ONLY
def test_provisioning_leaks_no_handles(tmp_path):
    # Three runs per measurement: a leak of even one handle per run shows
    # as >= 3 against a tolerance of 2 for unrelated interpreter churn.
    fr.provision(make_root(tmp_path / "warm"), environ={})      # warm caches / DLLs
    start = _handle_count()
    for i in range(3):
        ok = fr.provision(make_root(tmp_path / f"ok{i}"), environ={})
        assert {r.state for r in ok.results} == {"created"}, ok.results
    after_ok = _handle_count()
    for i in range(3):
        bad = fr.provision(make_root(tmp_path / f"bad{i}"), environ={},
                           verify=lambda held: False)
        assert {r.state for r in bad.results} == {"error"}
    after_bad = _handle_count()
    assert abs(after_ok - start) <= 2, (start, after_ok)
    assert abs(after_bad - start) <= 2, (start, after_bad)


# ------------------------------------------------- static guards


def test_first_run_spawns_nothing_and_never_sets_an_acl_by_path():
    tokens = []
    tree = ast.parse(FIRST_RUN_PY.read_text(encoding="utf-8"))
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings:
            tokens.append(node.value.lower())
        elif isinstance(node, ast.Attribute):
            tokens.append(node.attr.lower())
        elif isinstance(node, ast.Name):
            tokens.append(node.id.lower())
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            tokens += [a.name.lower() for a in node.names] + [(getattr(node, "module", "") or "")]
    assert "setkernelobjectsecurity" in tokens and "getsecurityinfo" in tokens, \
        "the guard must see the handle-based calls, or it is empty"
    for banned in ("subprocess", "icacls", "setnamedsecurityinfow", "getnamedsecurityinfow",
                   "system", "popen", "startfile", "chmod"):
        assert banned not in tokens, banned


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
    root = make_root(tmp_path)
    events = []
    # The DEFAULT provisioner: real restrict + real verify (icacls / chmod).
    host, popen = _host(root, _config(gate), events=events)
    host.start()
    token = first_line(dash_path(root))
    assert len(popen.calls) == 2
    for _argv, kw in popen.calls:
        # Read the one value / one verdict to a local: a failing assert on the
        # child mapping itself would render the whole environment.
        child_env = kw["env"]
        if gate:
            child_token = None if child_env is None else child_env.get("RC_DASH_TOKEN")
            assert child_token == token, "the gate hands every service RC_DASH_TOKEN"
        else:
            sees_token = child_env is not None and any(
                k.upper() == "RC_DASH_TOKEN" for k in child_env)
            assert sees_token is False, "gate off: no service sees RC_DASH_TOKEN"
    host_has_token = "RC_DASH_TOKEN" in os.environ
    assert host_has_token is False, "the host's own environment is untouched"


def test_default_provisioning_logs_names_never_values(tmp_path, monkeypatch):
    monkeypatch.delenv("RC_VISION_TOKEN", raising=False)   # conftest's test default
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
