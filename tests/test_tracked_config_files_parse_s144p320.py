"""S144-P-320 - every tracked ``.json`` / ``.yml`` / ``.yaml`` / ``.toml`` file parses strictly, held at zero.

A config file that no longer parses is the quietest way to break a consumer: most readers in this repo catch the
decode error and fall back to defaults (``core/polled_json`` returns its default, the coaches skip a bad data file),
so the file rots while every test that does not open it stays green. Four failure shapes are checked over every
tracked file, measured 2026-11-07 at zero over 1084 ``.json``, 8 ``.yml`` and 2 ``.toml``:

- the file does not parse;
- a ``.json`` file starts with a UTF-8 BOM (``json.loads`` on the decoded text raises, ``JSON.parse`` in the dashboard
  rejects it, and an editor adds it without a trace);
- an object repeats a key (``json.loads`` and ``yaml.safe_load`` keep the LAST value and drop the first with no
  error, so a merge that pastes a second block silently overrides the first);
- a ``.json`` file carries ``NaN`` / ``Infinity`` / ``-Infinity``, which Python writes by default (``allow_nan``) but
  ``JSON.parse`` and every strict parser refuse.

Each shape has a positive control below, so a rule that stopped detecting fails loudly instead of passing for nothing.
Nothing is grandfathered: fix the file, never widen this test.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_BOM = b"\xef\xbb\xbf"


class _DuplicateKey(ValueError):
    pass


def _reject_duplicate_keys(pairs):
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise _DuplicateKey(f"duplicate key {key!r}")
        seen.add(key)
    return dict(pairs)


def _reject_constant(name):
    raise ValueError(f"non-standard JSON constant {name}")


def _json_problem(raw: bytes) -> str:
    """The first strict-JSON problem in ``raw``, or an empty string when it is clean."""
    if raw.startswith(_BOM):
        return "starts with a UTF-8 BOM"
    try:
        json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (ValueError, UnicodeDecodeError) as exc:
        return f"{type(exc).__name__}: {str(exc)[:120]}"
    return ""


def _yaml_loader():
    yaml = pytest.importorskip("yaml")

    class _Strict(yaml.SafeLoader):
        pass

    def _mapping(loader, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=True)
            if key in seen:
                raise _DuplicateKey(
                    f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
            seen.add(key)
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    _Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
    return yaml, _Strict


def _yaml_problem(raw: bytes) -> str:
    yaml, loader = _yaml_loader()
    try:
        list(yaml.load_all(raw.decode("utf-8"), Loader=loader))
    except (yaml.YAMLError, ValueError, UnicodeDecodeError) as exc:
        return f"{type(exc).__name__}: {str(exc)[:120]}"
    return ""


def _toml_problem(raw: bytes) -> str:
    try:
        tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return f"{type(exc).__name__}: {str(exc)[:120]}"
    return ""


def _problems(patterns, check) -> list[str]:
    out = []
    for path in repo_files(REPO_ROOT, patterns):
        problem = check(Path(path).read_bytes())
        if problem:
            out.append(f"{relative_posix(path)}: {problem}")
    return out


def test_enumeration_is_not_vacuous():
    assert len(repo_files(REPO_ROOT, ("*.json",))) > 500
    assert len(repo_files(REPO_ROOT, ("*.yml", "*.yaml"))) >= 5
    assert len(repo_files(REPO_ROOT, ("*.toml",))) >= 1


def test_every_tracked_json_file_is_strict():
    assert _problems(("*.json",), _json_problem) == []


def test_every_tracked_yaml_file_parses_without_a_repeated_key():
    pytest.importorskip("yaml")
    assert _problems(("*.yml", "*.yaml"), _yaml_problem) == []


def test_every_tracked_toml_file_parses():
    assert _problems(("*.toml",), _toml_problem) == []


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a": 1',
        _BOM + b'{"a": 1}',
        b'{"a": 1, "a": 2}',
        b'{"o": {"k": 1, "k": 1}}',
        b'[{"x": NaN}]',
        b'{"x": Infinity}',
        b'{"x": -Infinity}',
        b'{"x": "\xff"}',
    ],
)
def test_json_checker_flags_each_failure_shape(raw):
    assert _json_problem(raw) != ""


def test_json_checker_passes_a_clean_document():
    assert _json_problem(b'{"a": [1, 2.5, null, {"b": "c"}], "d": {"a": 1}}') == ""
    assert _json_problem(b"[]") == ""


def test_yaml_checker_flags_a_repeated_key_and_a_parse_error():
    pytest.importorskip("yaml")
    assert "duplicate key" in _yaml_problem(b"a: 1\nb: 2\na: 3\n")
    assert "duplicate key" in _yaml_problem(b"o:\n  k: 1\n  k: 1\n")
    assert _yaml_problem(b"a: [1, 2\n") != ""
    assert _yaml_problem(b"a: 1\nb:\n  a: 2\n") == ""


def test_toml_checker_flags_a_repeated_key_and_a_parse_error():
    assert _toml_problem(b"a = 1\na = 2\n") != ""
    assert _toml_problem(b"a = \n") != ""
    assert _toml_problem(b"a = 1\n[t]\na = 2\n") == ""
