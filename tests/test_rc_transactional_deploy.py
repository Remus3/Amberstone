"""Deep-audit suite for `ops/rc_transactional_deploy.py` (lane 8, cycle 7).

The module had ZERO test references before this file: measured by scanning
every `tests/**/*.py` for the stem `rc_transactional_deploy`. It is the
process that overwrites RC's own source files on disk, it runs under the
supervisor's Administrator token, and it takes every path it writes from a
JSON request dropped into `ops/runtime/deploy_requests/`. No in-repo module
writes that directory today, so the producer is out-of-band by construction
- which is precisely why the consumer has to validate.

Path-containment note (item 1179): a traversal test can pass for the wrong
reason when it is anchored to a real repo path. Every root here is a
`tmp_path`-style temporary directory created by the test, so containment is
asserted against a root the test owns rather than against wherever the
suite happens to be checked out.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from ops import rc_transactional_deploy as D  # noqa: E402


class _TmpTreeCase(unittest.TestCase):
    """A disposable project/staging/runtime trio plus an OUTSIDE dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="rc_deploy_audit_")
        base = Path(self._tmp.name)
        self.outside = base / "outside"
        self.project = base / "project"
        self.staging = base / "staging"
        self.runtime = self.project / "ops" / "runtime"
        for d in (self.outside, self.project, self.staging, self.runtime):
            d.mkdir(parents=True, exist_ok=True)
        self.request_path = base / "req.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_request(self, req: dict) -> Path:
        req.setdefault("project_root", str(self.project))
        req.setdefault("staging_root", str(self.staging))
        req.setdefault("runtime_dir", str(self.runtime))
        req.setdefault("health_timeout_seconds", 0.05)
        req.setdefault("command_timeout_seconds", 0.05)
        self.request_path.write_text(json.dumps(req), encoding="utf-8")
        return self.request_path

    def _stage(self, rel: str, body: str = "print('staged')\n") -> None:
        p = self.staging / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


