"""The two ds_perm_swarm table builders write through core.polled_json.

RM-258 residual (RM-1713): build_aram_archetype_override.py and
build_marksman_offclass_exempt.py hand-rolled `<out>.json.tmp` + os.replace,
a destination-derived scratch name two concurrent runs would share. They now
call core.polled_json.atomic_write_text, which keeps the bytes identical
(ensure_ascii JSON, indent 2, one trailing LF, no CR) and leaves no scratch
file behind.
"""
from __future__ import annotations

import json

import pytest

from ops.audit.ds_perm_swarm import (build_aram_archetype_override as aram,
                                     build_marksman_offclass_exempt as mark)

# Both mains read the keys they print; the champions map stays empty so the
# per-champ evidence print (aram only) has nothing to iterate.
TABLE = {"champions": {}, "note": "caf" + chr(0xE9), "considered_archetype_mismatch": 1,
         "ranged_marksmen_considered": 2, "skipped_user_pick": [],
         "skipped_no_win_anchor": []}


@pytest.mark.parametrize("mod", [aram, mark], ids=["aram", "marksman"])
def test_main_writes_exact_lf_bytes_and_leaves_no_scratch(
        mod, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.json"
    monkeypatch.setattr(mod, "_OUT_PATH", out)
    monkeypatch.setattr(mod, "build_table", lambda: dict(TABLE))
    mod.main()
    expected = json.dumps(dict(TABLE), indent=2,
                          ensure_ascii=True, sort_keys=False) + "\n"
    raw = out.read_bytes()
    assert raw == expected.encode("ascii")
    assert b"\r" not in raw
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.json"]
    assert "wrote" in capsys.readouterr().out


@pytest.mark.parametrize("mod", [aram, mark], ids=["aram", "marksman"])
def test_main_goes_through_polled_json(mod, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(mod, "_OUT_PATH", tmp_path / "out.json")
    monkeypatch.setattr(mod, "build_table", lambda: dict(TABLE))
    monkeypatch.setattr(mod, "atomic_write_text",
                        lambda p, t: seen.append((p, t)))
    mod.main()
    assert len(seen) == 1 and seen[0][0] == tmp_path / "out.json"
    assert seen[0][1].endswith("}\n")
