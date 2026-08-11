"""Expected decisions/incidents for core correlation/detection scenarios.

The oracle is intentionally high-level: it states how many decisions of each
type a correct implementation should emit, not the exact alert ids. That keeps
the tests stable while algorithms evolve.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CoreOracle:
    """Decision counts expected for a scenario."""

    route_count: int = 0
    dedup_count: int = 0
    suppress_count: int = 0
    # Upper bound on how many incidents may be created (for detection tests).
    max_incidents: int | None = None


ORACLE: dict[str, CoreOracle] = {
    # First alert opens an incident; the rest are duplicates.
    "duplicate_storm": CoreOracle(route_count=1, dedup_count=9, max_incidents=1),
    # First alert opens an incident; the rest are correlated updates.
    "correlated_cascade": CoreOracle(route_count=1, max_incidents=1),
    # Severity escalation should update the existing incident, not create a new one.
    "severity_escalation": CoreOracle(route_count=1, max_incidents=1),
    # Flapping should be suppressed after the first actionable alert.
    "flapping_alerts": CoreOracle(route_count=1, suppress_count=3, max_incidents=1),
    # Unrelated services should each get their own incident.
    "multi_tenant_noise": CoreOracle(route_count=3, max_incidents=3),
}
