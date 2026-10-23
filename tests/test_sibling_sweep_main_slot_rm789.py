"""RM-789 - MAIN's checkout name gets a sibling-sweep name slot.

THE GAP
-------
``tools/sibling_name_sweep.py`` ``config_from_parts`` builds its name slots from
three keys of the gitignored ``ops/moon_sync_repos.json``: ``repos``,
``participants`` values and ``retired`` values. MAIN (the supervisor tree) is
deliberately in NONE of them, and each one is unusable for it because another
reader acts on it:

* ``repos`` - the poller polls every listed checkout and the outbound
  reciprocity check treats it as a sibling root.
* ``participants`` - ``ops/loop/inbox_tick.py`` ``_make_deliver`` prefers a
  participant path over the arming record's ``main.inbox`` (MAIN 0327 RULING:
  the record is the one source of MAIN's delivery paths).
* ``retired`` - ``inbox_tick.load_roster`` returns retired codes and
  ``validate_agreement`` refuses the whole record as
  ``malformed:counterparties_retired``, because MAIN is always a counterparty.

So a leak of MAIN's checkout name into a pushed diff matched no needle. The fix
is a fourth key, ``supervisor`` (code -> path, or a list of paths / bare
names, the ``retired`` shape), read ONLY by the sweep. The sweep stays ARMED
WITH A MEASURED ESCAPE RATE ABOVE ZERO; this closes one named escape.

Synthetic placeholders only: the names are ASSEMBLED at run time and resolve to
nothing, and the drive prefix is assembled so this file never trips the
sweep's config-free structural arm.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# HARD imports: an absent gate must not read as a green run.
from ops.loop import inbox_tick  # noqa: E402
from tools import inbox_responder_runner as runner  # noqa: E402
from tools import moon_sync_poller as poller  # noqa: E402
from tools import sibling_name_sweep as sweep  # noqa: E402

_NW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_Z = "0" * 40
_D = "C:" + "\\"
# Assembled, never spelled: neither name exists anywhere.
_MAIN_LEAF = "Synth" + "overseer" + "quay"
_MAIN_ALIAS = "Synth" + "helmname"
_SIB_LEAF = "Synth" + "wake" + "harbor"
_BASE = {
    "repos": [_D + _SIB_LEAF],
    "participants": {"QW": _D + _SIB_LEAF},
}
# A BARE mention: no drive path and no URL, so only the needle arm can see it
# (the config-free structural arm needs a drive-rooted path).
_BARE_LEAK = "per the " + _MAIN_LEAF + " ruling this is fine\n"


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("RC_MOON_SYNC_REPOS", raising=False)
    monkeypatch.delenv("RC_MOON_SYNC_NARROWED_NAMES", raising=False)
    monkeypatch.delenv("RC_SIBLING_SWEEP_BYPASS", raising=False)
    monkeypatch.setenv("RC_SIBLING_SWEEP_RUN_LOG", str(tmp_path / "runlog" / "runs.jsonl"))


def _root(tmp_path: Path, blob: dict, name: str = "cfgroot") -> Path:
    root = tmp_path / name
    (root / "ops").mkdir(parents=True, exist_ok=True)
    (root / "ops" / "moon_sync_repos.json").write_text(json.dumps(blob), encoding="ascii")
    return root


def _cfg(tmp_path: Path, blob: dict):
    return sweep.load_config(root=_root(tmp_path, blob), env={})


def _scan(cfg, text: str):
    return sweep.scan_text(
        sweep.build_needles(cfg), cfg.codes, text,
        path="probe.txt", source="TEST", status="A",
    )


def _with_main(value) -> dict:
    return dict(_BASE, supervisor={"MAIN": value})


# --------------------------------------------------------------------------
# 1. The slot
# --------------------------------------------------------------------------
def test_without_the_key_main_is_in_no_slot(tmp_path):
    """The measured gap, kept as the control: the existing keys hold no MAIN."""
    cfg = _cfg(tmp_path, _BASE)
    assert cfg.mode == sweep.MODE_ARMED
    assert _MAIN_LEAF not in cfg.names
    assert not _scan(cfg, _BARE_LEAK)


def test_the_supervisor_key_arms_a_slot_for_main_checkout_name(tmp_path):
    cfg = _cfg(tmp_path, _with_main(_D + _MAIN_LEAF))
    assert cfg.mode == sweep.MODE_ARMED
    assert _MAIN_LEAF in cfg.names
    assert _SIB_LEAF in cfg.names, "the sibling slots are unchanged"
    assert _scan(cfg, _BARE_LEAK), "bare-word arm"
    assert _scan(cfg, "see " + _D + _MAIN_LEAF + "\\notes.txt"), "drive-path arm"
    assert _scan(cfg, "https://github.com/someone/" + _MAIN_LEAF), "github URL arm"


def test_the_supervisor_code_is_carried_and_never_becomes_a_participant(tmp_path):
    cfg = _cfg(tmp_path, _with_main(_D + _MAIN_LEAF))
    assert "MAIN" in cfg.codes
    assert "MAIN" not in cfg.participants
    hits = _scan(cfg, "MAIN lives at " + _MAIN_LEAF + "\n")
    assert hits and hits[0].severity == sweep.SEV_RESOLUTION


def test_a_supervisor_value_may_be_a_list_of_path_and_bare_name(tmp_path):
    cfg = _cfg(tmp_path, _with_main([_D + _MAIN_LEAF, _MAIN_ALIAS]))
    assert _MAIN_LEAF in cfg.names and _MAIN_ALIAS in cfg.names
    assert _scan(cfg, "the " + _MAIN_ALIAS + " project said so")


def test_a_config_holding_only_the_supervisor_is_still_armed(tmp_path):
    cfg = _cfg(tmp_path, {"supervisor": {"MAIN": _D + _MAIN_LEAF}})
    assert cfg.mode == sweep.MODE_ARMED
    assert cfg.names == (_MAIN_LEAF,)


def test_a_junk_supervisor_shape_arms_nothing_and_breaks_nothing(tmp_path):
    for junk in ("MAIN", ["MAIN"], 7, None, {"MAIN": 7}, {"MAIN": [None, 3]}):
        cfg = _cfg(tmp_path, dict(_BASE, supervisor=junk))
        assert cfg.mode == sweep.MODE_ARMED, junk
        assert cfg.names == (_SIB_LEAF,), junk


def test_the_supervisor_slot_is_narrowable_by_declaration_only(tmp_path):
    cfg = _cfg(tmp_path, dict(_with_main(_D + _MAIN_LEAF), narrowed_names=[_MAIN_LEAF]))
    assert cfg.narrowed_names == (_MAIN_LEAF,)
    assert not _scan(cfg, _BARE_LEAK), "a declared narrowing drops the bare arm"
    assert _scan(cfg, "see " + _D + _MAIN_LEAF + "\\x"), "and keeps the path arm"


# --------------------------------------------------------------------------
# 2. The pre-push dry run halts on a synthetic leak (BACKLOG acceptance)
# --------------------------------------------------------------------------
def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True, creationflags=_NW,
    ).stdout.strip()


@pytest.fixture()
def leaked_push(tmp_path: Path):
    """A clone whose one unpushed commit carries a BARE mention of MAIN."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    for key, value in (
        ("user.email", "t@example.invalid"), ("user.name", "t"),
        ("core.autocrlf", "false"), ("commit.gpgsign", "false"),
        ("core.hooksPath", str(tmp_path / "nohooks")),
    ):
        _git(work, "config", key, value)
    _git(work, "remote", "add", "origin", str(remote))
    (work / "README.txt").write_text("base\n", encoding="ascii")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "--no-verify", "-m", "base")
    base = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "-q", "--no-verify", "origin", "main")
    (work / "notes.txt").write_text(_BARE_LEAK, encoding="ascii")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "--no-verify", "-m", "add notes")
    tip = _git(work, "rev-parse", "HEAD")
    return work, f"refs/heads/main {tip} refs/heads/main {base}"