class ContainedPathTests(unittest.TestCase):
    """`contained_path` is the single containment primitive, modelled on the
    `dashboard/routes_static.py:64-67` precedent (resolve + relative_to)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="rc_deploy_cpath_")
        self.root = Path(self._tmp.name) / "root"
        (self.root / "sub").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_accepts_plain_relative(self) -> None:
        got = D.contained_path(self.root, "sub/file.py")
        self.assertEqual(got, (self.root / "sub" / "file.py").resolve())

    def test_rejects_parent_traversal(self) -> None:
        with self.assertRaises(D.DeployPathError):
            D.contained_path(self.root, "../escaped.txt")

    def test_rejects_deep_parent_traversal(self) -> None:
        with self.assertRaises(D.DeployPathError):
            D.contained_path(self.root, "sub/../../../escaped.txt")

    def test_rejects_absolute_path(self) -> None:
        # Measured: Path(root) / Path("C:/Windows/Temp/x") == C:/Windows/Temp/x
        # on Windows - an absolute right-hand side DISCARDS the root entirely.
        absolute = "C:/Windows/Temp/rc_escape.txt" if os.name == "nt" else "/tmp/rc_escape.txt"
        with self.assertRaises(D.DeployPathError) as ctx:
            D.contained_path(self.root, absolute)
        # Assert WHICH guard fired. `relative_to` would also reject this
        # input, so a bare assertRaises here passes over a deleted
        # drive/root check - measured, that mutant survived until this
        # assertion was added.
        self.assertIn("not relative", str(ctx.exception))

    def test_rejects_drive_relative(self) -> None:
        # "C:evil.txt" carries a drive but no root: it resolves against the
        # PROCESS cwd, so it lands inside the root only by coincidence.
        if os.name != "nt":
            self.skipTest("drive-relative paths are Windows-only")
        with self.assertRaises(D.DeployPathError):
            D.contained_path(self.root, "C:evil.txt")

    def test_rejects_unc_path(self) -> None:
        if os.name != "nt":
            self.skipTest("UNC paths are Windows-only")
        with self.assertRaises(D.DeployPathError):
            D.contained_path(self.root, "//server/share/evil.txt")

    def test_rejects_nul_byte(self) -> None:
        with self.assertRaises(D.DeployPathError):
            D.contained_path(self.root, "sub/file\x00.py")

    def test_rejects_empty(self) -> None:
        with self.assertRaises(D.DeployPathError):
            D.contained_path(self.root, "")

    def test_rejects_non_string(self) -> None:
        with self.assertRaises(D.DeployPathError):
            D.contained_path(self.root, {"not": "a path"})


class DeployPathEscapeTests(_TmpTreeCase):
    """A deploy request must not be able to write outside project_root nor
    read outside staging_root."""

    def test_live_path_absolute_escape_writes_nothing(self) -> None:
        victim = self.outside / "victim.txt"
        victim.write_text("ORIGINAL", encoding="utf-8")
        self._stage("payload.py", "print('pwned')\n")
        req = self._write_request({
            "request_id": "esc1",
            "files": [{"staged": "payload.py", "live": str(victim)}],
        })
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")
        self.assertEqual(victim.read_text(encoding="utf-8"), "ORIGINAL")

    def test_live_path_parent_traversal_writes_nothing(self) -> None:
        self._stage("payload.py")
        req = self._write_request({
            "request_id": "esc2",
            "files": [{"staged": "payload.py",
                       "live": "../outside/traversed.txt"}],
        })
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")
        self.assertFalse((self.outside / "traversed.txt").exists())

    def test_staged_path_escape_cannot_exfiltrate(self) -> None:
        # The sharp shape: `staged` pointing at a secret outside the staging
        # root copies that secret INTO the project tree, where the dashboard
        # static route would then serve it.
        secret = self.outside / "API-Key-Claude.txt"
        secret.write_text("sk-ant-SECRET-VALUE", encoding="utf-8")
        req = self._write_request({
            "request_id": "esc3",
            "files": [{"staged": str(secret), "live": "web/leaked.txt"}],
        })
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")
        self.assertFalse((self.project / "web" / "leaked.txt").exists())
        self.assertNotIn("SECRET-VALUE", json.dumps(result))

    def test_request_id_traversal_cannot_place_restart_file(self) -> None:
        self._stage("payload.py")
        req = self._write_request({
            "request_id": "../../outside/pwn",
            "files": [{"staged": "payload.py", "live": "app_file.py"}],
            "force_restart": True,
        })
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")
        self.assertFalse((self.outside / "pwn.restart.json").exists())


class SecretExclusionTests(_TmpTreeCase):
    """rc_supervisor.py:29 records that rollback excludes `ops/backups/` and
    `API-Key-Claude.txt`. The deploy script named the same file in a local
    `api_key` variable and never read it - the exclusion was declared and
    not implemented."""

    def test_api_key_file_cannot_be_deployed(self) -> None:
        self._stage("API-Key-Claude.txt", "sk-ant-INJECTED")
        req = self._write_request({
            "request_id": "sec1",
            "files": [{"staged": "API-Key-Claude.txt",
                       "live": "API-Key-Claude.txt"}],
        })
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")
        self.assertFalse((self.project / "API-Key-Claude.txt").exists())
        self.assertNotIn("INJECTED", json.dumps(result))

    def test_api_key_file_cannot_be_deployed_case_insensitively(self) -> None:
        self._stage("api-key-claude.TXT", "sk-ant-INJECTED")
        req = self._write_request({
            "request_id": "sec2",
            "files": [{"staged": "api-key-claude.TXT",
                       "live": "nested/api-key-claude.TXT"}],
        })
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")

    def test_api_key_file_name_is_request_configurable(self) -> None:
        self._stage("other-secret.txt", "value")
        req = self._write_request({
            "request_id": "sec3",
            "api_key_file": "other-secret.txt",
            "files": [{"staged": "other-secret.txt",
                       "live": "other-secret.txt"}],
        })
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")


class RollbackCompletenessTests(_TmpTreeCase):
    """A rollback that only restores files which already existed leaves every
    NEWLY ADDED file in place - the deploy is then not transactional in the
    one direction that matters, because a new module can shadow an import."""

    def _failing_deploy(self, files: list) -> dict:
        # health_file is never written by anything in this test, so the
        # heartbeat wait always times out and the deploy rolls back.
        req = self._write_request({"request_id": "rb1", "files": files})
        return D.do_deploy(req)

    def test_rollback_restores_a_modified_file(self) -> None:
        live = self.project / "mod.py"
        live.write_text("ORIGINAL = 1\n", encoding="utf-8")
        self._stage("mod.py", "REPLACED = 2\n")
        result = self._failing_deploy(
            [{"staged": "mod.py", "live": "mod.py"}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "health_check")
        self.assertTrue(result["rollback"])
        self.assertEqual(live.read_text(encoding="utf-8"), "ORIGINAL = 1\n")

    def test_rollback_removes_a_newly_created_file(self) -> None:
        live = self.project / "brand_new.py"
        self.assertFalse(live.exists())
        self._stage("brand_new.py", "NEW = 1\n")
        result = self._failing_deploy(
            [{"staged": "brand_new.py", "live": "brand_new.py"}])
        self.assertFalse(result["ok"])
        self.assertTrue(result["rollback"])
        self.assertFalse(
            live.exists(),
            "rollback left a newly created file on disk - the deploy is not "
            "transactional for added files")

    def test_rollback_removes_new_file_and_restores_old_in_one_batch(self) -> None:
        old = self.project / "old.py"
        old.write_text("OLD = 1\n", encoding="utf-8")
        self._stage("old.py", "OLD = 2\n")
        self._stage("added.py", "ADDED = 1\n")
        result = self._failing_deploy([
            {"staged": "old.py", "live": "old.py"},
            {"staged": "added.py", "live": "added.py"},
        ])
        self.assertFalse(result["ok"])
        self.assertEqual(old.read_text(encoding="utf-8"), "OLD = 1\n")
        self.assertFalse((self.project / "added.py").exists())


class CompileGateTests(_TmpTreeCase):
    """Characterization: a staged .py that will not compile must abort BEFORE
    anything is copied over a live file."""

    def test_syntax_error_aborts_before_copy(self) -> None:
        live = self.project / "good.py"
        live.write_text("OK = 1\n", encoding="utf-8")
        self._stage("good.py", "def broken(:\n")
        req = self._write_request({
            "request_id": "c1",
            "files": [{"staged": "good.py", "live": "good.py"}],
        })
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "compile")
        self.assertEqual(live.read_text(encoding="utf-8"), "OK = 1\n")

    def test_missing_staged_file_is_reported_not_raised(self) -> None:
        req = self._write_request({
            "request_id": "c2",
            "files": [{"staged": "absent.py", "live": "absent.py"}],
        })
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")

    def test_empty_file_list_is_reported_not_raised(self) -> None:
        req = self._write_request({"request_id": "c3", "files": []})
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")

    def test_file_entry_missing_keys_is_reported_not_raised(self) -> None:
        req = self._write_request({
            "request_id": "c4",
            "files": [{"staged": "x.py"}],
        })
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")


class AtomicWriteTests(unittest.TestCase):
    """WinError 5: os.replace raises PermissionError while a reader holds the
    destination open. `ops/runtime/control/commands/` and the deploy result
    files are polled by the app, so the contention is routine - the bounded
    backoff at core/polled_json.py:40-48 is the in-tree answer."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="rc_deploy_atomic_")
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_atomic_write_json_retries_through_permission_error(self) -> None:
        target = self.dir / "polled.json"
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(5, "Access is denied")
            return real_replace(src, dst)

        D.os.replace = flaky
        try:
            D.atomic_write_json(target, {"k": "v"})
        finally:
            D.os.replace = real_replace
        self.assertGreaterEqual(calls["n"], 3)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         {"k": "v"})

    def test_atomic_write_json_re_raises_after_the_retry_budget(self) -> None:
        target = self.dir / "wedged.json"
        real_replace = os.replace

        def always_denied(src, dst):
            raise PermissionError(5, "Access is denied")

        D.os.replace = always_denied
        try:
            with self.assertRaises(PermissionError):
                D.atomic_write_json(target, {"k": "v"})
        finally:
            D.os.replace = real_replace

    def test_copy_atomic_retries_through_permission_error(self) -> None:
        src = self.dir / "src.txt"
        src.write_text("body", encoding="utf-8")
        dst = self.dir / "dst.txt"
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(s, d):
            calls["n"] += 1
            if calls["n"] <= 1:
                raise PermissionError(5, "Access is denied")
            return real_replace(s, d)

        D.os.replace = flaky
        try:
            D.copy_atomic(src, dst)
        finally:
            D.os.replace = real_replace
        self.assertEqual(dst.read_text(encoding="utf-8"), "body")


