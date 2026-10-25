"""The one network helper every download goes through (TRD section 5)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import requests

log = logging.getLogger(__name__)

USER_AGENT = "ParcelWatch/0.1 (portfolio research)"
TIMEOUT_S = 120
BACKOFF_S = (2, 4, 8)
BLOCKED_HOSTS = ("maps.wake.gov", "maps.wakegov.com")


def _check_host(url: str) -> None:
    """Refuse Wake County's own GIS server, which blocks the owner's network."""
    if any(h in url for h in BLOCKED_HOSTS):
        raise ValueError(f"refusing to call Wake's own server, use ArcGIS Hub: {url}")


def get_with_retry(
    url: str,
    *,
    stream: bool = False,
    params: dict[str, str] | None = None,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> requests.Response:
    """GET a URL with a 120 s timeout, a descriptive User-Agent and 3 retries.

    Retries on connection errors, timeouts and HTTP 429/5xx, waiting 2, 4 then 8 s.

    Args:
        url: Absolute URL. Wake County's own server is always refused.
        stream: Pass through to ``requests`` for large downloads.
        params: Optional query parameters.
        session: Optional ``requests.Session`` to reuse connections.
        sleep: Injected sleep function, so tests don't wait.

    Returns:
        A successful ``requests.Response`` (status < 400).

    Raises:
        ValueError: If ``url`` points at a blocked host.
        requests.HTTPError: On a non-retryable status or after the last retry.
    """
    _check_host(url)
    getter = session.get if session is not None else requests.get
    headers = {"User-Agent": USER_AGENT}
    attempts = len(BACKOFF_S) + 1
    for attempt in range(attempts):
        try:
            resp = getter(url, headers=headers, timeout=TIMEOUT_S, stream=stream, params=params)
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = status is None or status == 429 or status >= 500
            if not retryable or attempt == attempts - 1:
                raise
            wait = BACKOFF_S[attempt]
            log.warning("GET %s failed (%s), retry %d in %ds", url, exc, attempt + 1, wait)
            sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover
