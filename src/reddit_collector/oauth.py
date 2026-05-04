from __future__ import annotations
import asyncio
import time
import httpx
import structlog

log = structlog.get_logger(__name__)

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
# Refresh slightly before expiry; Reddit tokens last ~3600s.
REFRESH_LEAD_SEC = 600


class RedditAuth:
    """Manages an OAuth access token for the Reddit API.

    Uses `client_credentials` for script apps without a bot identity, or
    `password` grant when REDDIT_USERNAME/PASSWORD are set (acts as bot user).
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        username: str | None = None,
        password: str | None = None,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._username = username
        self._password = password
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def token(self, http: httpx.AsyncClient) -> str:
        async with self._lock:
            if self._token and time.time() < self._expires_at - REFRESH_LEAD_SEC:
                return self._token
            await self._refresh(http)
            return self._token  # type: ignore[return-value]

    async def _refresh(self, http: httpx.AsyncClient) -> None:
        if self._username and self._password:
            data = {
                "grant_type": "password",
                "username": self._username,
                "password": self._password,
            }
        else:
            data = {"grant_type": "client_credentials"}
        auth = httpx.BasicAuth(self._client_id, self._client_secret)
        headers = {"User-Agent": self._user_agent}
        resp = await http.post(TOKEN_URL, data=data, auth=auth, headers=headers, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = time.time() + int(body.get("expires_in", 3600))
        log.info("reddit.oauth.refreshed", expires_in=body.get("expires_in"))
