"""Usage tests for the entrance rate limiter.

The TokenBucket tests exercise the algorithm directly with a fake clock
(no real sleeping). The middleware tests wire it into a throwaway FastAPI
app to demonstrate the actual request-level behavior: which paths get
limited, that clients are tracked independently, and what a client sees
when it's throttled.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.rate_limit import RateLimitMiddleware, RateLimitRule, TokenBucket


def test_token_bucket_allows_burst_up_to_capacity_then_blocks():
    bucket = TokenBucket(capacity=3, refill_per_second=1, tokens=3, updated_at=0.0)

    allowed = [bucket.take(now=0.0)[0] for _ in range(3)]
    blocked, retry_after = bucket.take(now=0.0)

    assert allowed == [True, True, True]
    assert blocked is False
    assert abs(retry_after - 1.0) < 1e-9


def test_token_bucket_refills_over_time():
    bucket = TokenBucket(capacity=2, refill_per_second=1, tokens=0, updated_at=0.0)

    still_empty, _ = bucket.take(now=0.5)
    replenished, _ = bucket.take(now=1.5)

    assert still_empty is False
    assert replenished is True


def _rate_limited_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        rules=[
            RateLimitRule(prefix="/v1/integrations", capacity=2, refill_per_second=0),
            RateLimitRule(prefix="/v1", capacity=100, refill_per_second=100),
        ],
        clock=lambda: 0.0,
    )

    @app.post("/v1/integrations/example/webhook")
    async def webhook() -> dict:
        return {"ok": True}

    @app.get("/v1/other")
    async def other() -> dict:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    return app


def test_middleware_blocks_after_capacity_and_reports_retry_after():
    client = TestClient(_rate_limited_app())

    first = client.post("/v1/integrations/example/webhook")
    second = client.post("/v1/integrations/example/webhook")
    third = client.post("/v1/integrations/example/webhook")

    assert first.status_code == 202 or first.status_code == 200
    assert second.status_code in (200, 202)
    assert third.status_code == 429
    assert "Retry-After" in third.headers


def test_middleware_tracks_clients_independently():
    client = TestClient(_rate_limited_app())

    for _ in range(2):
        assert client.post(
            "/v1/integrations/example/webhook", headers={"X-Forwarded-For": "10.0.0.1"}
        ).status_code in (200, 202)
    exhausted = client.post("/v1/integrations/example/webhook", headers={"X-Forwarded-For": "10.0.0.1"})
    other_client_still_allowed = client.post(
        "/v1/integrations/example/webhook", headers={"X-Forwarded-For": "10.0.0.2"}
    )

    assert exhausted.status_code == 429
    assert other_client_still_allowed.status_code in (200, 202)


def test_middleware_leaves_unmatched_prefixes_unlimited():
    client = TestClient(_rate_limited_app())

    responses = [client.get("/health") for _ in range(50)]

    assert all(response.status_code == 200 for response in responses)


def test_narrower_rule_applies_over_broader_one():
    """/v1/integrations/... matches both rules; the narrower (stricter) one wins."""
    client = TestClient(_rate_limited_app())

    for _ in range(2):
        assert client.post("/v1/integrations/example/webhook").status_code in (200, 202)
    webhook_blocked = client.post("/v1/integrations/example/webhook")
    other_v1_still_allowed = client.get("/v1/other")

    assert webhook_blocked.status_code == 429
    assert other_v1_still_allowed.status_code == 200
