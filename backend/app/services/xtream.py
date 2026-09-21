import asyncio
import email.utils
import logging
import random
import threading
import time
from typing import List, Dict, Optional, Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Statuses that mean "try again later" rather than "this request is wrong".
# Xtream panels sitting behind nginx answer 503 (and sometimes 500) as soon as
# their per-IP connection or request limit is reached.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _parse_retry_after(response: Optional[httpx.Response]) -> Optional[float]:
    """Return the Retry-After delay in seconds, if the server sent a usable one."""
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    parsed = email.utils.parsedate_to_datetime(raw)
    if parsed is None:
        return None
    return max(0.0, parsed.timestamp() - time.time())


class AdaptiveRateLimiter:
    """Token bucket that slows down when the panel pushes back.

    The semaphores in the sync tasks cap concurrency, not throughput: when the
    panel answers in 50ms, ten coroutines happily issue 200 requests/second.
    This caps the actual rate, halves it whenever the panel answers 429/5xx, and
    recovers gradually afterwards (AIMD), so the panel dictates the pace instead
    of us having to guess the right value.

    An instance is meant to be used from either the async or the sync path, not
    both at once: each path has its own lock around the shared counters.
    """

    MIN_RATE = 0.5              # requests/second floor, never throttle below this
    PENALTY_FACTOR = 0.5        # multiplicative decrease on pushback
    RECOVERY_FRACTION = 0.05    # additive increase per success, as a share of max_rate

    def __init__(self, rate: float, burst: Optional[float] = None):
        self.max_rate = max(float(rate), self.MIN_RATE)
        self.rate = self.max_rate
        self.capacity = float(burst) if burst is not None else max(1.0, self.max_rate)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.blocked_until = 0.0
        self._async_lock: Optional[asyncio.Lock] = None
        self._sync_lock = threading.Lock()

    def _reserve(self) -> float:
        """Consume a token and return how long the caller must wait before using it."""
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

        wait = max(0.0, self.blocked_until - now)
        if self.tokens < 1.0:
            wait = max(wait, (1.0 - self.tokens) / self.rate)
        # Tokens go negative on purpose: concurrent callers then queue up behind
        # each other instead of all waking at the same instant.
        self.tokens -= 1.0
        return wait

    async def acquire(self) -> None:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        async with self._async_lock:
            wait = self._reserve()
        if wait > 0:
            await asyncio.sleep(wait)

    def acquire_sync(self) -> None:
        with self._sync_lock:
            wait = self._reserve()
        if wait > 0:
            time.sleep(wait)

    def penalize(self, retry_after: Optional[float] = None) -> None:
        """Halve the rate and hold every caller back for a cooldown.

        At most one halving per cooldown window: with ten requests in flight a
        single overload would otherwise divide the rate by 1024 and pin it to
        the floor for the rest of the sync.
        """
        now = time.monotonic()
        already_backing_off = now < self.blocked_until
        if not already_backing_off:
            self.rate = max(self.MIN_RATE, self.rate * self.PENALTY_FACTOR)

        cooldown = retry_after if retry_after is not None else 1.0 / self.rate
        self.blocked_until = max(self.blocked_until, now + cooldown)
        self.tokens = min(self.tokens, 0.0)

    def reward(self) -> None:
        if self.rate < self.max_rate:
            self.rate = min(self.max_rate, self.rate + self.max_rate * self.RECOVERY_FRACTION)


