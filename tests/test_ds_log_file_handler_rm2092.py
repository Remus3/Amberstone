"""RM-2092: Daemon Slayer runtime WARNING / ERROR lines reach a log file.

``agents/daemon_slayer/server.py`` ``serve_forever`` configured logging with a
bare ``logging.basicConfig`` (stderr only), and RC starts DS as a child with
stdout and stderr on DEVNULL (``core/daemon_slayer_client.py`` ``_spawn_child``,
pinned by tests/test_rm740e_ds_spawn_owner.py and kept as it is). Every DS
runtime warning - the engine-reject line of
tests/test_ds_engine_reject_log_clip_s144d55.py among them - was lost in
production.

``serve_forever`` now also attaches a size-capped rotating file handler
(``core.log_rotation``, the RM-718 bound) writing ``logs/daemon_slayer.log``
under the repo root, or the file a non-empty ``RC_DS_LOG_FILE`` names (the kit
test guard points it at tmp_path for every test). Every write here lands in
tmp_path, and every handler a test adds to the root logger is removed and
closed in teardown.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import SnapshotNotFound
from core import log_rotation
from tests import _fleet_guard_config

_REPO = Path(__file__).resolve().parents[1]
_DS_LOGGER = "daemon_slayer.server"


def _ds_file_handlers(lg: logging.Logger) -> list[logging.Handler]:
    return [h for h in lg.handlers if h.name == server.LOG_FILE_HANDLER_NAME]


@pytest.fixture
def clean_root():
    """The root logger, with every handler a test adds removed and closed."""
    root = logging.getLogger()
    before = list(root.handlers)
    level = root.level
    try:
        yield root
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()
        root.setLevel(level)


def test_warning_lands_in_the_file(tmp_path, clean_root):
    target = tmp_path / "logs" / "daemon_slayer.log"  # the parent does not exist yet
    handler = server.install_file_log(target)
    assert handler is not None
    assert handler in clean_root.handlers
    logging.getLogger(_DS_LOGGER).warning("rm2092 probe %s", "alpha")
    handler.flush()
    data = target.read_bytes()
    assert b"daemon_slayer.server WARNING rm2092 probe alpha" in data
    assert b"\r\n" not in data  # LF rows (RM-481), the core.log_rotation handler


def test_the_handler_is_the_shared_size_capped_rotating_one(tmp_path, clean_root):
    handler = server.install_file_log(tmp_path / "ds.log")
    assert isinstance(handler, log_rotation.SafeRotatingFileHandler)
    assert handler.maxBytes == log_rotation.DEFAULT_MAX_BYTES
    assert handler.backupCount == log_rotation.DEFAULT_BACKUP_COUNT
    assert handler.encoding == "utf-8"
    assert handler.mode == "a"


def test_second_install_adds_no_handler(tmp_path, clean_root):
    target = tmp_path / "ds.log"
    first = server.install_file_log(target)
    second = server.install_file_log(target)
    assert first is not None
    assert second is first
    assert len(_ds_file_handlers(clean_root)) == 1
    logging.getLogger(_DS_LOGGER).warning("rm2092 once")
    first.flush()
    assert target.read_text(encoding="utf-8").count("rm2092 once") == 1


@pytest.mark.parametrize("shape", ["directory", "parent_is_a_file"])
def test_unwritable_path_returns_none_and_warns_once(tmp_path, clean_root, caplog, shape):
    if shape == "directory":
        target = tmp_path / "is_a_dir"
        target.mkdir()
    else:
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        target = blocker / "daemon_slayer.log"
    before = list(clean_root.handlers)
    with caplog.at_level(logging.WARNING, logger=_DS_LOGGER):
        result = server.install_file_log(target)
    assert result is None
    assert clean_root.handlers == before
    warned = [r for r in caplog.records if r.name == _DS_LOGGER and r.levelno == logging.WARNING]
    assert len(warned) == 1, [r.getMessage() for r in warned]
    assert "stderr only" in warned[0].getMessage()


def test_target_is_the_repo_logs_dir_unless_the_env_names_a_file(tmp_path, monkeypatch):
    monkeypatch.delenv(server.LOG_FILE_ENV, raising=False)
    assert server.log_file_target() == _REPO / "logs" / "daemon_slayer.log"
    monkeypatch.setenv(server.LOG_FILE_ENV, "   ")
    assert server.log_file_target() == _REPO / "logs" / "daemon_slayer.log"
    monkeypatch.setenv(server.LOG_FILE_ENV, str(tmp_path / "env.log"))
    assert server.log_file_target() == tmp_path / "env.log"
    assert server.log_file_target(tmp_path / "arg.log") == tmp_path / "arg.log"


def test_the_suite_points_the_env_at_tmp(tmp_path):
    assert _fleet_guard_config.ENV_ROOTS.get(server.LOG_FILE_ENV) == "daemon_slayer.log"
    value = os.getenv(server.LOG_FILE_ENV)
    assert value == str(tmp_path / "daemon_slayer.log")


def test_serve_forever_keeps_stderr_and_adds_the_file(tmp_path, clean_root, monkeypatch):
    target = tmp_path / "wired.log"
    monkeypatch.setenv(server.LOG_FILE_ENV, str(target))

    def _no_snapshot(**kwargs):
        raise SnapshotNotFound("rm2092 no snapshot")

    monkeypatch.setattr(server, "start_server", _no_snapshot)
    saved = list(clean_root.handlers)
    clean_root.handlers.clear()  # a bare root, as in the DS process
    try:
        assert server.serve_forever(port=0) == 2
        added = list(clean_root.handlers)
        streams = [h for h in added if type(h) is logging.StreamHandler]
        files = _ds_file_handlers(clean_root)
        assert len(streams) == 1, added
        assert len(files) == 1, added
        files[0].flush()
    finally:
        for h in list(clean_root.handlers):
            clean_root.removeHandler(h)
            h.close()
        clean_root.handlers[:] = saved
    text = target.read_text(encoding="utf-8")
    assert "daemon_slayer.server ERROR snapshot not found: rm2092 no snapshot" in text


def test_serve_forever_runs_on_when_the_file_cannot_open(tmp_path, clean_root, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv(server.LOG_FILE_ENV, str(blocker / "daemon_slayer.log"))
    reached = []

    def _no_snapshot(**kwargs):
        reached.append(kwargs)
        raise SnapshotNotFound("rm2092 no snapshot")

    monkeypatch.setattr(server, "start_server", _no_snapshot)
    assert server.serve_forever(port=0) == 2
    assert len(reached) == 1
    assert not _ds_file_handlers(clean_root)