def _dry_run(monkeypatch, work: Path, line: str, cfg_root: Path) -> int:
    monkeypatch.setattr(sweep, "REPO_ROOT", work)
    monkeypatch.setattr(sys, "stdin", io.StringIO(line + "\n"))
    return sweep.main(["--pre-push", "origin", "--config-root", str(cfg_root)])


def test_pre_push_dry_run_is_clean_without_the_key(leaked_push, monkeypatch, tmp_path):
    work, line = leaked_push
    rc = _dry_run(monkeypatch, work, line, _root(tmp_path, _BASE))
    assert rc == sweep.EXIT_CLEAN, "control: the gap is real, the bare MAIN name passes"


def test_pre_push_dry_run_halts_on_a_main_name_leak(leaked_push, monkeypatch, tmp_path, capsys):
    work, line = leaked_push
    rc = _dry_run(monkeypatch, work, line, _root(tmp_path, _with_main(_D + _MAIN_LEAF)))
    assert rc == sweep.EXIT_HALT
    err = capsys.readouterr()
    # The report names a SLOT, never the literal.
    assert _MAIN_LEAF not in err.out + err.err


def test_the_operator_push_gate_refuses_a_main_name_leak(tmp_path):
    """Sibling consumer of the same `load_config` name list (core/operator_push)."""
    from core import operator_push  # noqa: PLC0415

    assert operator_push.sweep_refusal(_BARE_LEAK, root=_root(tmp_path, _BASE)) is None
    refusal = operator_push.sweep_refusal(
        _BARE_LEAK, root=_root(tmp_path, _with_main(_D + _MAIN_LEAF), name="armed"))
    assert refusal and "refused" in refusal
    assert _MAIN_LEAF not in refusal


