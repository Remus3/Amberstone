"""RM-353: a DDragon version string must be validated before it becomes a path segment.

`DDragon.__init__` did `self._root = CACHE_ROOT / self._version` followed by
`self._root.mkdir(parents=True, exist_ok=True)` with `self._version` taken
straight off the wire - `latest_version` guarded only `if not versions`. Two
ways that escapes the cache root:

  * a list element such as ``"../../evil"`` is joined by `pathlib` without
    normalisation, and on Windows an ANCHORED element (``"C:/Users/.../evil"``)
    REPLACES the left operand entirely;
  * a JSON *string* body rather than a list makes ``versions[0]`` a single
    CHARACTER - ``"maintenance"`` yields ``"m"`` - so the cache silently forks
    into a junk directory that nothing ever reads.

The residue is permanent either way: `tools/ddragon_mirror_refresh.py`
`_SEMVER_DIR` only ever considers ``^\\d+\\.\\d+\\.\\d+$`` directories for
pruning, so a non-semver dir is never a prune candidate. That is why the
accepted shape here is deliberately the SAME shape the pruner recognises -
anything this code creates must be something the retention pass can later
remove. `test_every_accepted_version_is_a_prune_candidate` pins that tie.

The same defense-in-depth reasoning is already written down in the tree for
DDragon icon FILENAMES at `lib/icons/downloader.py:37-43` (`_safe_basename`);
the version string simply never got the same treatment.

Two guards, each load-bearing for a different input, which is why breaking
either one turns a different test red:

  * `latest_version` guards the WIRE (a poisoned versions.json reaching any
    public caller - it is exported from `lib/ddragon/__init__.py`);
  * `DDragon.__init__` guards the PATH (an explicit ``version=`` argument -
    `agents/agent2_backend/pipeline/orchestrator.py:98`, `fetch_all`, and
    `lib/icons/downloader.py:94` all pass one in - was `:64` until the RM-359
    change added `_safe_relpath` above the class and shifted it).

Sibling sweep (same root cause, wire-derived version -> created directory):
`tools/ddragon_mirror_refresh.py` `resolve_latest_version` feeds
``META_DIR / version`` (`:303`, `:310`), ``META_DIR / version /
"champion_detail"`` (`:339`) and ``WEB_DIR / version`` (`:552`), and `main()`
also accepts a ``--version`` string from the command line. Both are covered
below.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lib.ddragon.fetch as fetch_mod  # noqa: E402
import tools.ddragon_mirror_refresh as ddr  # noqa: E402
from lib.http.client import Response  # noqa: E402


class _StubClient:
    """Replays one canned Response for every GET."""

    def __init__(self, response: Response) -> None:
        self._response = response
        self.urls: list[str] = []

    def get(self, url: str, **kwargs):
        self.urls.append(url)
        return self._response


def _versions_resp(body: bytes, status: int = 200) -> Response:
    return Response(status, {}, body, f"{fetch_mod.DDRAGON_BASE}/api/versions.json")


def _wire_client(monkeypatch, body: bytes) -> _StubClient:
    """Point `lib.ddragon.fetch` at a stub client serving `body`."""
    stub = _StubClient(_versions_resp(body))
    monkeypatch.setattr(fetch_mod, "get_client", lambda: stub)
    return stub


def _sandbox_cache_root(monkeypatch, tmp_path: Path) -> Path:
    """Nest the cache root three deep so a ``../../..`` escape lands INSIDE tmp.

    Without the nesting the traversal case would create a directory beside the
    pytest tmp dir when the guard is removed for a mutation check.
    """
    root = tmp_path / "data" / "meta_build" / "ddragon"
    monkeypatch.setattr(fetch_mod, "CACHE_ROOT", root)
    return root


# ---------------------------------------------------------------------------
# The validator itself.


def test_validate_version_accepts_a_real_patch_string():
    """The happy path must survive: every version this repo has ever cached."""
    for good in ("16.15.1", "16.17.1", "5.24.2", "10.1.1"):
        assert ddr.validate_version(good) == good


def test_validate_version_rejects_a_traversal_element():
    """The acceptance case: ``../../evil`` must never reach `pathlib`."""
    for bad in ("../../evil", "../../../pwned", "..", ".", "16.15.1/../..",
                "a/b", "a\\b"):
        with pytest.raises(ValueError):
            ddr.validate_version(bad)


def test_validate_version_rejects_a_windows_anchored_path():
    """On Windows an anchored element REPLACES the left operand entirely."""
    for bad in ("C:/Users/Administrator/Desktop/evil", "C:evil", "/etc/passwd",
                "\\\\server\\share"):
        with pytest.raises(ValueError):
            ddr.validate_version(bad)


def test_validate_version_rejects_a_bare_word():
    """A JSON *string* body makes ``versions[0]`` one character.

    ``"maintenance"`` yields ``"m"`` - a perfectly legal directory name, which
    is exactly why a basename-only check (the `_safe_basename` shape used for
    icon filenames) is NOT sufficient here and a version SHAPE is required.
    """
    for bad in ("m", "maintenance", "latest", "16", "16.15", "16.15.1.4",
                "16.15.1-beta", " 16.15.1", "16.15.1 "):
        with pytest.raises(ValueError):
            ddr.validate_version(bad)


def test_validate_version_rejects_a_trailing_newline():
    """`$` matches BEFORE a trailing newline, so `.match` would wave this through.

    "16.15.1\\n" is not a traversal, but it is a control character in a name
    this code is about to `mkdir`. The validator uses `fullmatch` for exactly
    this case; the pruner keeps `.match` so it would still recognise such a
    directory as a prune candidate.
    """
    for bad in ("16.15.1\n", "16.15.1\r\n", "16.15.1\n../evil"):
        with pytest.raises(ValueError):
            ddr.validate_version(bad)


def test_validate_version_rejects_non_str_and_empty():
    """A malformed body can yield a dict, an int or None, not just a bad str."""
    for bad in (None, "", 16, 16.15, {"v": "16.15.1"}, ["16.15.1"], True):
        with pytest.raises(ValueError):
            ddr.validate_version(bad)


def test_every_accepted_version_is_a_prune_candidate():
    """The invariant that makes the residue non-permanent.

    `prune_stale_versions` only considers `_SEMVER_DIR` directories, so a dir
    this code creates under a version the validator ACCEPTED must always be
    something the retention pass can later delete. Pinning both directions
    stops the two patterns drifting apart.
    """
    for good in ("16.15.1", "5.24.2"):
        assert ddr._SEMVER_DIR.match(ddr.validate_version(good))
    for bad in ("maintenance", "../../evil", "16.15"):
        with pytest.raises(ValueError):
            ddr.validate_version(bad)
        assert ddr._SEMVER_DIR.match(bad) is None


# ---------------------------------------------------------------------------
# ACCEPTANCE: DDragon() raises ValueError and creates nothing outside the root.


def test_ddragon_raises_on_traversal_from_the_wire_and_creates_nothing(
        monkeypatch, tmp_path):
    """ACCEPTANCE case 1: ``/api/versions.json`` returns ``["../../../pwned"]``."""
    _wire_client(monkeypatch, b'["../../../pwned"]')
    root = _sandbox_cache_root(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        fetch_mod.DDragon()

    # The escape target, had the join gone through.
    assert not (tmp_path / "pwned").exists()
    # And nothing was created inside the cache root either - the guard fires
    # BEFORE the mkdir, not after it.
    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


def test_ddragon_raises_on_a_bare_string_body_and_creates_nothing(
        monkeypatch, tmp_path):
    """ACCEPTANCE case 2: the body is the bare string ``"maintenance"``.

    ``versions[0]`` is then ``"m"``. This is the case a traversal-only check
    would wave through.
    """
    _wire_client(monkeypatch, b'"maintenance"')
    root = _sandbox_cache_root(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        fetch_mod.DDragon()

    assert not (root.parent / "m").exists()
    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


def test_ddragon_raises_on_a_windows_anchored_wire_version(monkeypatch, tmp_path):
    """An anchored element discards the cache root completely."""
    escape = tmp_path / "anchored_evil"
    _wire_client(monkeypatch, f'["{escape.as_posix()}"]'.encode())
    _sandbox_cache_root(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        fetch_mod.DDragon()

    assert not escape.exists()


def test_ddragon_rejects_an_explicit_traversal_version(monkeypatch, tmp_path):
    """The caller-supplied path, which the wire guard alone does NOT cover.

    `fetch_all(version=...)`, `IconDownloader(version=...)` and
    `orchestrator.py:98` all construct `DDragon` with a version they did not
    validate, so the constructor needs its own guard.
    """
    _wire_client(monkeypatch, b'["16.15.1"]')
    root = _sandbox_cache_root(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        fetch_mod.DDragon(version="../../../pwned")

    assert not (tmp_path / "pwned").exists()
    assert not root.exists()


def test_ddragon_happy_path_still_creates_the_cache_dir(monkeypatch, tmp_path):
    """The guard must not be over-broad - a real patch still works end to end."""
    _wire_client(monkeypatch, b'["16.15.1","16.14.1"]')
    root = _sandbox_cache_root(monkeypatch, tmp_path)

    dd = fetch_mod.DDragon()

    assert dd.version == "16.15.1"
    assert dd.cache_dir == root / "16.15.1"
    assert dd.cache_dir.is_dir()


def test_latest_version_rejects_a_poisoned_wire_entry():
    """The wire guard in isolation - `latest_version` is publicly exported."""
    stub = _StubClient(_versions_resp(b'["../../../pwned"]'))

    with pytest.raises(ValueError):
        fetch_mod.latest_version(client=stub)


def test_latest_version_still_returns_a_real_patch():
    """RM-352's happy path is unchanged by the RM-353 guard."""
    stub = _StubClient(_versions_resp(b'["16.15.1","16.14.1"]'))

    assert fetch_mod.latest_version(client=stub) == "16.15.1"


