from __future__ import annotations
import asyncio
import time
from typing import Any
import httpx
import structlog

log = structlog.get_logger(__name__)

FIREBASE_BASE = "https://hacker-news.firebaseio.com/v0"
ALGOLIA_BASE = "https://hn.algolia.com/api/v1"


class HNClient:
    """Polite client for Hacker News public APIs.

    No auth; we self-throttle to keep traffic considerate. Both APIs are stable
    and free, but treat them as a courtesy resource — never hammer.
    """

    def __init__(self, user_agent: str, rps: float = 2.0):
        self._http = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )
        self._min_interval = 1.0 / max(rps, 0.5)
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "HNClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _throttle(self) -> None:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def _get(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            await self._throttle()
            try:
                r = await self._http.get(url, params=params)
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                wait = min(60, 2 ** attempt)
                log.warning("hn.net.retry", url=url, error=str(exc), attempt=attempt, wait=wait)
                await asyncio.sleep(wait)
                continue
            if r.status_code in (429, 502, 503, 504):
                wait = min(60, 2 ** attempt)
                log.warning("hn.api.retry", url=url, status=r.status_code, wait=wait)
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"hn GET {url} failed after {max_attempts} attempts")

    async def item(self, item_id: int) -> dict[str, Any] | None:
        return await self._get(f"{FIREBASE_BASE}/item/{item_id}.json")

    async def latest_max_id(self) -> int:
        return int(await self._get(f"{FIREBASE_BASE}/maxitem.json"))

    async def search(self, query: str, *, tags: str = "story", numeric_filters: str | None = None,
                     hits_per_page: int = 50, page: int = 0) -> dict[str, Any]:
        """Algolia search. tags='story', 'comment', 'show_hn', 'launch_hn'."""
        params: dict[str, Any] = {
            "query": query,
            "tags": tags,
            "hitsPerPage": hits_per_page,
            "page": page,
        }
        if numeric_filters:
            params["numericFilters"] = numeric_filters
        return await self._get(f"{ALGOLIA_BASE}/search_by_date", params=params)
