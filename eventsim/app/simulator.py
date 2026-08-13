import random

from app.models import EventIn
from app.rules import RULES

_SOURCES = ["web-01", "web-02", "db-01", "worker-03"]

# Which service each simulated host belongs to. The names are the ones
# platform/config/routing.json routes on, so an alert that travels the long
# way round -- scraped by Prometheus, alerted by Alertmanager, posted to the
# platform's webhook -- still resolves to a real on-call engineer. Without
# this the alert arrives with no `service` label and is unroutable.
SERVICE_BY_SOURCE = {
    "web-01": "storefront_web",
    "web-02": "storefront_web",
    "db-01": "db_primary",
    "worker-03": "payments_api",
}


def generate_synthetic_event() -> EventIn:
    """Random event over one of the known rule metrics.

    Occasionally exceeds its threshold so autogenerate mode has something to
    fire triggers on without a real monitoring system feeding it yet.
    """
    rule = random.choice(RULES)
    breach = random.random() < 0.2
    if breach:
        value = rule.threshold * (1.2 if rule.op in (">", ">=") else 0.5)
    else:
        value = rule.threshold * (0.5 if rule.op in (">", ">=") else 1.5)
    source = random.choice(_SOURCES)
    return EventIn(
        source=source,
        metric=rule.metric,
        value=round(value, 2),
        labels={"service": SERVICE_BY_SOURCE[source]},
    )
