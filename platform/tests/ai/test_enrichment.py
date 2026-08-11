"""AI enrichment contour tests, in two layers.

Unit layer (always runs): EnrichmentService's parsing, vocabulary, and
never-raise guarantees, with the HTTP client replaced by an in-process
stub. This is the layer that protects the deterministic alert path: the
model may say anything, and the contract must still hold.

Live layer (-m live, requires VLLM_TEST=1): runs the real app/ai/ code —
prompt builder, vLLM client, parser — against the deployed model and
asserts the *contract* the rest of the platform relies on (valid
vocabulary, bounded confidence, non-empty explanation). It deliberately
does NOT pin one exact answer: a 4B model's specific classification is not
a stable assertion target, and a test that fails whenever the model is
merely mediocre teaches everyone to ignore it. Judging whether the answers
are actually *good* is what `pytest -m eval` is for (separate, opt-in).
"""
import os

import pytest

from app.ai.client import AIClientError
from app.ai.service import CLASSIFICATIONS, PRIORITIES, EnrichmentService
from tests.ai.fixtures import enrichment_request

LIVE_ENABLED = os.environ.get("VLLM_TEST") == "1"
live = pytest.mark.skipif(not LIVE_ENABLED, reason="live vLLM tests disabled (set VLLM_TEST=1)")


class StubClient:
    """In-process stand-in for app.ai.client.LLMClient."""

    def __init__(self, reply: dict | None = None, error: Exception | None = None):
        self._reply = reply
        self._error = error

    async def chat_json(self, messages, max_tokens=512):
        if self._error:
            raise self._error
        return self._reply, "stub-model"


@pytest.mark.asyncio
async def test_model_failure_falls_back_without_raising():
    service = EnrichmentService(client=StubClient(error=AIClientError("boom")))
    results = await service.enrich(enrichment_request())

    assert len(results) == 3
    for result in results:
        assert result.confidence == 0.0
        assert result.recommendation is None
        assert "unavailable" in result.explanation


@pytest.mark.asyncio
async def test_out_of_vocabulary_answer_is_discarded_not_passed_through():
    reply = {
        "classification": "definitely_a_database_thing",
        "priority": "urgent!!!",
        "root_cause": "slow query on the orders table",
        "confidence": 4.7,
        "explanation": "because reasons",
    }
    service = EnrichmentService(client=StubClient(reply=reply))
    results = await service.enrich(enrichment_request())
    by_capability = {r.capability: r for r in results}

    assert by_capability["classification"].recommendation is None
    assert by_capability["priority"].recommendation is None
    # Free-text root cause survives; enum fields don't.
    assert by_capability["root_cause"].recommendation == "slow query on the orders table"
    # Confidence is clamped into the contract's [0, 1] whatever the model said.
    assert all(0.0 <= r.confidence <= 1.0 for r in results)


@pytest.mark.asyncio
async def test_partial_reply_yields_partial_results():
    service = EnrichmentService(client=StubClient(reply={"classification": "database"}))
    results = await service.enrich(enrichment_request())
    by_capability = {r.capability: r for r in results}

    assert by_capability["classification"].recommendation == "database"
    assert by_capability["priority"].recommendation is None
    assert all(r.explanation for r in results)


@pytest.mark.live
@live
@pytest.mark.asyncio
async def test_live_enrichment_satisfies_contract():
    """The real model, through the real app/ai/ code path. Asserts the
    contract every caller of EnrichmentService relies on — nothing more."""
    from app.ai.service import EnrichmentService as LiveService

    service = LiveService()
    results = await service.enrich(enrichment_request())

    assert {r.capability for r in results} == {"classification", "priority", "root_cause"}
    for result in results:
        assert str(result.alert_id)
        assert 0.0 <= result.confidence <= 1.0
        assert result.explanation
        assert result.model_name
        if result.capability == "classification":
            assert result.recommendation in CLASSIFICATIONS
        if result.capability == "priority":
            assert result.recommendation in PRIORITIES
