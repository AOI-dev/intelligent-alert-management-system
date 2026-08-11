"""Happy-path tests for the AI enrichment contour.

The AI module currently only defines ports (app/ai/ports.py:
EnrichmentPublisher, EnrichmentResultHandler) -- no worker calls a real LLM
anywhere yet, vLLM env vars notwithstanding (see platform/flags.env; no
client code reads them). test_mock_response_satisfies_oracle is xfail on
purpose: _to_result below is a parser this test file invents for itself,
not anything in app/ai/, so without the xfail it would pass by
construction regardless of whether real enrichment exists -- a mock
tested against itself, same trap tests/core/test_core.py's oracle tests
were in before FlapAwareCorrelator actually existed to satisfy them. Once
a real service parses a real LLM response through real app/ai/ code, wire
this test to call that instead of _to_result and drop the xfail -- same
transition test_core.py already went through.
"""
import pytest

from tests.ai.fixtures import enrichment_request, mock_llm_classification_response
from tests.ai.oracle import ORACLE


def _to_result(alert_id, capability: str, response: dict) -> dict:
    """Stand-in only -- not app/ai/ code. See module docstring."""
    return {
        "alert_id": str(alert_id),
        "capability": capability,
        "confidence": response.get("confidence", 0.0),
        "explanation": response.get("explanation", ""),
        "model_name": "mock-llm",
        "model_version": "0.1.0",
        "recommendation": response.get(f"expected_{capability}") or response.get(capability),
    }


@pytest.mark.xfail(
    reason="no real enrichment service exists yet -- this only proves a test-local mock parser "
    "satisfies the oracle, not any app/ai/ code; see module docstring",
    strict=True,
)
@pytest.mark.parametrize("capability", ["classification", "priority", "root_cause"])
def test_mock_response_satisfies_oracle(capability: str):
    request = enrichment_request()
    oracle = ORACLE[capability]
    response = mock_llm_classification_response()
    result = _to_result(request.alert.alert_id, capability, response)

    assert result["capability"] == oracle.capability
    assert result["confidence"] >= oracle.min_confidence
    if oracle.expected_classification:
        assert result["recommendation"] == oracle.expected_classification
    if oracle.expected_priority:
        assert result["recommendation"] == oracle.expected_priority
    if oracle.requires_explanation:
        assert result["explanation"]


def test_enrichment_request_carries_alert_and_capabilities():
    request = enrichment_request()
    assert request.alert.rule == "api-latency"
    assert "classification" in request.requested_capabilities
    assert request.feature_mode == "suggest"
