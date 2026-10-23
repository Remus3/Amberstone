"""RM-799 - the sibling-name sweep config no longer fails OPEN on a junk shape.

THE GAP (verifier-measured on RM-789)
-------------------------------------
``tools/sibling_name_sweep.py`` armed nothing and raised nothing - only the
banner's slot count moved - when the gitignored per-host config carried:

* a ``supervisor`` / ``retired`` value of the wrong shape (a top-level list, an
  int, a null, a dict / int / nested-list per-code value): ``_coded_slots``
  skipped it and ``load_config`` coerced a non-object to ``{}``;
* a mis-cased key (``Supervisor``): only the exact spelling was ever read;
* any ``RC_MOON_SYNC_REPOS`` override: the env branch called
  ``config_from_parts(paths, {}, narrowed)``, so MAIN's slot and every retired
  slot silently dropped.

THE DECISION
------------
The sweep already FAILS CLOSED on a broken config: an unreadable JSON file and
a config yielding zero names are both FAULT (exit 3, the push is refused). A
malformed or mis-spelled key the sweep reads follows that convention: FAULT,
with the key and its expected SHAPE named and the malformed COUNT stated, and
never the value. Under the env override (a repos-only path list) the per-host
file's sweep-only coded keys (``supervisor``, ``retired``) are still read,
validated the same way, and armed beside the override, so MAIN's slot stays.

The sweep stays ARMED WITH A MEASURED ESCAPE RATE ABOVE ZERO; this closes the
silent fail-open on a malformed config, nothing more.

Synthetic placeholders only: every name is ASSEMBLED at run time and resolves
to nothing, and the drive prefix is assembled so this file never trips the
sweep's config-free structural arm.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# HARD import: an absent gate must not read as a green run.
from tools import sibling_name_sweep as sweep  # noqa: E402

_D = "C:" + "\\"
_MAIN_LEAF = "Synth" + "keel" + "warden"
_RET_LEAF = "Synth" + "ember" + "dock"
_RET_ALIAS = "Synth" + "oldname"
_SIB_LEAF = "Synth" + "tide" + "mill"
_ENV_LEAF = "Synth" + "gale" + "yard"

_GOOD = {
    "repos": [_D + _SIB_LEAF],
    "participants": {"QW": _D + _SIB_LEAF},
    "narrowed_names": [],
    "retired": {"YQ": [_D + _RET_LEAF, _RET_ALIAS]},
    "supervisor": {"MAIN": _D + _MAIN_LEAF},
}
_BARE_MAIN = "per the " + _MAIN_LEAF + " ruling this is fine\n"
_SECRETS = (_MAIN_LEAF, _RET_LEAF, _RET_ALIAS, _SIB_LEAF, _ENV_LEAF)


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("RC_MOON_SYNC_REPOS", raising=False)
    monkeypatch.delenv("RC_MOON_SYNC_NARROWED_NAMES", raising=False)
    monkeypatch.delenv("RC_SIBLING_SWEEP_BYPASS", raising=False)
    monkeypatch.setenv("RC_SIBLING_SWEEP_RUN_LOG", str(tmp_path / "runlog" / "runs.jsonl"))


def _root(tmp_path: Path, blob, name: str = "cfgroot") -> Path:
    root = tmp_path / name
    (root / "ops").mkdir(parents=True, exist_ok=True)
    (root / "ops" / "moon_sync_repos.json").write_text(json.dumps(blob), encoding="ascii")
    return root


def _cfg(tmp_path: Path, blob, env=None, name: str = "cfgroot"):
    return sweep.load_config(root=_root(tmp_path, blob, name), env=env or {})


def _scan(cfg, text: str):
    return sweep.scan_text(
        sweep.build_needles(cfg), cfg.codes, text,
        path="probe.txt", source="TEST", status="A",
    )


def _no_value_in(text: str) -> None:
    for secret in _SECRETS:
        assert secret not in text, "a malformed-config report must never print a value"


def _assert_malformed(cfg, key: str, count: int = 1) -> None:
    assert cfg.mode == sweep.MODE_FAULT, (key, cfg.mode)
    assert len(cfg.malformed) == count, cfg.malformed
    assert cfg.names == (), "a FAULT config arms no partial slot set"
    banner = sweep.mode_banner(cfg)
    assert "FAULT" in banner
    assert f"{count} malformed key(s)" in banner
    assert f"'{key}'" in banner, banner
    _no_value_in(banner)


# --------------------------------------------------------------------------
# 1. A well-formed config is unchanged
# --------------------------------------------------------------------------
def test_a_well_formed_config_has_no_problem_and_the_same_slots(tmp_path):
    cfg = _cfg(tmp_path, _GOOD)
    assert cfg.mode == sweep.MODE_ARMED
    assert cfg.malformed == ()
    assert "malformed" not in sweep.mode_banner(cfg)
    direct = sweep.config_from_parts(
        _GOOD["repos"], _GOOD["participants"], (), _GOOD["retired"], _GOOD["supervisor"])
    assert cfg.names == direct.names == (_SIB_LEAF, _RET_LEAF, _RET_ALIAS, _MAIN_LEAF)
    assert cfg.codes == direct.codes == ("QW", "YQ", "MAIN")
    assert sweep.config_problems(_GOOD) == []


def test_absent_and_empty_slot_keys_are_not_malformed(tmp_path):
    for blob in (
        {"repos": [_D + _SIB_LEAF]},
        dict(_GOOD, retired={}, supervisor={}, participants={}, narrowed_names=[]),
        dict(_GOOD, roster={"ZZ": {"display": "x"}}, accounts={"probe_s": 300}),
        dict(_GOOD, _doc="free text", _supervisor_doc="free text"),
    ):
        cfg = _cfg(tmp_path, blob)
        assert cfg.mode == sweep.MODE_ARMED, blob
        assert cfg.malformed == (), blob


def test_the_example_template_is_itself_well_formed():
    blob = json.loads((REPO_ROOT / "ops" / "moon_sync_repos.example.json")
                      .read_text(encoding="utf-8"))
    assert sweep.config_problems(blob) == []


# --------------------------------------------------------------------------
# 2. Each junk shape of a coded slot key is a FAULT, never a silent gap
# --------------------------------------------------------------------------
_CODED_JUNK = [
    pytest.param(lambda leaf: [_D + leaf], id="top-level-list"),
    pytest.param(lambda leaf: 7, id="top-level-int"),
    pytest.param(lambda leaf: _D + leaf, id="top-level-string"),
    pytest.param(lambda leaf: None, id="top-level-null"),
    pytest.param(lambda leaf: {"MAIN": {"path": _D + leaf}}, id="dict-value"),
    pytest.param(lambda leaf: {"MAIN": 7}, id="int-value"),
    pytest.param(lambda leaf: {"MAIN": [[_D + leaf]]}, id="nested-list-value"),
    pytest.param(lambda leaf: {"MAIN": [_D + leaf, 3]}, id="list-with-non-string"),
    pytest.param(lambda leaf: {"MAIN": []}, id="empty-list-value"),
    pytest.param(lambda leaf: {"MAIN": _D[:2]}, id="value-names-no-checkout"),
    pytest.param(lambda leaf: {"  ": _D + leaf}, id="blank-code"),
]


@pytest.mark.parametrize("key", ["supervisor", "retired"])
@pytest.mark.parametrize("junk", _CODED_JUNK)
def test_a_junk_coded_slot_shape_is_a_named_fault(tmp_path, key, junk):
    blob = dict(_GOOD)
    blob[key] = junk(_MAIN_LEAF)
    cfg = _cfg(tmp_path, blob)
    _assert_malformed(cfg, key)
    assert sweep.CONFIG_KEY_SHAPES[key] in cfg.detail, "the expected shape is named"


@pytest.mark.parametrize(
    "key, junk",
    [
        pytest.param("repos", _D + _SIB_LEAF, id="repos-string"),
        pytest.param("repos", [{"path": _D + _SIB_LEAF}], id="repos-dict-item"),
        pytest.param("participants", [_D + _SIB_LEAF], id="participants-list"),
        pytest.param("participants", {"QW": [_D + _SIB_LEAF]}, id="participants-list-value"),
        pytest.param("narrowed_names", _SIB_LEAF, id="narrowed-string"),
        pytest.param("narrowed_names", [3], id="narrowed-int-item"),
    ],
)
def test_a_junk_shape_of_any_key_the_sweep_reads_is_a_named_fault(tmp_path, key, junk):
    blob = dict(_GOOD)
    blob[key] = junk
    cfg = _cfg(tmp_path, blob)
    _assert_malformed(cfg, key)
    assert sweep.CONFIG_KEY_SHAPES[key] in cfg.detail


def test_a_top_level_non_object_is_a_fault_not_a_crash(tmp_path):
    cfg = _cfg(tmp_path, [_D + _SIB_LEAF])
    assert cfg.mode == sweep.MODE_FAULT
    assert len(cfg.malformed) == 1
    assert "JSON object" in cfg.detail
    _no_value_in(sweep.mode_banner(cfg))


# --------------------------------------------------------------------------
# 3. A mis-cased known key is malformed, not ignored
# --------------------------------------------------------------------------
@pytest.mark.parametrize("spelled", ["Supervisor", "SUPERVISOR", " supervisor"])
def test_a_mis_cased_supervisor_key_is_a_named_fault(tmp_path, spelled):
    blob = {k: v for k, v in _GOOD.items() if k != "supervisor"}
    blob[spelled] = {"MAIN": _D + _MAIN_LEAF}
    cfg = _cfg(tmp_path, blob)
    _assert_malformed(cfg, "supervisor")
    assert "mis-spelled" in cfg.detail


@pytest.mark.parametrize("spelled", ["Retired", "Repos", "Participants", "Narrowed_Names"])
def test_every_mis_cased_key_the_sweep_reads_is_a_fault(tmp_path, spelled):
    cfg = _cfg(tmp_path, dict(_GOOD, **{spelled: {}}))
    _assert_malformed(cfg, spelled.lower())


def test_problems_are_counted_one_per_key(tmp_path):
    blob = {k: v for k, v in _GOOD.items() if k != "retired"}
    blob["supervisor"] = 7
    blob["Retired"] = {"YQ": _D + _RET_LEAF}
    cfg = _cfg(tmp_path, blob)
    _assert_malformed(cfg, "supervisor", count=2)
    assert "'retired'" in cfg.detail


# --------------------------------------------------------------------------
# 4. The count reaches the pre-push output and the run record
# --------------------------------------------------------------------------
def _records(tmp_path: Path) -> list:
    path = tmp_path / "runlog" / "runs.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="ascii").splitlines() if ln]


def test_pre_push_refuses_a_malformed_config_and_records_the_count(
    tmp_path, monkeypatch, capsys
):
    root = _root(tmp_path, dict(_GOOD, supervisor=[_D + _MAIN_LEAF]))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    rc = sweep.main(["--pre-push", "origin", "--config-root", str(root)])
    assert rc == sweep.EXIT_FAULT
    err = capsys.readouterr().err
    assert "1 malformed key(s)" in err and "'supervisor'" in err
    _no_value_in(err)
    rec = _records(tmp_path)[-1]
    assert rec["malformed"] == 1
    assert rec["cfg"] == sweep.MODE_FAULT and rec["verdict"] == "fault"


def test_a_well_formed_run_records_zero_malformed(tmp_path, capsys):
    root = _root(tmp_path, _GOOD)
    target = tmp_path / "clean.txt"
    target.write_text("nothing to see here\n", encoding="ascii")
    rc = sweep.main(["--scan-file", str(target), "--config-root", str(root)])
    assert rc == sweep.EXIT_CLEAN
    assert "malformed" not in capsys.readouterr().err
    assert _records(tmp_path)[-1]["malformed"] == 0


def test_the_operator_push_gate_refuses_a_malformed_config(tmp_path):
    from core import operator_push  # noqa: PLC0415

    refusal = operator_push.sweep_refusal(
        "harmless text", root=_root(tmp_path, dict(_GOOD, Supervisor={})))
    assert refusal and "refused" in refusal
    _no_value_in(refusal)


# --------------------------------------------------------------------------
# 5. The env override keeps the per-host file's coded slots armed
# --------------------------------------------------------------------------
def _env(*leaves: str) -> dict:
    return {"RC_MOON_SYNC_REPOS": os.pathsep.join(_D + leaf for leaf in leaves)}


def test_env_override_keeps_main_and_retired_slots_armed(tmp_path):
    cfg = _cfg(tmp_path, _GOOD, env=_env(_ENV_LEAF))
    assert cfg.mode == sweep.MODE_ARMED
    assert cfg.source == "RC_MOON_SYNC_REPOS"
    assert cfg.malformed == ()
    assert _ENV_LEAF in cfg.names, "the override's own paths still arm"
    assert _MAIN_LEAF in cfg.names, "MAIN's slot survives the override"
    assert _RET_LEAF in cfg.names and _RET_ALIAS in cfg.names
    assert "MAIN" in cfg.codes and "YQ" in cfg.codes
    assert _scan(cfg, _BARE_MAIN), "a bare MAIN-name leak halts under the override"
    # The override still REPLACES repos and carries no participants.
    assert _SIB_LEAF not in cfg.names
    assert "QW" not in cfg.codes and cfg.participants == {}


def test_env_override_without_a_file_is_unchanged(tmp_path):
    root = tmp_path / "nofile"
    (root / "ops").mkdir(parents=True)
    cfg = sweep.load_config(root=root, env=_env(_ENV_LEAF))
    assert cfg.mode == sweep.MODE_ARMED
    assert cfg.names == (_ENV_LEAF,) and cfg.codes == ()


def test_env_override_carries_the_file_narrowing_for_coded_slots_only(tmp_path):
    blob = dict(_GOOD, narrowed_names=[_MAIN_LEAF, _ENV_LEAF])
    cfg = _cfg(tmp_path, blob, env=_env(_ENV_LEAF))
    assert cfg.narrowed_names == (_MAIN_LEAF,), (
        "a coded slot keeps its declared strength under the override, and a file "
        "declaration never weakens a slot the override itself supplies")
    assert not _scan(cfg, _BARE_MAIN)
    assert _scan(cfg, "see " + _D + _MAIN_LEAF + "\\x"), "the path arm stays"


@pytest.mark.parametrize("key", ["supervisor", "retired"])
def test_env_override_faults_on_a_junk_coded_slot(tmp_path, key):
    cfg = _cfg(tmp_path, dict(_GOOD, **{key: [_D + _MAIN_LEAF]}), env=_env(_ENV_LEAF))
    _assert_malformed(cfg, key)
    assert "RC_MOON_SYNC_REPOS" in cfg.detail


def test_env_override_faults_on_a_mis_cased_supervisor(tmp_path):
    blob = {k: v for k, v in _GOOD.items() if k != "supervisor"}
    blob["Supervisor"] = {"MAIN": _D + _MAIN_LEAF}
    cfg = _cfg(tmp_path, blob, env=_env(_ENV_LEAF))
    _assert_malformed(cfg, "supervisor")


def test_env_override_faults_on_an_unreadable_file(tmp_path):
    root = tmp_path / "broken"
    (root / "ops").mkdir(parents=True)
    (root / "ops" / "moon_sync_repos.json").write_text("{not json", encoding="ascii")
    cfg = sweep.load_config(root=root, env=_env(_ENV_LEAF))
    assert cfg.mode == sweep.MODE_FAULT
    assert "unreadable" in cfg.detail


def test_env_override_ignores_keys_it_does_not_read(tmp_path):
    """Under the override only the coded keys are consumed, so only they can
    fault it; a junk repos / participants in the file changes nothing."""
    blob = dict(_GOOD, repos="junk", participants=["junk"], Repos=[])
    cfg = _cfg(tmp_path, blob, env=_env(_ENV_LEAF))
    assert cfg.mode == sweep.MODE_ARMED
    assert cfg.malformed == ()
    assert _MAIN_LEAF in cfg.names


# --------------------------------------------------------------------------
# 6. The honest-claim phrasing is unchanged where it lives
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "rel, phrase",
    [
        ("CLAUDE.md", '"ARMED WITH A MEASURED ESCAPE RATE ABOVE ZERO" - never claim '
                      '"sibling names cannot leak", never soften that phrasing.'),
        ("docs/SIBLING_SWEEP_AND_BOUNDARY.md",
         '"the sweep half is ARMED WITH A MEASURED ESCAPE RATE ABOVE ZERO", never '
         '"sibling names cannot leak"'),
        ("tools/sibling_name_sweep.py",
         'The honest claim after this lands is "the sweep half is armed\n'
         'with a measured escape rate above zero", never "sibling names cannot leak".'),
    ],
)
def test_the_escape_rate_phrasing_is_unchanged(rel, phrase):
    text = (REPO_ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert phrase in text, rel
