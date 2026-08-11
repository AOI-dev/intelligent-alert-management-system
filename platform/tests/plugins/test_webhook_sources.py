"""Usage tests for the WebhookAlertSource adapter API.

These exist to demonstrate — and pin down — how a new monitoring client
plugs in, not to exhaustively cover the builtins. In particular
test_third_party_adapter_with_unrelated_payload_shape below defines a
from-scratch adapter for a fictitious vendor whose payload looks nothing
like Alertmanager's or Zabbix's, to prove the port doesn't quietly assume
one vendor's shape.
"""

from collections.abc import Sequence
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.plugins.builtins.webhooks import AlertmanagerWebhookSource, ZabbixWebhookSource
from app.plugins.ports import ParsedAlert, PluginMetadata, WebhookAlertSource
from app.plugins.registry import PluginRegistry


def test_alertmanager_adapter_parses_alerts_array():
    source = AlertmanagerWebhookSource()
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "HighCPU", "severity": "critical"},
                "annotations": {"summary": "CPU pegged"},
                "startsAt": "2026-08-11T10:00:00Z",
                "fingerprint": "abc123",
            }
        ]
    }

    parsed = source.parse(payload)

    assert len(parsed) == 1
    assert isinstance(parsed[0], ParsedAlert)
    assert parsed[0].data["source"] == "prometheus"
    assert parsed[0].data["severity"] == "critical"


def test_alertmanager_adapter_rejects_payload_without_alerts_array():
    with pytest.raises(ValueError, match="alerts"):
        AlertmanagerWebhookSource().parse({"not_alerts": []})


def test_zabbix_adapter_parses_flat_event_object():
    source = ZabbixWebhookSource()
    payload = {
        "eventid": "42",
        "name": "Disk full",
        "severity": "4",
        "clock": "1710000000",
        "hosts": [{"host": "db-01"}],
        "tags": [{"tag": "service", "value": "payments"}],
    }

    parsed = source.parse(payload)

    assert len(parsed) == 1
    assert parsed[0].data["source"] == "zabbix"
    assert parsed[0].data["labels"]["host"] == "db-01"


def test_zabbix_adapter_rejects_payload_without_eventid():
    with pytest.raises(ValueError, match="eventid"):
        ZabbixWebhookSource().parse({"name": "no id here"})


def test_third_party_adapter_with_unrelated_payload_shape():
    """A vendor that isn't Alertmanager or Zabbix: a bare uptime beacon
    (`{"host": "...", "up": bool}`), no severity/labels/timestamps at all.
    Proves an adapter can invent whatever shape its vendor needs.
    """

    class PingBeaconWebhookSource:
        metadata = PluginMetadata(
            name="pingbeacon-webhook",
            version="0.1.0",
            category="webhook-source",
            description="Fictitious uptime beacon for adapter-flexibility testing.",
        )
        slug = "pingbeacon"

        def parse(self, payload: Any) -> Sequence[ParsedAlert]:
            if not isinstance(payload, dict) or "host" not in payload or "up" not in payload:
                raise ValueError("PingBeacon payload must contain host and up")
            host = str(payload["host"])
            up = bool(payload["up"])
            correlation_id = uuid5(NAMESPACE_URL, f"pingbeacon:{host}")
            message_id = uuid5(NAMESPACE_URL, f"pingbeacon:{host}:{up}")
            return [
                ParsedAlert(
                    message_id=message_id,
                    correlation_id=correlation_id,
                    data={
                        "alert_id": str(correlation_id),
                        "rule": "PingBeaconDown",
                        "severity": "critical" if not up else "info",
                        "source": "pingbeacon",
                        "metric": "up",
                        "value": 1.0 if up else 0.0,
                        "threshold": 1.0,
                        "labels": {"host": host},
                    },
                )
            ]

    assert isinstance(PingBeaconWebhookSource(), WebhookAlertSource)

    source = PingBeaconWebhookSource()
    parsed = source.parse({"host": "edge-07", "up": False})
    assert parsed[0].data["severity"] == "critical"

    with pytest.raises(ValueError):
        source.parse({"host": "edge-07"})

    registry = PluginRegistry([AlertmanagerWebhookSource(), ZabbixWebhookSource(), source])
    assert registry.webhook_source("pingbeacon") is source
    assert registry.webhook_source("zabbix") is not None
    assert registry.webhook_source("unknown-vendor") is None
    assert {m.name for m in registry.all_metadata} == {
        "alertmanager-webhook",
        "zabbix-webhook",
        "pingbeacon-webhook",
    }


def test_registry_rejects_two_adapters_claiming_the_same_slug():
    class DuplicateZabbixWebhookSource:
        metadata = PluginMetadata(name="duplicate-zabbix", version="0.0.1", category="webhook-source")
        slug = "zabbix"

        def parse(self, payload: Any) -> Sequence[ParsedAlert]:
            return []

    with pytest.raises(ValueError, match="zabbix"):
        PluginRegistry([ZabbixWebhookSource(), DuplicateZabbixWebhookSource()])
