"""The shared HTTP helper retries, backs off and refuses Wake's own server."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from parcelwatch.http import USER_AGENT, get_with_retry


class FakeSession:
    """Returns queued responses or raises queued exceptions, recording each call."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append({"url": url, **kwargs})
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        resp = requests.Response()
        resp.status_code = out
        resp.url = url
        return resp


def test_refuses_wake_server() -> None:
    with pytest.raises(ValueError, match="Wake"):
        get_with_retry("https://maps.wake.gov/arcgis/rest/x")


def test_retries_then_succeeds() -> None:
    s = FakeSession([requests.ConnectionError("boom"), 503, 200])
    waits: list[float] = []
    resp = get_with_retry("https://example.org/f", session=s, sleep=waits.append)  # type: ignore[arg-type]
    assert resp.status_code == 200
    assert waits == [2, 4]
    assert s.calls[0]["headers"]["User-Agent"] == USER_AGENT
    assert s.calls[0]["timeout"] == 120


def test_gives_up_after_three_retries() -> None:
    s = FakeSession([500, 500, 500, 500])
    waits: list[float] = []
    with pytest.raises(requests.HTTPError):
        get_with_retry("https://example.org/f", session=s, sleep=waits.append)  # type: ignore[arg-type]
    assert waits == [2, 4, 8]


def test_no_retry_on_404() -> None:
    s = FakeSession([404])
    waits: list[float] = []
    with pytest.raises(requests.HTTPError):
        get_with_retry("https://example.org/f", session=s, sleep=waits.append)  # type: ignore[arg-type]
    assert waits == []