class HeartbeatTests(unittest.TestCase):
    """Characterization of the run_id acceptance matrix documented in
    `wait_for_heartbeat`'s own docstring - pinned so a rewrite cannot
    silently change which process counts as recovered."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="rc_deploy_hb_")
        self.health = Path(self._tmp.name) / "health.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_health(self, payload: dict) -> None:
        self.health.write_text(json.dumps(payload), encoding="utf-8")
        # Push the mtime forward so it is unambiguously newer than 0.0.
        os.utime(self.health, (2_000_000_000, 2_000_000_000))

    def test_same_run_id_is_accepted(self) -> None:
        self._write_health({"alive": True, "run_id": "abc"})
        self.assertTrue(D.wait_for_heartbeat(
            self.health, 0.0, 1.0, expected_run_id="abc"))

    def test_different_run_id_is_rejected_without_allow_new_run(self) -> None:
        self._write_health({"alive": True, "run_id": "xyz"})
        self.assertFalse(D.wait_for_heartbeat(
            self.health, 0.0, 0.4, expected_run_id="abc"))

    def test_different_run_id_is_accepted_with_allow_new_run(self) -> None:
        self._write_health({"alive": True, "run_id": "xyz"})
        self.assertTrue(D.wait_for_heartbeat(
            self.health, 0.0, 1.0, expected_run_id="abc", allow_new_run=True))

    def test_not_alive_is_rejected(self) -> None:
        self._write_health({"alive": False, "run_id": "abc"})
        self.assertFalse(D.wait_for_heartbeat(
            self.health, 0.0, 0.4, expected_run_id="abc"))

    def test_stale_mtime_is_rejected(self) -> None:
        self._write_health({"alive": True, "run_id": "abc"})
        stale_floor = self.health.stat().st_mtime
        self.assertFalse(D.wait_for_heartbeat(
            self.health, stale_floor, 0.4, expected_run_id="abc"))

    def test_corrupt_health_json_does_not_raise(self) -> None:
        self.health.write_text("{not json", encoding="utf-8")
        os.utime(self.health, (2_000_000_000, 2_000_000_000))
        self.assertFalse(D.wait_for_heartbeat(self.health, 0.0, 0.4))

    def test_missing_health_file_does_not_raise(self) -> None:
        self.assertFalse(D.wait_for_heartbeat(
            Path(self._tmp.name) / "absent.json", 0.0, 0.3))


class BackupPruneTests(_TmpTreeCase):
    """The prune swallowed every exception with a bare `except Exception:
    pass`, so a wedged retention sweep was indistinguishable from a clean
    one. It stays fail-soft - a prune failure must not fail a good deploy -
    but the reason now reaches the result payload."""

    def test_prune_failure_is_surfaced_not_swallowed(self) -> None:
        req = {"backup_retention_count": "not-an-int"}
        errors: list = []
        kept = D.prune_backups(self.project / "ops" / "backups", req, errors)
        self.assertEqual(kept, 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("ValueError", errors[0])

    def test_prune_keeps_the_newest_n(self) -> None:
        backups = self.project / "ops" / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        for stamp in ("20260801-000000-a", "20260802-000000-b",
                      "20260803-000000-c", "20260804-000000-d"):
            (backups / stamp).mkdir()
        errors: list = []
        removed = D.prune_backups(backups, {"backup_retention_count": 2},
                                  errors)
        self.assertEqual(errors, [])
        self.assertEqual(removed, 2)
        surviving = sorted(p.name for p in backups.iterdir())
        self.assertEqual(surviving,
                         ["20260803-000000-c", "20260804-000000-d"])

    def test_prune_on_a_missing_backups_dir_is_a_no_op(self) -> None:
        errors: list = []
        removed = D.prune_backups(self.project / "nope", {}, errors)
        self.assertEqual(removed, 0)
        self.assertEqual(errors, [])

    # - RM-363 sibling sweep: the guard was off by one --------------------

    def _four_backups(self) -> Path:
        backups = self.project / "ops" / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        for stamp in ("20260801-000000-a", "20260802-000000-b",
                      "20260803-000000-c", "20260804-000000-d"):
            (backups / stamp).mkdir()
        return backups

    def test_a_retention_of_zero_is_refused_and_deletes_nothing(self) -> None:
        """The guard rejected `< 0` and admitted `0`, which is the one
        degenerate value a "keep newest N" slice cannot survive:
        `all_bkps[0:]` is EVERY backup and each one is rmtree'd. Worse than
        the supervisor's copy, because `prune_backups` runs after the health
        check inside a live deploy, so the in-flight deploy's own rollback
        snapshot lives under the same root and goes with the history.
        """
        backups = self._four_backups()
        errors: list = []

        removed = D.prune_backups(backups, {"backup_retention_count": 0},
                                  errors)

        self.assertEqual(removed, 0)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("backup_retention_count", errors[0])
        self.assertEqual(len(list(backups.iterdir())), 4,
                         "a keep-zero policy deleted backups")

    def test_a_negative_retention_still_deletes_nothing(self) -> None:
        """Already refused before RM-363; pinned so the widened bound cannot
        quietly narrow back to `< 0` and lose the negative case too."""
        backups = self._four_backups()
        errors: list = []

        removed = D.prune_backups(backups, {"backup_retention_count": -1},
                                  errors)

        self.assertEqual(removed, 0)
        self.assertEqual(len(errors), 1, errors)
        self.assertEqual(len(list(backups.iterdir())), 4)

    def test_a_retention_of_one_still_prunes(self) -> None:
        """Anti-vacuity: the smallest LEGAL value must still do its job, or
        the guard has disabled the feature instead of bounding it."""
        backups = self._four_backups()
        errors: list = []

        removed = D.prune_backups(backups, {"backup_retention_count": 1},
                                  errors)

        self.assertEqual(errors, [])
        self.assertEqual(removed, 3)
        self.assertEqual([p.name for p in backups.iterdir()],
                         ["20260804-000000-d"])


class RequestValidationTests(_TmpTreeCase):
    """What happens on merely WRONG input, distinct from hostile input."""

    def test_files_not_a_list_is_reported_not_raised(self) -> None:
        req = self._write_request({"request_id": "v1", "files": {"a": 1}})
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")
        # Assert the SHAPE check fired, not just that something failed.
        # Mutation-tested: without the `isinstance(files, list)` guard a dict
        # still fails, but one item later and with the wrong diagnosis
        # ("files[0] must be an object"), so a bare phase assertion here
        # passes over a deleted guard.
        self.assertIn("must be a list", result["error"])
        self.assertIn("dict", result["error"])

    def test_file_entry_not_a_dict_is_reported_not_raised(self) -> None:
        req = self._write_request({"request_id": "v2", "files": ["nope"]})
        result = D.do_deploy(req)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")

    def test_missing_project_root_is_reported_not_raised(self) -> None:
        self.request_path.write_text(
            json.dumps({"request_id": "v3", "files": []}), encoding="utf-8")
        result = D.do_deploy(self.request_path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "validate")

    def test_result_always_carries_request_id_and_timestamp(self) -> None:
        req = self._write_request({"request_id": "v4", "files": []})
        result = D.do_deploy(req)
        self.assertEqual(result["request_id"], "v4")
        self.assertIn("handled_at", result)


if __name__ == "__main__":
    unittest.main()
