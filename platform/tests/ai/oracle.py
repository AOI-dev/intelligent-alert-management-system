"""Expected AI enrichment results for happy-path tests."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EnrichmentOracle:
    capability: str
    expected_classification: str | None = None
    expected_priority: str | None = None
    min_confidence: float = 0.0
    requires_explanation: bool = True


ORACLE: dict[str, EnrichmentOracle] = {
    "classification": EnrichmentOracle(
        capability="classification",
        expected_classification="database_degradation",
        min_confidence=0.8,
        requires_explanation=True,
    ),
    "priority": EnrichmentOracle(
        capability="priority",
        expected_priority="p2",
        min_confidence=0.8,
    ),
    "root_cause": EnrichmentOracle(
        capability="root_cause",
        min_confidence=0.7,
        requires_explanation=True,
    ),
}
