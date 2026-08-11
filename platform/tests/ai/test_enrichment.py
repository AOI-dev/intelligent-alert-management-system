"""Happy-path tests for the AI enrichment contour.

The AI module currently only defines ports. These tests parse a mock LLM
response and assert the contract a real enrichment service must satisfy.
"""
import pytest

from tests.ai.fixtures import enrichment_request, mock_llm_classification_response
from tests.ai.oracle import ORACLE


def _to_result(alert_id, capability: str, response: dict) -> dict:
    """Minimal parser mirroring what a real enrichment service would do."""
    return {
        "alert_id": str(alert_id),
        "capability": capability,
        "confidence": response.get("confidence", 0.0),
        "explanation": response.get("explanation", ""),
        "model_name": "mock-llm",
        "model_version": "0.1.0",
        "recommendation": response.get(f"expected_{capability}") or response.get(capability),
    }


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
