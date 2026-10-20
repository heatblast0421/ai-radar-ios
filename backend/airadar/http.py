"""HTTP client with polite defaults: retries with backoff, rate-limit awareness, per-host spacing."""
from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("airadar.http")

USER_AGENT = "AIRadar/1.0 (personal AI news reader; +https://github.com/heatblast0421/ai-radar-ios)"


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Http:
    def __init__(self, timeout: float = 25.0, retries: int = 3, min_interval: dict[str, float] | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
            transport=transport,
        )
        self.retries = retries
        # Minimum seconds between requests to one host (arXiv asks for 3s).
        self.min_interval = {"export.arxiv.org": 3.1, **(min_interval or {})}
        self._last: dict[str, float] = {}
        self.sleep = time.sleep

    def _space(self, url: str) -> None:
        host = urlsplit(url).netloc
        gap = self.min_interval.get(host)
        if gap:
            wait = self._last.get(host, 0) + gap - time.monotonic()
            if wait > 0:
                self.sleep(wait)
        self._last[host] = time.monotonic()

    def request(self, method: str, url: str, *, headers: dict | None = None, params=None, json=None,
                ok_statuses=(200,), max_wait: float = 60.0) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._space(url)
            try:
                resp = self.client.request(method, url, headers=headers, params=params, json=json)
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("network error %s %s (attempt %d): %s", method, url, attempt + 1, exc)
                self.sleep(min(2 ** attempt, 10))
                continue
            if resp.status_code in ok_statuses or resp.status_code == 304:
                return resp
            if resp.status_code in (429, 500, 502, 503, 504) or (
                resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0"
            ):
                wait = _retry_after(resp)
                if wait is None:
                    wait = min(2 ** (attempt + 1), 20)
                if wait > max_wait or attempt == self.retries:
                    raise FetchError(f"HTTP {resp.status_code} (rate limited / unavailable) for {url}", resp.status_code)
                log.warning("HTTP %s from %s, retrying in %.0fs", resp.status_code, url, wait)
                self.sleep(wait)
                continue
            raise FetchError(f"HTTP {resp.status_code} for {url}: {resp.text[:200]}", resp.status_code)
        raise FetchError(f"network failure for {url}: {last_exc}")

    def get(self, url: str, **kw) -> httpx.Response:
        return self.request("GET", url, **kw)

    def get_json(self, url: str, **kw):
        return self.get(url, **kw).json()

    def close(self):
        self.client.close()


def _retry_after(resp: httpx.Response) -> float | None:
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            return float(ra)
        except ValueError:
            return None
    reset = resp.headers.get("x-ratelimit-reset")
    if reset and resp.headers.get("x-ratelimit-remaining") == "0":
        try:
            return max(0.0, float(reset) - time.time()) + 1
        except ValueError:
            return None
    return None
