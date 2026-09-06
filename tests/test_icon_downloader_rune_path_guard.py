"""RM-359: the rune download path never validated its CDN-supplied icon string.

`lib/icons/downloader.py` carries `_safe_basename` (`:36`) with an explicit
audit rationale - "an attacker who successfully MITMs DDragon (TLS bypass)
could return ``image.full`` of ``../../../etc/x.png``". Three of the four
download methods route the wire value through it before use: `champions()`
(`:122`), `spells()` (`:139`) and `items()` (`:156`). `runes()` did not.

(All line numbers in this file are POST-change - they were re-derived after
the last edit, not carried over from the filed row. Adding `_safe_relpath`
shifted every call site below it down by 30 lines, and the first draft of
this docstring cited the pre-change numbers, which is
`feedback_your_own_edit_staled_the_citation` exactly.) It took `tree.get("icon")` and
`rune.get("icon")` straight from the payload and built BOTH halves from the
raw string:

    url    = f"{DDRAGON_CDN}/img/{icon}"
    target = out / Path(icon).name

`Path(icon).name` LOOKS like sanitisation and is not. Measured with the
project interpreter on this tree:

  * ``Path(".").name`` is ``''``, so ``target`` becomes the ``data/icons/rune``
    DIRECTORY itself. With ``force=True`` that reaches
    ``os.replace(tmp, <directory>)``, which raises an uncaught ``OSError`` out
    of `runes()` and out of `download_all()`.
  * ``Path("..").name`` is ``'..'``, so ``target`` resolves one level ABOVE the
    rune directory.
  * ``Path("../../etc/passwd").name`` is ``'passwd'`` - flattened, and so the
    filesystem half of a classic traversal is genuinely absorbed. The URL half
    is not, which is the part the filed row did not name.

WHY THE URL HALF MATTERS SEPARATELY. The three guarded siblings build their
URL from the VALIDATED basename (`:127`, `:144`, `:161`); `runes()` interpolated
the raw value, so a hostile ``icon`` escaped the ``/img/`` prefix of the
outbound request even in the cases where the on-disk path was flattened to
something harmless. Validating one half and not the other is why both are
pinned below.

THE FIX IS `_safe_relpath`, NOT `_safe_basename`, AND THAT IS DELIBERATE.
Real DDragon rune icons are multi-segment by design -
``perk-images/Styles/Domination/Electrocute/Electrocute.png`` - so applying
`_safe_basename` to the whole string would reject every legitimate rune and
turn the function into a no-op. The live twin already solved this exact
problem: `tools/ddragon_mirror_refresh.py:217` `_safe_relpath` splits on "/"
and requires every SEGMENT to pass `_safe_basename`. This ports that.

`test_a_legitimate_multi_segment_rune_icon_is_still_downloaded` exists
precisely so a later hardening pass cannot "simplify" this to `_safe_basename`
and silently disable rune icons. Deleting the guard and deleting the feature
must not look the same to the suite.

REACHABILITY, PROVEN NOT ASSUMED. `IconDownloader` and `download_all` appear
outside this module only in the `lib/icons/__init__.py:5` re-export; no
production code imports them (`ops/phase3_setup.py:43` names the string
``"lib/icons"`` as a directory to create, not an import). So this defect was
LATENT rather than live, and these are contract tests rather than caller
tests - inventing a call path would prove nothing. That is the same shape
RM-347 and RM-350 closed under, and it is recorded here so a later reader
cannot re-inherit an overstated severity.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lib.icons.downloader as dl  # noqa: E402
from lib.http.client import Response  # noqa: E402


LEGIT = "perk-images/Styles/Domination/Electrocute/Electrocute.png"


class _StubClient:
    """Answers every GET with one canned PNG body and records the URL."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str) -> Response:
        self.urls.append(url)
        return Response(200, {}, b"\x89PNG\r\n\x1a\n", url)


class _StubDDragon:
    """Replays one canned runesReforged payload; never touches the network."""

    def __init__(self, payload: list, version: str = "16.15.1") -> None:
        self._payload = payload
        self.version = version

    def runes(self) -> list:
        return self._payload


def _downloader(monkeypatch, tmp_path: Path, payload: list) -> tuple:
    """An `IconDownloader` wired to stubs, writing under `tmp_path`."""
    client = _StubClient()
    monkeypatch.setattr(dl, "get_client", lambda: client)
    monkeypatch.setattr(dl, "DDragon", lambda version=None: _StubDDragon(payload))
    monkeypatch.setattr(dl, "ICONS_ROOT", tmp_path / "icons")
    return dl.IconDownloader(), client


def _tree(icon):
    """A runesReforged tree whose own icon is `icon` and which has no slots."""
    return [{"icon": icon, "slots": []}]


def _nested(icon):
    """A runesReforged tree whose nested rune icon is `icon`."""
    return [{"icon": LEGIT, "slots": [{"runes": [{"icon": icon}]}]}]


HOSTILE = [
    ".",
    "..",
    "../../etc/passwd",
    "../../../../evil.png",
    "..\\..\\evil.png",
    "/etc/passwd",
    "perk-images/../../../evil.png",
    "perk-images/./evil.png",
]


@pytest.mark.parametrize("icon", HOSTILE)
def test_a_hostile_tree_icon_is_rejected(monkeypatch, tmp_path, icon):
    """The top-level tree icon is validated before it becomes a path or a URL."""
    d, client = _downloader(monkeypatch, tmp_path, _tree(icon))
    assert d.runes(force=True) == 0
    assert client.urls == []


@pytest.mark.parametrize("icon", HOSTILE)
def test_a_hostile_nested_rune_icon_is_rejected(monkeypatch, tmp_path, icon):
    """The inner per-slot rune icon gets the same treatment as the tree icon.

    Two separate call sites read `icon` in `runes()`, and a fix applied to only
    one of them leaves the other exploitable. Guarding both is why this test
    exists alongside the tree-icon one rather than being folded into it.
    """
    d, client = _downloader(monkeypatch, tmp_path, _nested(icon))
    # The legitimate tree icon still downloads; only the hostile nested one is dropped.
    assert d.runes(force=True) == 1
    assert client.urls == [f"{dl.DDRAGON_CDN}/img/{LEGIT}"]


def test_a_dot_icon_does_not_target_the_rune_directory_itself(monkeypatch, tmp_path):
    """`Path(".").name` is `''`, which made `target` the output DIRECTORY.

    Unguarded and with `force=True` this reached `os.replace(tmp, <directory>)`
    and raised an uncaught `OSError` out of `runes()` and `download_all()`, so
    a single poisoned entry aborted the whole icon refresh. The directory must
    survive as a directory and the call must return normally.
    """
    d, _ = _downloader(monkeypatch, tmp_path, _tree("."))
    assert d.runes(force=True) == 0
    out = tmp_path / "icons" / "rune"
    assert out.is_dir()


def test_nothing_is_written_outside_the_rune_directory(monkeypatch, tmp_path):
    """The filesystem half: no hostile icon may create a file above `out`."""
    for icon in HOSTILE:
        d, _ = _downloader(monkeypatch, tmp_path, _tree(icon))
        d.runes(force=True)
    out = tmp_path / "icons" / "rune"
    strays = [p for p in (tmp_path / "icons").rglob("*") if p.is_file() and p.parent != out]
    assert strays == []
    assert list(out.iterdir()) == []


def test_the_outbound_url_is_never_built_from_an_unvalidated_string(monkeypatch, tmp_path):
    """The URL half, which the filed row did not name.

    `../../etc/passwd` flattens to a harmless `passwd` on the filesystem, so a
    fix that only guarded `target` would leave this request escaping the
    `/img/` prefix while every path assertion above still passed.
    """
    d, client = _downloader(monkeypatch, tmp_path, _tree("../../../../evil.png"))
    d.runes(force=True)
    assert client.urls == []


def test_a_legitimate_multi_segment_rune_icon_is_still_downloaded(monkeypatch, tmp_path):
    """Real DDragon rune icons are multi-segment and MUST keep working.

    This is the anti-over-correction guard. `_safe_basename` applied to the
    whole string rejects every real rune icon, so a later pass that "unifies"
    the rune path onto the basename validator turns `runes()` into a permanent
    no-op. That failure is silent - a count of 0 looks like an empty payload -
    so it is pinned here rather than left to review.
    """
    d, client = _downloader(monkeypatch, tmp_path, _tree(LEGIT))
    assert d.runes(force=True) == 1
    assert client.urls == [f"{dl.DDRAGON_CDN}/img/{LEGIT}"]
    assert (tmp_path / "icons" / "rune" / "Electrocute.png").is_file()


def test_every_download_method_validates_its_wire_supplied_icon():
    """Parity guard: no future method may skip validation the way `runes()` did.

    The root cause was three-of-four adoption, which review missed precisely
    because the odd one out reads naturally. This asserts the property rather
    than the four instances, so a FIFTH download method inherits the check.
    """
    import inspect

    src = inspect.getsource(dl.IconDownloader)
    methods = [m for m in ("champions", "spells", "items", "runes")
               if f"def {m}(" in src]
    assert methods == ["champions", "spells", "items", "runes"]
    for name in methods:
        body = inspect.getsource(getattr(dl.IconDownloader, name))
        assert "_safe_basename(" in body or "_safe_relpath(" in body, (
            f"{name}() builds a path from a wire value without validating it"
        )


def test_safe_relpath_rejects_every_hostile_shape():
    """Unit-level contract for the ported validator itself.

    ``" "`` is deliberately NOT in this list. It is accepted, because
    `_safe_basename` accepts it and the live twin at
    `tools/ddragon_mirror_refresh.py:217` therefore accepts it too. A
    single-space segment is contained - it names a file inside the rune
    directory and escapes nothing - and rejecting it here would open a fresh
    divergence between the two validators, which is the exact defect class
    RM-359 is about. This first draft did assert it and went red against a
    correct fix; the test was wrong, not the port.
    """
    for icon in HOSTILE:
        assert dl._safe_relpath(icon) is None, icon
    for bad in (None, "", 123, [], "a//b", "\x00.png", "perk-images/"):
        assert dl._safe_relpath(bad) is None, bad


def test_safe_relpath_accepts_the_real_ddragon_shapes():
    """And the values it must let through, taken from live DDragon payloads."""
    for icon in (
        LEGIT,
        "perk-images/Styles/7200_Domination.png",
        "perk-images/Styles/Precision/PressTheAttack/PressTheAttack.png",
        "single.png",
    ):
        assert dl._safe_relpath(icon) == icon