# --------------------------------------------------------------------------
# 3. No other reader of the file acts on the new key
# --------------------------------------------------------------------------
def test_inbox_tick_never_reads_the_supervisor_key(tmp_path):
    root = _root(tmp_path, _with_main(str(tmp_path / "mainco")))
    parts, retired = inbox_tick.load_roster(root)
    assert "MAIN" not in parts, "a MAIN participant would outrank the record for delivery"
    assert "MAIN" not in retired, "a retired MAIN would refuse the whole arming record"


def test_the_responder_never_reads_the_supervisor_key(tmp_path):
    mainco = tmp_path / "mainco"
    (mainco / "moon_sync_inbox").mkdir(parents=True)
    root = _root(tmp_path, {"participants": {}, "supervisor": {"MAIN": str(mainco)}})
    keep, _detail = runner.load_participants(root)
    assert "MAIN" not in keep


def test_the_poller_never_polls_the_supervisor(tmp_path, monkeypatch):
    mainco = tmp_path / "mainco"
    mainco.mkdir()
    root = _root(tmp_path, {"supervisor": {"MAIN": str(mainco)}})
    monkeypatch.setattr(poller, "_repo_config", lambda: root / "ops" / "moon_sync_repos.json")
    roots = poller._load_repo_roots()
    assert roots, "the poller always polls this repo, so an empty tuple is a broken read"
    assert all(Path(r).name != "mainco" for r in roots)


def test_the_example_template_documents_the_supervisor_key():
    blob = json.loads((REPO_ROOT / "ops" / "moon_sync_repos.example.json")
                      .read_text(encoding="utf-8"))
    assert "supervisor" in blob and "_supervisor_doc" in blob
    assert isinstance(blob["supervisor"], dict) and blob["supervisor"]
    cfg = sweep.config_from_parts([], {}, supervisor=blob["supervisor"])
    assert cfg.mode == sweep.MODE_ARMED, "the placeholder must parse as a slot"