# ---------------------------------------------------------------------------
# Sibling sweep: the mirror tool has the same root cause on a second path.


def test_resolve_latest_version_rejects_a_traversal_entry(monkeypatch):
    """`resolve_latest_version` feeds META_DIR / WEB_DIR joins at :303/:339/:552."""
    class _Res:
        status = 200
        body = b'["../../../pwned"]'

    monkeypatch.setattr(ddr, "http_get", lambda *a, **k: _Res())

    with pytest.raises(ValueError):
        ddr.resolve_latest_version()


def test_resolve_latest_version_still_returns_a_real_patch(monkeypatch):
    class _Res:
        status = 200
        body = b'["16.15.1","16.14.1"]'

    monkeypatch.setattr(ddr, "http_get", lambda *a, **k: _Res())

    assert ddr.resolve_latest_version() == "16.15.1"


def test_main_rejects_a_traversal_cli_version(monkeypatch):
    """``--version`` is operator input and reaches the same joins.

    It also covers the case where `resolve_latest_version` is replaced (the
    mirror suite monkeypatches it), so the CLI path is guarded independently
    of the resolver.
    """
    monkeypatch.setattr(ddr, "read_index", lambda: {"latest_pulled": "16.15.1"})
    monkeypatch.setattr(ddr, "run", lambda *a, **k: None)

    with pytest.raises(ValueError):
        ddr.main(["--version", "../../../pwned", "--dry-run"])


