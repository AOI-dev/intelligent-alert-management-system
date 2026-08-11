"""Synthetic inputs and mock LLM outputs for AI enrichment tests."""
from uuid import uuid4

from app.contracts.messages import EnrichmentRequest, MonitoringAlert


def make_alert(rule: str = "api-latency", severity: str = "high") -> MonitoringAlert:
    return MonitoringAlert(
        alert_id=uuid4(),
        rule=rule,
        severity=severity,
        source="prometheus",
        metric="api_latency_p99",
        value=2.5,
        threshold=1.0,
        labels={"service": "payments", "env": "prod"},
    )


def enrichment_request() -> EnrichmentRequest:
    return EnrichmentRequest(
        alert=make_alert(),
        requested_capabilities=["classification", "priority", "root_cause"],
        deadline_at="2099-01-01T00:00:00Z",
        feature_mode="suggest",
    )


def mock_llm_classification_response() -> dict:
    """Example structured output an internal LLM might return."""
    return {
        "classification": "database_degradation",
        "priority": "p2",
        "root_cause": "slow_query_on_orders_table",
        "confidence": 0.87,
        "explanation": "Latency spike correlates with disk queue depth on the primary database.",
        "recommended_team": "db-oncall",
    }
