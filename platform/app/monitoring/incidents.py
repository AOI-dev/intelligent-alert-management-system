"""Incident read model, derived from the alert and decision streams.

An incident here is not a new source of truth: it is the correlation key,
observed. `app/routing/service.py:incident_id_for` already derives a stable
incident id from the key so the notifications dispatcher can dedup across
restarts -- this module groups by that same id, so the incident a user acks
on the dashboard is by construction the one the on-call engineer was paged
about. Any other derivation would let the two drift.

What opens an incident is a `route` decision, not an alert. Alerts that the
correlator dedups or suppresses belong to an incident (they are counted on
it) but do not create one: an incident is something the platform decided a
human should know about, and a suppressed flap is precisely the opposite.

SCOPE, stated plainly, because the difference matters for what the screen
can be trusted to say:

- This is a live-tail projection with the same bounds as
  app/monitoring/store.py -- it holds the most recent `limit` incidents and
  is rebuilt from scratch on restart. It is not history; the TimescaleDB
  projection is (app/monitoring/persistence.py).
- There is no `resolved` status. Nothing in the pipeline publishes a
  resolution signal today, and inventing one from "we stopped hearing about
  it" would be a guess presented as a fact. Statuses are `open` and
  `acknowledged`, and an incident stops updating when its alerts stop.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from app.contracts.messages import Decision, MonitoringAlert
from app.core.correlation_automaton import SEVERITY_RANK
from app.core.pipeline import default_key
from app.routing.service import incident_id_for

ROUTE = "route"
_UNKNOWN_RANK = SEVERITY_RANK["warning"]


def _rank(severity: str) -> int:
    return SEVERITY_RANK.get(severity.lower(), _UNKNOWN_RANK)


class IncidentProjection:
    """Bounded, in-memory incidents derived from what the core decided."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._incidents: OrderedDict[UUID, dict] = OrderedDict()

    def observe(
        self,
        alert: MonitoringAlert,
        decisions: Sequence[Decision],
        occurred_at: datetime | None = None,
    ) -> dict | None:
        """Fold one alert and the decisions it produced into the projection.

        Returns the incident this alert belongs to, or None when the alert
        belongs to no open incident -- i.e. it was deduped or suppressed on a
        key that has never paged anyone. Such an alert is deliberately
        dropped rather than opening an incident retroactively: it is visible
        on the Алерты and Решения screens, where the reason it went nowhere
        is the point.
        """
        seen_at = occurred_at or datetime.now(timezone.utc)
        incident_id = incident_id_for(alert)
        existing = self._incidents.get(incident_id)
        routes = [d for d in decisions if d.decision_type == ROUTE]

        if existing is None:
            if not routes:
                return None
            existing = self._open(incident_id, alert, seen_at)

        self._update(existing, alert, decisions, routes, seen_at)
        self._incidents.move_to_end(incident_id)
        while len(self._incidents) > self._limit:
            self._incidents.popitem(last=False)
        return existing

    def _open(self, incident_id: UUID, alert: MonitoringAlert, seen_at: datetime) -> dict:
        key = default_key(alert)
        incident = {
            "incident_id": str(incident_id),
            "correlation_key": key,
            # Named after the alert that opened it, deterministically. The AI
            # contour writes nicer headlines (app/ai/summarize.py), but it is
            # off by default and may be unavailable -- an incident must be
            # identifiable on screen regardless, so the title never depends
            # on the model.
            "title": f"{alert.rule} · {alert.labels.get('service') or alert.source}",
            "service": alert.labels.get("service"),
            "status": "open",
            "severity": alert.severity,
            "opened_at": seen_at.isoformat(),
            "updated_at": seen_at.isoformat(),
            "first_alert_id": str(alert.alert_id),
            "last_alert_id": str(alert.alert_id),
            "alert_count": 0,
            "notification_count": 0,
            "decisions_by_type": {},
            "last_action": None,
            "last_reason": None,
            # The reason attached to the most recent `route` decision, kept
            # apart from last_reason on purpose: a long-running incident's
            # newest decision is usually "identical repeat of an
            # already-tracked signal", which explains why the last alert was
            # quiet, not why anyone was paged. The screen needs the latter.
            "page_reason": None,
            "page_action": None,
            "policy_id": None,
            "acknowledged_by": None,
            "acknowledged_by_label": None,
            "acknowledged_at": None,
            "acknowledgement_note": None,
        }
        self._incidents[incident_id] = incident
        return incident

    def _update(
        self,
        incident: dict,
        alert: MonitoringAlert,
        decisions: Sequence[Decision],
        routes: Sequence[Decision],
        seen_at: datetime,
    ) -> None:
        incident["alert_count"] += 1
        incident["last_alert_id"] = str(alert.alert_id)
        incident["updated_at"] = seen_at.isoformat()
        # Peak, not latest: an incident that reached critical stays reported as
        # critical even while a lower-severity signal on the same key is the
        # most recent thing to arrive.
        if _rank(alert.severity) > _rank(incident["severity"]):
            incident["severity"] = alert.severity
        if alert.labels.get("service") and not incident["service"]:
            incident["service"] = alert.labels["service"]

        counts = incident["decisions_by_type"]
        for decision in decisions:
            counts[decision.decision_type] = counts.get(decision.decision_type, 0) + 1
            incident["last_action"] = decision.action
            incident["last_reason"] = decision.reason
            incident["policy_id"] = decision.policy_id or incident["policy_id"]

        if routes:
            incident["notification_count"] += len(routes)
            incident["page_reason"] = routes[-1].reason
            incident["page_action"] = routes[-1].action
            # A fresh page on an acknowledged incident reopens it. Someone
            # acked "the database is slow"; being paged again means it got
            # worse (escalate_incident) and the ack no longer covers it.
            if incident["status"] == "acknowledged":
                incident["status"] = "open"
                incident["acknowledged_by"] = None
                incident["acknowledged_by_label"] = None
                incident["acknowledged_at"] = None
                incident["acknowledgement_note"] = None

    def list(self) -> list[dict]:
        """Most recently updated first, matching MessageStore.list()."""
        return list(reversed(self._incidents.values()))

    def get(self, incident_id: UUID) -> dict | None:
        return self._incidents.get(incident_id)

    def acknowledge(
        self,
        incident_id: UUID,
        by: str,
        display_label: str | None = None,
        note: str | None = None,
    ) -> dict | None:
        """`by` is the platform identity id -- the pseudonymous technical
        identifier that is the only thing the database is allowed to keep
        (АР-07). `display_label` is carried alongside it for rendering only,
        and lives no longer than this in-memory projection does.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            return None
        incident["status"] = "acknowledged"
        incident["acknowledged_by"] = by
        incident["acknowledged_by_label"] = display_label
        incident["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
        incident["acknowledgement_note"] = note
        return incident