# ---------------------------------------------------------------------------
# RM-359 sibling: the VERSION segment of `champion_detail` was guarded above,
# the CHAMPION KEY segment of the very same join was not.
#
# `pull_champion_detail` builds both halves from `champion_key`:
#
#     url  = f"{DDRAGON_BASE}/cdn/{version}/data/{LOCALE}/champion/{key}.json"
#     dest = META_DIR / version / "champion_detail" / f"{key}.json"
#
# and `champion_key` is a raw key off the wire - `pull_all_champion_details`
# takes `list((summary or {}).get("data", {}).keys())` where `summary` is the
# downloaded `champion.json` bundle. `_atomic_write_json` does
# `path.parent.mkdir(parents=True, exist_ok=True)` before writing, so a key of
# `../../../pwned` CREATES the escaped directory and writes into it.
#
# This is the same three-of-four root cause RM-359 fixed in
# `lib/icons/downloader.py`, and it lands in the file that DEFINES both
# validators: `_safe_basename` is applied to all eight image names in
# `enumerate_assets` and `_safe_relpath` to both rune paths, while this one
# wire string reached a mkdir with nothing applied.
#
# SEVERITY IS HIGHER HERE THAN IN THE ROW THAT FOUND IT. RM-359's own body
# recorded "the live twin is CORRECT ... only the unused library copy
# diverges". That is now measured false: `lib/icons/downloader.py` has zero
# production callers, whereas this module is scheduled task
# `RC-DDragonMirrorRefresh` (verified Ready on this box), running
# `--check-changed` daily at 03:30, which does NOT short-circuit `run()`.


