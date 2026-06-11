"""fetch_all prunes stale data/meta_build/ddragon/<semver>/ cache dirs.

Deep-audit P1b (item 397): the bundle cache accreted one ~8.7 MB tracked dir
per patch forever (16.8.1/16.10.1 git-rm'd this cycle per the gemini-confirmed
current+previous retention ruling). fetch_all now prunes beyond the window
after a successful pull, reusing the mirror's junction-safe helper.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lib.ddragon.fetch as fetch_mod


def _seed(root: Path, names):
    for n in names:
        d = root / n
        d.mkdir(parents=True)
        (d / "champion.json").write_text("{}", encoding="utf-8")


def test_fetch_all_prunes_cache_beyond_current_plus_previous(tmp_path, monkeypatch):
    _seed(tmp_path, ["16.8.1", "16.10.1", "16.11.1", "16.12.1"])
    monkeypatch.setattr(fetch_mod, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(fetch_mod.DDragon, "pull_all", lambda self: {})
    monkeypatch.setattr(fetch_mod, "latest_version", lambda client=None: "16.12.1")

    out = fetch_mod.fetch_all()

    assert out["version"] == "16.12.1"
    survivors = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert survivors == ["16.11.1", "16.12.1"]
    assert (tmp_path / "_index.json").exists()


def test_fetch_all_prune_failure_does_not_break_fetch(tmp_path, monkeypatch):
    _seed(tmp_path, ["16.11.1", "16.12.1"])
    monkeypatch.setattr(fetch_mod, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(fetch_mod.DDragon, "pull_all", lambda self: {})
    monkeypatch.setattr(fetch_mod, "latest_version", lambda client=None: "16.12.1")

    def boom(*a, **k):
        raise OSError("locked")
    monkeypatch.setattr(fetch_mod, "prune_stale_versions", boom)

    out = fetch_mod.fetch_all()  # must not raise
    assert out["version"] == "16.12.1"
