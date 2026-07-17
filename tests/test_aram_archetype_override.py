"""DSP3 (DS permutation swarm Cluster A) - ARAM archetype-override seam.

Cross-eval Cluster A: ``get_archetype_for`` routes each champ to its KIT
archetype (correct by tag / damage-axis), but rewind ARAM win-data favors a
DIFFERENT build axis for a cluster of champions, so the kit-default scorer's
whole pool misses the empirically winning ARAM build (Kayle/KogMaw win on
on-hit carry, not AP mage; Zilean/Shaco/Shyvana win on AP, not their
hps/burst/hybrid kit axis; Taric wins as tank).

The fix is a DEFAULT-OFF resolver seam: when ``prefer_aram_win_axis=True`` and
the champ has a WIN-anchored override AND no operator pick, the override
archetype is surfaced as primary (the kit default drops to secondary). Byte-
identical when OFF; operator picks are NEVER touched. The live default-ON flip
is EXCLUDED (do-not-flip-blind) -> docs/LIVE_GAME_GATED_SYNC.md.

The override table is built WIN-anchored from the cross-eval empirical (rewind
WIN+usage) data by ops/audit/ds_perm_swarm/build_aram_archetype_override.py.
These are characterization assertions against both the builder (hermetic
fixtures) and the shipped table (real champions).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import archetype_picks as ap
from ops.audit.ds_perm_swarm import build_aram_archetype_override as bld


@pytest.fixture(autouse=True)
def _fresh_caches():
    ap._invalidate_axis_cache()
    ap._invalidate_picks_cache()
    ap._invalidate_aram_overrides_cache()
    yield
    ap._invalidate_axis_cache()
    ap._invalidate_picks_cache()
    ap._invalidate_aram_overrides_cache()


# --------------------------------------------------------------------------- #
# Builder (hermetic - tiny fake cross-eval dirs, the 1.8GB rewind db is never
# opened; the builder reads only the small per-champ JSONs).
# --------------------------------------------------------------------------- #
def _write(d: Path, name: str, obj: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(
        json.dumps(obj), encoding="utf-8", newline="\n",
    )


def _seed(tmp_path: Path) -> tuple[Path, Path]:
    vd = tmp_path / "verdicts"
    dd = tmp_path / "data"
    # Kayle: archetype_ok=false, source=default, ARAM on-hit carry wins ->
    # override carry (ad axis), WIN-anchored by Blade of The Ruined King.
    _write(vd, "Kayle", {"champion": "Kayle", "archetype_ok": False,
                         "severity": "MISMATCH"})
    _write(dd, "Kayle", {
        "champion": "Kayle",
        "archetype": {"primary": "mage", "secondary": "carry",
                      "source": "default"},
        "empirical": {"ARAM": {
            "self": {"n": 18, "wr": 50.0, "items": [
                {"id": "3153", "name": "Blade of The Ruined King",
                 "n": 10, "wr": 60.0}]},
            "all": {"n": 143, "wr": 53.8, "items": [
                {"id": "3091", "name": "Wit's End", "n": 53, "wr": 56.6}]},
        }},
    })
    # Lulu: archetype_ok=false but it is an OPERATOR pick -> never overridden.
    _write(vd, "Lulu", {"champion": "Lulu", "archetype_ok": False,
                        "severity": "MISMATCH"})
    _write(dd, "Lulu", {
        "champion": "Lulu",
        "archetype": {"primary": "carry", "secondary": "mage",
                      "source": "user_cs"},
        "empirical": {"ARAM": {"all": {"n": 50, "wr": 50.0, "items": [
            {"id": "3124", "name": "Guinsoo's Rageblade", "n": 30,
             "wr": 60.0}]}}},
    })
    # Aatrox: archetype_ok=true -> not a Cluster-A candidate at all.
    _write(vd, "Aatrox", {"champion": "Aatrox", "archetype_ok": True,
                         "severity": "MINOR"})
    _write(dd, "Aatrox", {
        "champion": "Aatrox",
        "archetype": {"primary": "bruiser", "secondary": "tank",
                      "source": "default"},
        "empirical": {"ARAM": {"all": {"n": 100, "wr": 50.0, "items": []}}},
    })
    return vd, dd


def test_builder_emits_kayle_carry_override(tmp_path):
    vd, dd = _seed(tmp_path)
    table = bld.build_table(verdicts_dir=vd, data_dir=dd)
    champs = table["champions"]
    assert "Kayle" in champs
    assert champs["Kayle"]["override"] == "carry"
    assert champs["Kayle"]["default_primary"] == "mage"
    assert champs["Kayle"]["axis"] == "ad"
    # WIN evidence is the rewind winning item(s) on the override axis.
    names = [e["name"] for e in champs["Kayle"]["evidence"]]
    assert "Blade of The Ruined King" in names


def test_builder_skips_operator_pick(tmp_path):
    vd, dd = _seed(tmp_path)
    table = bld.build_table(verdicts_dir=vd, data_dir=dd)
    assert "Lulu" not in table["champions"]
    assert "Lulu" in table["skipped_user_pick"]


def test_builder_ignores_archetype_ok_true(tmp_path):
    vd, dd = _seed(tmp_path)
    table = bld.build_table(verdicts_dir=vd, data_dir=dd)
    assert "Aatrox" not in table["champions"]


def test_builder_raises_on_unmapped_divergent_champ(tmp_path):
    vd, dd = _seed(tmp_path)
    # A NEW archetype_ok=false + source=default champ not in the audited map
    # must fail LOUDLY (forces review) rather than silently drop.
    _write(vd, "Foozle", {"champion": "Foozle", "archetype_ok": False,
                         "severity": "MISMATCH"})
    _write(dd, "Foozle", {
        "champion": "Foozle",
        "archetype": {"primary": "mage", "source": "default"},
        "empirical": {"ARAM": {"all": {"n": 50, "wr": 50.0, "items": []}}},
    })
    with pytest.raises(ValueError):
        bld.build_table(verdicts_dir=vd, data_dir=dd)


def test_builder_win_anchor_gate_drops_unsupported(tmp_path):
    vd, dd = _seed(tmp_path)
    # Kayle override is carry(ad); if the empirical block has NO above-baseline
    # on-axis winner, the override is not WIN-anchored and must be skipped.
    _write(dd, "Kayle", {
        "champion": "Kayle",
        "archetype": {"primary": "mage", "source": "default"},
        "empirical": {"ARAM": {"all": {"n": 143, "wr": 53.8, "items": [
            # AP item only - does not match the carry(ad) signature.
            {"id": "6653", "name": "Liandry's Torment", "n": 40, "wr": 60.0}]}}},
    })
    table = bld.build_table(verdicts_dir=vd, data_dir=dd)
    assert "Kayle" not in table["champions"]
    assert "Kayle" in table["skipped_no_win_anchor"]


# --------------------------------------------------------------------------- #
# Shipped table (real artifact) - the 7 Cluster-A default-source overrides.
# --------------------------------------------------------------------------- #
# The 6 archetype_ok=false + source=default Cluster-A champs. MissFortune and
# Lulu are also archetype_ok=false but are user_cs operator picks -> excluded.
EXPECTED_OVERRIDES = {
    "Zilean": "mage", "Taric": "tank", "Shaco": "mage", "Shyvana": "mage",
    "KogMaw": "carry", "Kayle": "carry",
}


def test_shipped_table_has_expected_overrides():
    for champ, want in EXPECTED_OVERRIDES.items():
        assert ap.aram_archetype_override(champ) == want, champ


def test_operator_pick_champs_absent_from_shipped_table():
    # archetype_ok=false but user_cs -> NEVER overridden (operator owns the pick).
    assert ap.aram_archetype_override("Lulu") is None
    assert ap.aram_archetype_override("MissFortune") is None


# --------------------------------------------------------------------------- #
# Resolver seam (default-OFF byte-identical; never touches operator picks).
# --------------------------------------------------------------------------- #
def test_seam_off_is_byte_identical_default():
    # Kayle's kit default is onhit (Slice B Task 10 on-hit-AP roster, layered on
    # top of the P6-G1 axis correction's mage default); OFF must be unchanged.
    off = ap.get_archetype_for("Kayle")
    assert off["primary"] == "onhit"
    assert off["source"] == "default"
    explicit_off = ap.get_archetype_for("Kayle", prefer_aram_win_axis=False)
    assert explicit_off == off


def test_seam_on_overrides_kayle_to_carry():
    on = ap.get_archetype_for("Kayle", prefer_aram_win_axis=True)
    assert on["primary"] == "carry"
    assert on["secondary"] == "onhit"     # kit default (Slice B onhit) drops to alt-view
    assert on["source"] == ap.SOURCE_ARAM_WIN


def test_seam_on_leaves_non_override_champ_unchanged(monkeypatch):
    # Hermetic: no operator picks; Caitlyn (carry kit, no Cluster-A override)
    # must be byte-identical ON vs OFF.
    monkeypatch.setattr(ap, "_load_picks", lambda: {})
    on = ap.get_archetype_for("Caitlyn", prefer_aram_win_axis=True)
    off = ap.get_archetype_for("Caitlyn")
    assert on == off
    assert on["primary"] == "carry"
    assert on["source"] == "default"


def test_seam_never_touches_operator_pick(monkeypatch):
    # An operator pick on an override champ wins even with the seam ON.
    monkeypatch.setattr(ap, "_load_picks", lambda: {
        "Kayle": {"champion": "Kayle", "primary": "mage",
                  "secondary": "carry", "source": "user_cs"},
    })
    on = ap.get_archetype_for("Kayle", prefer_aram_win_axis=True)
    assert on["primary"] == "mage"
    assert on["source"] == "user_cs"


def test_override_helper_unknown_champ_is_none():
    assert ap.aram_archetype_override("NonexistentChamp123") is None
    assert ap.aram_archetype_override("") is None


def test_override_loader_fail_soft(monkeypatch, tmp_path):
    # Missing table file -> empty map, no override, no raise.
    monkeypatch.setattr(ap, "_ARAM_OVERRIDE_PATH", tmp_path / "missing.json")
    ap._invalidate_aram_overrides_cache()
    assert ap.aram_archetype_override("Kayle") is None
    on = ap.get_archetype_for("Kayle", prefer_aram_win_axis=True)
    assert on["primary"] == "onhit"       # falls back to kit default, no crash
