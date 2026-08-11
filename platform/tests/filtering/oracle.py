"""Expected outcomes for filter/classification test scenarios.

An oracle maps a scenario name to the expected acceptance decision and,
optionally, the classification tags that a production classifier would add.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FilterOracle:
    accepted: bool
    expected_labels: dict[str, str] | None = None


ORACLE: dict[str, FilterOracle] = {
    "normal": FilterOracle(accepted=True, expected_labels={"priority": "p3"}),
    "ignored_source": FilterOracle(accepted=False),
    "maintenance": FilterOracle(accepted=False),
    "low_signal": FilterOracle(accepted=False),
    "noisy_probe": FilterOracle(accepted=False),
}
