"""Finite-state correlation policy (АР-03).

tests/core/oracle.py and artifacts/happy-path.md describe this in prose —
scenario by scenario, and step by step. This module is that same policy
made explicit and executable: a small state machine per correlation key.

    NEW ---first alert---> OPEN
    OPEN ---new correlated signal, or an escalation of a known one---> OPEN   (silent)
    OPEN ---identical repeat of a known signal---> OPEN                      (dedup)
    OPEN ---a known signal recurs at a LOWER severity than before---> FLAPPING (suppress)
    FLAPPING ---anything, while the key stays unstable---> FLAPPING          (suppress)

"Signal identity" (rule, metric, source) is what makes this more than a
single OPEN/CLOSED flag: two different signals sharing a correlation key
(e.g. db-latency and api-errors under the same incident) are additional
evidence, not a repeat and not flapping — see the correlated_cascade vs.
severity_escalation vs. flapping_alerts scenarios in tests/core/fixtures.py
for why those three needed to be told apart.

Each SequenceTransform.apply() call gets the *entire* window for the key
(see app/core/ports.py), so the state for OPEN vs. FLAPPING is derived by
replaying that history rather than kept as mutable instance state. That
keeps this a pure function of (key, window), same as any other
SequenceTransform, and keeps "flapping" correctly sticky: once any signal
in the key's history has regressed, every later call sees that regression
in the replay and keeps suppressing, with no separate flag to fall out of
sync.
"""

from collections.abc import Sequence

from app.contracts.messages import Decision, MonitoringAlert

POLICY_ID = "flap-aware-correlator/v1"

# Ordinal severity, low to high. Unknown severities fall back to "warning"
# rather than erroring — a single unrecognized label from a new vendor
# shouldn't take a whole correlation key out of service.
SEVERITY_RANK: dict[str, int] = {
    "resolved": 0,
    "info": 1,
    "warning": 2,
    "average": 3,
    "high": 4,
    "critical": 5,
}
_DEFAULT_RANK = SEVERITY_RANK["warning"]

SignalIdentity = tuple[str, str, str]


def _severity_rank(alert: MonitoringAlert) -> int:
    return SEVERITY_RANK.get(alert.severity.lower(), _DEFAULT_RANK)


def _signal_identity(alert: MonitoringAlert) -> SignalIdentity:
    """The specific check this alert reports on. The same rule firing
    again is "the same signal, again"; a different rule sharing a
    correlation key is a distinct piece of evidence for the same incident.
    """
    return (alert.rule, alert.metric, alert.source)


def _is_identical_repeat(previous: MonitoringAlert, current: MonitoringAlert) -> bool:
    return (
        previous.rule == current.rule
        and previous.severity == current.severity
        and previous.source == current.source
        and previous.metric == current.metric
        and previous.value == current.value
    )


def _has_flapped(history: Sequence[MonitoringAlert]) -> bool:
    """True once some signal identity in `history` has recurred at a lower
    severity than its own previous occurrence.
    """
    last_rank_by_signal: dict[SignalIdentity, int] = {}
    for alert in history:
        signal = _signal_identity(alert)
        rank = _severity_rank(alert)
        previous_rank = last_rank_by_signal.get(signal)
        if previous_rank is not None and rank < previous_rank:
            return True
        last_rank_by_signal[signal] = rank
    return False


def _decision(decision_type, current: MonitoringAlert, action: str, reason: str) -> Decision:
    return Decision(
        decision_type=decision_type,
        alert_id=current.alert_id,
        action=action,
        reason=reason,
        policy_id=POLICY_ID,
    )


class FlapAwareCorrelator:
    """Default SequenceTransform for CorrelationEngine (see app/core/pipeline.py).

    Opens an incident on the first alert for a key; silently folds in
    escalations and additional correlated signals so they don't each
    trigger a fresh notification; dedups exact repeats; and suppresses
    once a key starts flapping.
    """

    def apply(self, _key: str, window: Sequence[MonitoringAlert]) -> list[Decision]:
        if not window:
            return []
        *history, current = window

        if not history:
            return [_decision("route", current, "open_incident", "first alert observed for correlation key")]

        if _has_flapped(history):
            return [
                _decision(
                    "suppress",
                    current,
                    "suppress_flap",
                    "correlation key is flapping; suppressing further notifications",
                )
            ]

        same_signal_history = [a for a in history if _signal_identity(a) == _signal_identity(current)]
        if not same_signal_history:
            return []  # a new signal correlated into an already-open incident

        last_same_signal = same_signal_history[-1]
        if _is_identical_repeat(last_same_signal, current):
            return [_decision("dedup", current, "dedup", "identical repeat of an already-tracked signal")]

        if _severity_rank(current) >= _severity_rank(last_same_signal):
            return []  # escalation, or steady state: fold into the open incident silently

        return [
            _decision(
                "suppress",
                current,
                "suppress_flap",
                "signal regressed to a lower severity than its last occurrence",
            )
        ]