class XtreamClient:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        rate_limit: Optional[float] = None,
        max_connections: Optional[int] = None,
        timeout: float = 60.0,
    ):
        self.base_url = url.rstrip("/")
        self.username = username
        self.password = password
        self.api_url = f"{self.base_url}/player_api.php"
        self.timeout = timeout
        self.max_connections = int(
            max_connections if max_connections is not None else settings.XTREAM_MAX_CONNECTIONS
        )
        self.max_retries = settings.XTREAM_MAX_RETRIES
        self._limiter = AdaptiveRateLimiter(
            rate_limit if rate_limit is not None else settings.XTREAM_RATE_LIMIT_RPS
        )
        self._async_client: Optional[httpx.AsyncClient] = None
        self._sync_client: Optional[httpx.Client] = None

    # --- Connection pooling -------------------------------------------------
    # One pooled client per instance, so requests reuse keep-alive connections
    # instead of opening a fresh TCP connection each time (which is what makes
    # panels behind nginx answer 503).

    def _limits(self) -> httpx.Limits:
        return httpx.Limits(
            max_connections=self.max_connections,
            max_keepalive_connections=self.max_connections,
            keepalive_expiry=30.0,
        )

    def _async_http(self) -> httpx.AsyncClient:
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True, limits=self._limits()
            )
        return self._async_client

    def _sync_http(self) -> httpx.Client:
        if self._sync_client is None or self._sync_client.is_closed:
            self._sync_client = httpx.Client(
                timeout=self.timeout, follow_redirects=True, limits=self._limits()
            )
        return self._sync_client

    async def aclose(self) -> None:
        if self._async_client is not None and not self._async_client.is_closed:
            await self._async_client.aclose()
        self._async_client = None

    def close(self) -> None:
        if self._sync_client is not None and not self._sync_client.is_closed:
            self._sync_client.close()
        self._sync_client = None

    async def __aenter__(self) -> "XtreamClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    def __enter__(self) -> "XtreamClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # --- Requests -----------------------------------------------------------

    def _get_params(self, action: str, **kwargs) -> Dict[str, str]:
        params = {
            "username": self.username,
            "password": self.password,
            "action": action
        }
        params.update(kwargs)
        return params

    def _backoff(self, action: str, attempt: int, reason: str, response: Optional[httpx.Response]) -> float:
        """Slow the limiter down and return how long to wait before retrying."""
        retry_after = _parse_retry_after(response)
        self._limiter.penalize(retry_after)

        if retry_after is not None:
            delay = retry_after
        else:
            capped = min(settings.XTREAM_BACKOFF_MAX, settings.XTREAM_BACKOFF_BASE * (2 ** attempt))
            # Full jitter: without it every worker throttled at the same moment
            # retries at the same moment too, and the panel chokes again.
            delay = capped / 2 + random.uniform(0, capped / 2)

        logger.warning(
            f"{action}: {reason}, throttling to {self._limiter.rate:.2f} req/s, "
            f"retry in {delay:.1f}s (attempt {attempt + 1}/{self.max_retries + 1})"
        )
        return delay

    async def _request(self, action: str, **kwargs) -> Any:
        params = self._get_params(action, **kwargs)
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            await self._limiter.acquire()
            try:
                response = await self._async_http().get(self.api_url, params=params)
                response.raise_for_status()
                payload = response.json()
                self._limiter.reward()
                return payload
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in RETRYABLE_STATUS:
                    logger.error(f"HTTP error for {action}: {e}")
                    raise
                last_error = e
                delay = self._backoff(action, attempt, f"HTTP {e.response.status_code}", e.response)
            except httpx.TransportError as e:
                last_error = e
                delay = self._backoff(action, attempt, f"transport error ({e.__class__.__name__})", None)
            except ValueError as e:
                # Panels under load answer 200 with an HTML error page
                last_error = e
                delay = self._backoff(action, attempt, "invalid JSON response", None)
            except Exception as e:
                logger.error(f"Error fetching {action}: {e}")
                raise

            if attempt < self.max_retries:
                await asyncio.sleep(delay)

        logger.error(f"Giving up on {action} after {self.max_retries + 1} attempts: {last_error}")
        raise last_error

    def _request_sync(self, action: str, **kwargs) -> Any:
        params = self._get_params(action, **kwargs)
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            self._limiter.acquire_sync()
            try:
                response = self._sync_http().get(self.api_url, params=params)
                response.raise_for_status()
                payload = response.json()
                self._limiter.reward()
                return payload
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in RETRYABLE_STATUS:
                    logger.error(f"HTTP error for {action}: {e}")
                    raise
                last_error = e
                delay = self._backoff(action, attempt, f"HTTP {e.response.status_code}", e.response)
            except httpx.TransportError as e:
                last_error = e
                delay = self._backoff(action, attempt, f"transport error ({e.__class__.__name__})", None)
            except ValueError as e:
                last_error = e
                delay = self._backoff(action, attempt, "invalid JSON response", None)
            except Exception as e:
                logger.error(f"Error fetching {action}: {e}")
                raise

            if attempt < self.max_retries:
                time.sleep(delay)

        logger.error(f"Giving up on {action} after {self.max_retries + 1} attempts: {last_error}")
        raise last_error

    async def get_vod_categories(self) -> List[Dict]:
        return await self._request("get_vod_categories")

    def get_vod_categories_sync(self) -> List[Dict]:
        return self._request_sync("get_vod_categories")

    async def get_vod_streams(self, category_id: Optional[str] = None) -> List[Dict]:
        kwargs = {}
        if category_id:
            kwargs["category_id"] = category_id
        return await self._request("get_vod_streams", **kwargs)

    def get_vod_streams_sync(self, category_id: Optional[str] = None) -> List[Dict]:
        kwargs = {}
        if category_id:
            kwargs["category_id"] = category_id
        return self._request_sync("get_vod_streams", **kwargs)

    async def get_series_categories(self) -> List[Dict]:
        return await self._request("get_series_categories")

    def get_series_categories_sync(self) -> List[Dict]:
        return self._request_sync("get_series_categories")

    async def get_series(self, category_id: Optional[str] = None) -> List[Dict]:
        kwargs = {}
        if category_id:
            kwargs["category_id"] = category_id
        return await self._request("get_series", **kwargs)

    def get_series_sync(self, category_id: Optional[str] = None) -> List[Dict]:
        kwargs = {}
        if category_id:
            kwargs["category_id"] = category_id
        return self._request_sync("get_series", **kwargs)

    async def get_series_info(self, series_id: str) -> Dict:
        return await self._request("get_series_info", series_id=series_id)

    def get_series_info_sync(self, series_id: str) -> Dict:
        return self._request_sync("get_series_info", series_id=series_id)

    async def get_vod_info(self, vod_id: str) -> Dict:
        return await self._request("get_vod_info", vod_id=vod_id)

    def get_vod_info_sync(self, vod_id: str) -> Dict:
        return self._request_sync("get_vod_info", vod_id=vod_id)

    async def get_live_categories(self) -> List[Dict]:
        return await self._request("get_live_categories")

    def get_live_categories_sync(self) -> List[Dict]:
        return self._request_sync("get_live_categories")

    async def get_live_streams(self, category_id: Optional[str] = None) -> List[Dict]:
        kwargs = {}
        if category_id:
            kwargs["category_id"] = category_id
        return await self._request("get_live_streams", **kwargs)

    def get_live_streams_sync(self, category_id: Optional[str] = None) -> List[Dict]:
        kwargs = {}
        if category_id:
            kwargs["category_id"] = category_id
        return self._request_sync("get_live_streams", **kwargs)

    def get_stream_url(self, stream_type: str, stream_id: str, extension: str) -> str:
        # stream_type: "movie" or "series"
        return f"{self.base_url}/{stream_type}/{self.username}/{self.password}/{stream_id}.{extension}"