def test_pull_champion_detail_rejects_a_traversal_key(monkeypatch, tmp_path):
    """A hostile champion key must create nothing and fetch nothing."""
    calls: list[str] = []

    class _Res:
        status = 200
        body = b'{"data": {}}'

    def _spy(url, *a, **k):
        calls.append(url)
        return _Res()

    monkeypatch.setattr(ddr, "http_get", _spy)
    monkeypatch.setattr(ddr, "META_DIR", tmp_path / "meta")

    assert ddr.pull_champion_detail("16.15.1", "../../../pwned") is None
    assert calls == []
    assert not (tmp_path / "pwned.json").exists()
    assert list(tmp_path.rglob("*.json")) == []


@pytest.mark.parametrize("key", [
    "..", ".", "../evil", "..\\evil", "/etc/passwd", "C:/evil", "a/b",
])
def test_pull_champion_detail_rejects_every_hostile_key(monkeypatch, tmp_path, key):
    monkeypatch.setattr(ddr, "META_DIR", tmp_path / "meta")
    monkeypatch.setattr(ddr, "http_get", lambda *a, **k: pytest.fail(
        f"fetched despite hostile key {key!r}"))

    assert ddr.pull_champion_detail("16.15.1", key) is None


def test_read_or_pull_champion_detail_rejects_without_delegating(monkeypatch, tmp_path):
    """The cache-read entry point rejects on its OWN, before it joins or delegates.

    Written this way deliberately. The obvious version of this test - assert it
    returns None with `http_get` stubbed to fail - passes even with this
    guard deleted, because the call falls through to the now-guarded
    `pull_champion_detail` and is rejected one level down. Mutation-testing
    caught that: disabling this guard left the whole file green, which is the
    lane's own warning that a guard on a non-default path is untested.

    So the assertion is the one the guard actually makes: this function does
    not join `META_DIR / ... / f"{key}.json"` and does not stat it for an
    escaped key. Deleting the guard now turns this red.
    """
    monkeypatch.setattr(ddr, "META_DIR", tmp_path / "meta")
    monkeypatch.setattr(ddr, "pull_champion_detail", lambda *a, **k: pytest.fail(
        "delegated to the puller instead of rejecting the key here"))

    assert ddr.read_or_pull_champion_detail("16.15.1", "../../../pwned") is None


def test_pull_all_champion_details_drops_a_poisoned_key_and_keeps_the_rest(
        monkeypatch, tmp_path):
    """One hostile key in the bundle must not cost the other champions.

    The batch is the real blast radius: `run()` calls this with every key in
    the downloaded summary, so a fail-fast would turn one poisoned entry into
    a total mirror-refresh outage, and an unguarded pass writes outside
    META_DIR. Neither is acceptable; dropping the single bad key is.
    """
    monkeypatch.setattr(ddr, "META_DIR", tmp_path / "meta")

    class _Res:
        status = 200
        body = b'{"data": {"Ahri": {"id": "Ahri"}}}'

    monkeypatch.setattr(ddr, "http_get", lambda *a, **k: _Res())

    summary = {"data": {"Ahri": {}, "../../../pwned": {}}}
    out = ddr.pull_all_champion_details("16.15.1", summary, rate_limit=0.0)

    assert "Ahri" in out
    assert "../../../pwned" not in out
    assert list((tmp_path / "meta").rglob("pwned*")) == []


def test_a_real_champion_key_still_pulls_and_caches(monkeypatch, tmp_path):
    """The anti-over-correction guard: legitimate keys must keep working.

    Champion keys are plain alphanumerics (`Ahri`, `MonkeyKing`, `Chogath`),
    so `_safe_basename` is the right validator here - unlike the rune paths in
    RM-359, which are multi-segment and needed `_safe_relpath`.
    """
    monkeypatch.setattr(ddr, "META_DIR", tmp_path / "meta")

    class _Res:
        status = 200
        body = b'{"data": {"MonkeyKing": {"id": "MonkeyKing"}}}'

    monkeypatch.setattr(ddr, "http_get", lambda *a, **k: _Res())

    data = ddr.pull_champion_detail("16.15.1", "MonkeyKing")
    assert data == {"data": {"MonkeyKing": {"id": "MonkeyKing"}}}
    cached = tmp_path / "meta" / "16.15.1" / "champion_detail" / "MonkeyKing.json"
    assert cached.is_file()
