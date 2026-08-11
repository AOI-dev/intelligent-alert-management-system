"""Turns a `route` Decision into a NotificationRequest addressed at a human.

This is the link that was missing end to end: the platform produced
Decisions and the notifications stack consumed NotificationRequests, but
nothing converted one into the other, so no alert ever reached a person.

Order of operations matters here. The recipient is resolved from the
routing registry FIRST, and the model is only asked for wording once we
know there is somebody to send it to -- an unroutable alert must not spend
a GPU slot, and at storm time that is the difference between a queue that
drains and one that does not.
"""
from __future__ import annotations

import logging
from uuid import UUID

from app.ai.summarize import NotificationSummarizer, Summary
from app.contracts.messages import Decision, MonitoringAlert, NotificationRequest
from app.core.pipeline import default_key
from app.integration.normalizers import stable_id
from app.routing.registry import RoutingRegistry, Target

logger = logging.getLogger(__name__)

ROUTE_DECISION_TYPE = "route"


def incident_id_for(alert: MonitoringAlert) -> UUID:
    """A stable incident id for the alert's correlation key.

    FlapAwareCorrelator never populates Decision.incident_id (it decides per
    key without owning incident identity), but NotificationRequest requires
    one. Deriving it from the same key the correlator grouped on means every
    alert in one correlation group shares an incident id, deterministically
    and with no state to keep -- which is also what lets the notifications
    dispatcher dedup across restarts.
    """
    return stable_id("incident", default_key(alert))


def render_message(alert: MonitoringAlert, summary: Summary, target: Target) -> str:
    """The TrueConf message body. Markdown, since trueconf-bot sends with
    ParseMode.MARKDOWN."""
    service = alert.labels.get("service") or alert.source
    lines = [
        f"**[{summary.priority.upper()}] {summary.headline}**",
        "",
        f"- service: `{service}`  host: `{alert.source}`",
        f"- metric: `{alert.metric}` = `{alert.value:g}` (threshold `{alert.threshold:g}`)",
        f"- severity: `{alert.severity}`  on-call: `{target.target_id}` ({target.team})",
        "",
        f"➡️ {summary.next_step}",
    ]
    return "\n".join(lines)


class NotificationRouter:
    """Decision + alert -> NotificationRequest, or None when unroutable."""

    def __init__(
        self,
        registry: RoutingRegistry,
        summarizer: NotificationSummarizer | None = None,
    ) -> None:
        self._registry = registry
        self._summarizer = summarizer or NotificationSummarizer()

    @property
    def configured(self) -> bool:
        return self._registry.configured

    async def build(self, decision: Decision, alert: MonitoringAlert) -> NotificationRequest | None:
        if decision.decision_type != ROUTE_DECISION_TYPE:
            return None

        service = alert.labels.get("service")
        target = self._registry.resolve(service)
        if target is None:
            logger.warning(
                "No routing target for service %r (alert %s); not notifying",
                service,
                alert.alert_id,
            )
            return None

        summary = await self._summarizer.summarize(alert, decision.reason)
        return NotificationRequest(
            incident_id=decision.incident_id or incident_id_for(alert),
            target_id=target.target_id,
            webhook_url=target.webhook_url,
            priority=summary.priority,
            reason=decision.reason,
            payload={
                # What trueconf-bot needs to deliver, and nothing it has to
                # guess at.
                "trueconf_id": target.trueconf_id,
                "text": render_message(alert, summary, target),
                # Context for any other webhook consumer, and for debugging
                # which path wrote the wording.
                "headline": summary.headline,
                "next_step": summary.next_step,
                "summary_source": summary.source,
                "alert_id": str(alert.alert_id),
                "rule": alert.rule,
                "severity": alert.severity,
                "source": alert.source,
                "metric": alert.metric,
                "value": alert.value,
                "labels": alert.labels,
                "policy_id": decision.policy_id,
            },
        )
