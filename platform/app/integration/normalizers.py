from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5


def stable_id(namespace: str, value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"{namespace}:{value}")


def parse_epoch(value: str | int | float | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def to_event_data(alert_data: dict) -> dict:
    """Every normalize_* alert dict below doubles as its corresponding raw
    event: MonitoringEvent's open schema (extra="allow", see
    app/contracts/messages.py) means everything already computed here --
    severity, rule, summary, labels, whatever a given vendor added -- just
    rides along unchanged. The alert-specific `state`/`starts_at`/
    `occurred_at` keys get renamed to the event's own `status`/`timestamp`.

    Defensively renames a stray `event_id` key to `vendor_event_id` if a
    normalizer ever uses that name for a vendor's own id (see
    normalize_zabbix_problem's `vendor_event_id`, chosen precisely to avoid
    this): it must not collide with MonitoringEvent's own `event_id` (its
    record identity, a UUID) or with MonitoringAlert's `source_event_id`
    (the link *to* that record, a different UUID) -- three distinct
    things that happen to be easy to name the same by accident.
    """
    event_data = dict(alert_data)
    event_data["status"] = event_data.pop("state", "unknown")
    timestamp = event_data.pop("occurred_at", None) or event_data.pop("starts_at", None)
    if timestamp:
        event_data["timestamp"] = timestamp
    if "event_id" in event_data:
        event_data["vendor_event_id"] = event_data.pop("event_id")
    return event_data


def normalize_alertmanager(alert: dict) -> tuple[UUID, UUID, dict]:
    labels = {str(k): str(v) for k, v in alert.get("labels", {}).items()}
    annotations = {str(k): str(v) for k, v in alert.get("annotations", {}).items()}
    fingerprint = str(alert.get("fingerprint") or labels.get("alertname", "unknown"))
    status = str(alert.get("status", "firing"))
    starts_at = str(alert.get("startsAt", ""))
    message_id = stable_id("alertmanager", f"{fingerprint}:{status}:{starts_at}")
    correlation_id = stable_id("alertmanager", fingerprint)
    return message_id, correlation_id, {
        "alert_id": str(correlation_id),
        "rule": labels.get("alertname", "AlertmanagerAlert"),
        "severity": labels.get("severity", "warning").lower(),
        "source": "prometheus",
        "metric": labels.get("alertname", "unknown"),
        "value": 1.0 if status == "firing" else 0.0,
        "threshold": 1.0,
        "state": status,
        "starts_at": alert.get("startsAt"),
        "ends_at": alert.get("endsAt"),
        "generator_url": alert.get("generatorURL"),
        "summary": annotations.get("summary", labels.get("alertname", "")),
        "description": annotations.get("description", ""),
        "runbook": annotations.get("runbook", annotations.get("runbook_url", "")),
        "labels": labels,
    }


def normalize_zabbix_problem(problem: dict) -> tuple[UUID, UUID, dict]:
    event_id = str(problem["eventid"])
    clock = str(problem.get("clock", ""))
    message_id = stable_id("zabbix-problem", f"{event_id}:{clock}")
    correlation_id = stable_id("zabbix-problem", event_id)
    tags = {str(tag["tag"]): str(tag["value"]) for tag in problem.get("tags", [])}
    hosts = problem.get("hosts", [])
    host = hosts[0].get("host", "unknown") if hosts else "unknown"
    severity = {0: "info", 1: "warning", 2: "warning", 3: "average", 4: "high", 5: "critical"}.get(
        int(problem.get("severity", 0)), "warning"
    )
    return message_id, correlation_id, {
        "alert_id": str(correlation_id),
        "rule": "ZabbixProblem",
        "severity": severity,
        "source": "zabbix",
        "metric": problem.get("name", "zabbix_problem"),
        "value": 1.0,
        "threshold": 1.0,
        "state": "firing",
        "vendor_event_id": event_id,
        "summary": problem.get("name", "Zabbix problem"),
        "description": problem.get("opdata", ""),
        "occurred_at": parse_epoch(problem.get("clock")).isoformat(),
        "labels": {"host": host, **tags},
    }
