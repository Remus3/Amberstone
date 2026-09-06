"""RM-352: latest_version must check the HTTP status before parsing the body.

`HttpClient.request` RETURNS a `Response` for 4xx/5xx rather than raising
(`lib/http/client.py:586` builds `Response(e.code, hdrs, body, url)`), so a
DDragon 503 maintenance page or a Cloudflare interstitial flowed straight into
`resp.json()` and surfaced as `json.JSONDecodeError`. Every caller in the tree
degrades on `RuntimeError` - the sibling method in the same class already
raises one (`lib/ddragon/fetch.py` `_pull`), which is what made the omission a
bug rather than a design choice.

The status guard is asserted here on `latest_version` only. The version STRING
itself is still unvalidated (a non-list body, a path-traversal element); that
is RM-353 and is deliberately out of scope for these tests.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lib.ddragon.fetch as fetch_mod  # noqa: E402
from lib.http.client import Response  # noqa: E402


class _StubClient:
    """Records the URLs asked for and replays one canned Response."""

    def __init__(self, response: Response) -> None:
        self._response = response
        self.urls: list[str] = []

    def get(self, url: str, **kwargs):
        self.urls.append(url)
        return self._response


def _resp(status: int, body: bytes) -> Response:
    return Response(status, {}, body, f"{fetch_mod.DDRAGON_BASE}/api/versions.json")


def test_latest_version_raises_runtime_error_on_503_maintenance_page():
    """The acceptance case: a 503 HTML body must be a RuntimeError naming 503."""
    stub = _StubClient(_resp(503, b"<html><body>maintenance</body></html>"))

    with pytest.raises(RuntimeError) as exc:
        fetch_mod.latest_version(client=stub)

    assert "503" in str(exc.value)
    # Not the incidental parse failure a caller cannot classify.
    assert not isinstance(exc.value, json.JSONDecodeError)


def test_latest_version_raises_runtime_error_on_403_interstitial():
    """4xx is the same class: a bot wall is not a versions list."""
    stub = _StubClient(_resp(403, b"<html>Attention Required! | Cloudflare</html>"))

    with pytest.raises(RuntimeError) as exc:
        fetch_mod.latest_version(client=stub)

    assert "403" in str(exc.value)


def test_latest_version_rejects_non_200_even_when_the_body_parses():
    """A 500 carrying valid JSON is still an error, not a version.

    Without this the guard could be written as a try/except around the parse
    and still pass the two cases above while trusting an error body.
    """
    stub = _StubClient(_resp(500, b'["99.99.1"]'))

    with pytest.raises(RuntimeError) as exc:
        fetch_mod.latest_version(client=stub)

    assert "500" in str(exc.value)


def test_latest_version_returns_first_entry_on_200():
    """The happy path is unchanged - the guard must not be over-broad."""
    stub = _StubClient(_resp(200, b'["16.15.1","16.14.1","16.13.1"]'))

    assert fetch_mod.latest_version(client=stub) == "16.15.1"
    assert stub.urls == [f"{fetch_mod.DDRAGON_BASE}/api/versions.json"]


def test_latest_version_still_raises_on_an_empty_200_list():
    """The pre-existing empty-list contract survives the new guard."""
    stub = _StubClient(_resp(200, b"[]"))

    with pytest.raises(RuntimeError, match="empty versions list"):
        fetch_mod.latest_version(client=stub)
