"""Built-in webhook adapters for the vendors this stack ships with.

These wrap the existing normalizers so `POST /v1/integrations/{slug}/webhook`
in app/main.py never branches on vendor identity — it looks up the adapter
by slug and calls `.parse()`. A third-party monitoring client with a
completely different payload shape plugs in the same way: implement
WebhookAlertSource, register it via PLUGIN_PATHS, done. No core changes.
"""

from collections.abc import Sequence
from typing import Any

from app.integration.normalizers import normalize_alertmanager, normalize_zabbix_problem
from app.plugins.ports import ParsedAlert, PluginMetadata


class AlertmanagerWebhookSource:
    """Prometheus Alertmanager `webhook_config` payload: `{"alerts": [...]}`."""

    metadata = PluginMetadata(
        name="alertmanager-webhook",
        version="1.0.0",
        category="webhook-source",
        description="Prometheus Alertmanager webhook_config payload.",
    )
    slug = "alertmanager"

    def parse(self, payload: Any) -> Sequence[ParsedAlert]:
        alert_items = payload.get("alerts") if isinstance(payload, dict) else None
        if not isinstance(alert_items, list):
            raise ValueError("Alertmanager payload must contain alerts[]")
        return [ParsedAlert(*normalize_alertmanager(item)) for item in alert_items]


class ZabbixWebhookSource:
    """Zabbix action-webhook payload: a flat object keyed by `eventid` (see README)."""

    metadata = PluginMetadata(
        name="zabbix-webhook",
        version="1.0.0",
        category="webhook-source",
        description="Zabbix action-webhook payload.",
    )
    slug = "zabbix"

    def parse(self, payload: Any) -> Sequence[ParsedAlert]:
        if not isinstance(payload, dict) or not isinstance(payload.get("eventid"), (str, int)):
            raise ValueError("Zabbix payload must contain eventid")
        return [ParsedAlert(*normalize_zabbix_problem(payload))]
