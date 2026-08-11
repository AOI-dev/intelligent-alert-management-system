"""Entrance rate limiting.

Rate limiting lives at the HTTP entrance, not between internal modules —
this is a monolith, so an "inter-service call" between e.g. filtering and
correlation is just a function call; there is nothing to protect it from.
The one place internal traffic looks like a network call is the outbound
HTTP this process makes to other systems (Zabbix API polling, TrueConf
OAuth); those get client-side timeouts/limiting at their own call sites,
not here.

The store is a Protocol so a single-replica deployment can use the in-memory
default while a future multi-replica one swaps in something shared (Redis)
without touching the middleware.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp


@dataclass
class TokenBucket:
    capacity: float
    refill_per_second: float
    tokens: float
    updated_at: float

    def take(self, now: float, cost: float = 1.0) -> tuple[bool, float]:
        """Attempt to spend `cost` tokens as of `now`. Returns (allowed, retry_after_seconds)."""
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.updated_at = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True, 0.0
        deficit = cost - self.tokens
        retry_after = deficit / self.refill_per_second if self.refill_per_second > 0 else float("inf")
        return False, retry_after


class BucketStore(Protocol):
    def get_or_create(self, key: str, capacity: float, refill_per_second: float, now: float) -> TokenBucket: ...


class InMemoryBucketStore:
    """Per-process bucket storage. Fine for a single replica; not shared state."""

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}

    def get_or_create(self, key: str, capacity: float, refill_per_second: float, now: float) -> TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = TokenBucket(capacity=capacity, refill_per_second=refill_per_second, tokens=capacity, updated_at=now)
            self._buckets[key] = bucket
        return bucket


@dataclass(frozen=True)
class RateLimitRule:
    """A limit applied to requests whose path starts with `prefix`.

    Rules are matched by longest prefix first, so a narrow rule (webhooks)
    can be stricter than a broad one (the rest of the API) covering it.
    """

    prefix: str
    capacity: float
    refill_per_second: float


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket limiter keyed by (matched rule, client).

    Paths matching no rule pass through unlimited — health checks and
    metrics scraping are meant to stay off this by simply not adding a rule
    for their prefix.
    """

    def __init__(
        self,
        app: ASGIApp,
        rules: list[RateLimitRule],
        store: BucketStore | None = None,
        clock=time.monotonic,
    ) -> None:
        super().__init__(app)
        self._rules = sorted(rules, key=lambda r: len(r.prefix), reverse=True)
        self._store = store or InMemoryBucketStore()
        self._clock = clock

    def _rule_for(self, path: str) -> RateLimitRule | None:
        for rule in self._rules:
            if path.startswith(rule.prefix):
                return rule
        return None

    async def dispatch(self, request: Request, call_next):
        rule = self._rule_for(request.url.path)
        if rule is None:
            return await call_next(request)

        key = f"{rule.prefix}:{client_key(request)}"
        now = self._clock()
        bucket = self._store.get_or_create(key, rule.capacity, rule.refill_per_second, now)
        allowed, retry_after = bucket.take(now)
        if not allowed:
            # A zero refill rate (a fully closed bucket) makes retry_after
            # infinite; cap the advertised wait instead of crashing on the
            # int() conversion.
            capped_retry_after = min(retry_after, 3600.0)
            return JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(max(1, int(capped_retry_after) + 1))},
            )
        return await call_next(request)
