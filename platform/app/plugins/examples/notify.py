"""Example executor: send decisions to a webhook.

Replace the URL with your notification endpoint (Slack, PagerDuty, etc.).
"""

import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.contracts.messages import Decision
from app.plugins.ports import DecisionExecutor, PluginMetadata

logger = logging.getLogger(__name__)


class WebhookExecutor:
    """POSTs every decision to a configured URL."""

    metadata = PluginMetadata(
        name="webhook-executor",
        version="0.1.0",
        category="execution",
        description="POSTs decisions to a webhook URL.",
    )

    def __init__(self, url: str) -> None:
        self._url = url

    async def can_execute(self, decision: Decision) -> bool:
        return decision.decision_type in ("route", "suppress")

    async def execute(self, decision: Decision, context: Mapping[str, Any]) -> None:
        payload = {
            "type": decision.decision_type,
            "alert_id": str(decision.alert_id),
            "reason": decision.reason,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(self._url, json=payload)
        except Exception:
            logger.exception("Webhook POST failed for alert %s", decision.alert_id)
