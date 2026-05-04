from __future__ import annotations
import asyncio
import random
import time
from typing import Any
import httpx
import structlog

from .oauth import RedditAuth

log = structlog.get_logger(__name__)

API_BASE = "https://oauth.reddit.com"


class RateLimiter:
    """Tracks Reddit's `X-Ratelimit-*` headers and gates outbound calls.

    Reddit returns the *authoritative* state of your bucket on every response;
    we mirror it locally so callers (and concurrent workers in the same process)
    can sleep proactively when remaining gets near zero.
    """

    def __init__(self) -> None:
        self.remaining: float = 100.0
        self.reset: float = 60.0           # seconds until reset
        self.reset_at: float = time.time() + 60
        self._lock = asyncio.Lock()

    def update_from_headers(self, headers: httpx.Headers) -> None:
        try:
            self.remaining = float(headers.get("x-ratelimit-remaining", self.remaining))
            self.reset = float(headers.get("x-ratelimit-reset", self.reset))
            self.reset_at = time.time() + self.reset
        except ValueError:
            pass

    async def acquire(self) -> None:
        async with self._lock:
            if self.remaining < 2:
                wait = max(0.0, self.reset_at - time.time()) + random.uniform(0.1, 0.5)
                log.warning("reddit.ratelimit.sleep", seconds=round(wait, 2))
                await asyncio.sleep(wait)


class RedditClient:
    """Thin async wrapper around oauth.reddit.com with retries + rate-limit awareness."""

    def __init__(self, auth: RedditAuth, user_agent: str):
        self._auth = auth
        self._ua = user_agent
        self._http = httpx.AsyncClient(
            base_url=API_BASE,
            timeout=30.0,
            headers={"User-Agent": user_agent},
        )
        self.limiter = RateLimiter()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "RedditClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {**(params or {}), "raw_json": 1}
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            await self.limiter.acquire()
            token = await self._auth.token(self._http)
            headers = {"Authorization": f"bearer {token}"}
            t0 = time.monotonic()
            try:
                resp = await self._http.get(path, params=params, headers=headers)
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                wait = min(60.0, 2 ** attempt) + random.uniform(0, 1)
                log.warning("reddit.net.retry", path=path, error=str(exc), attempt=attempt, wait=wait)
                await asyncio.sleep(wait)
                continue

            self.limiter.update_from_headers(resp.headers)
            log.info(
                "reddit.api",
                path=path,
                status=resp.status_code,
                latency_ms=round((time.monotonic() - t0) * 1000),
                rl_remaining=self.limiter.remaining,
                rl_reset=self.limiter.reset,
                attempt=attempt,
            )

            if resp.status_code == 429:
                wait = max(1.0, self.limiter.reset) + random.uniform(0, 1)
                log.warning("reddit.api.429", path=path, wait=wait)
                await asyncio.sleep(wait)
                continue
            if resp.status_code == 401 and attempt == 1:
                # Force refresh on next iteration.
                self._auth._token = None  # type: ignore[attr-defined]
                continue
            if 500 <= resp.status_code < 600:
                wait = min(60.0, 2 ** attempt) + random.uniform(0, 1)
                log.warning("reddit.api.5xx", status=resp.status_code, wait=wait)
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError(f"reddit GET {path} failed after {max_attempts} attempts")
