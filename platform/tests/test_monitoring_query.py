"""Pure-function tests for the frontend's read endpoints (app/main.py's
/v1/events, /v1/alerts, /v1/alerts/{id}, /v1/decisions, /v1/summary) --
exercised directly against app.monitoring.query, without FastAPI, auth, or
Kafka in the loop, since that's all real logic these endpoints run.
"""
from uuid import uuid4

from app.contracts.messages import Decision
from app.monitoring.query import filter_messages, find_by_field, summarize
from app.monitoring.store import MessageStore


def _envelope(data: dict, occurred_at: str = "2026-01-01T00:00:00+00:00") -> dict:
    return {"message_id": "m1", "occurred_at": occurred_at, "data": data}


def test_filter_messages_with_no_filters_returns_everything():
    items = [_envelope({"severity": "critical"}), _envelope({"severity": "warning"})]

    assert filter_messages(items) == items


def test_filter_messages_matches_a_single_field_case_insensitively():
    items = [_envelope({"severity": "CRITICAL"}), _envelope({"severity": "warning"})]

    result = filter_messages(items, severity="critical")

    assert result == [items[0]]


def test_filter_messages_matches_all_given_fields():
    items = [
        _envelope({"severity": "critical", "source": "zabbix"}),
        _envelope({"severity": "critical", "source": "prometheus"}),
    ]

    result = filter_messages(items, severity="critical", source="prometheus")

    assert result == [items[1]]


def test_filter_messages_ignores_none_valued_filters():
    items = [_envelope({"severity": "critical"})]

    assert filter_messages(items, severity=None) == items


def test_filter_messages_by_since_excludes_older_items():
    from datetime import datetime, timezone

    older = _envelope({}, occurred_at="2026-01-01T00:00:00+00:00")
    newer = _envelope({}, occurred_at="2026-01-02T00:00:00+00:00")
    cutoff = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    assert filter_messages([older, newer], since=cutoff) == [newer]


def test_filter_messages_works_on_flat_items_with_no_envelope():
    """Decisions are stored flat (no "data" wrapper) -- filtering must
    still work directly against the item.
    """
    items = [{"decision_type": "route"}, {"decision_type": "dedup"}]

    result = filter_messages(items, decision_type="dedup")

    assert result == [items[1]]


def test_find_by_field_returns_the_matching_item():
    items = [_envelope({"alert_id": "a1"}), _envelope({"alert_id": "a2"})]

    assert find_by_field(items, "alert_id", "a2") == items[1]


def test_find_by_field_returns_none_when_nothing_matches():
    items = [_envelope({"alert_id": "a1"})]

    assert find_by_field(items, "alert_id", "missing") is None


def test_find_by_field_works_on_flat_items():
    items = [{"decision_id": "d1"}, {"decision_id": "d2"}]

    assert find_by_field(items, "decision_id", "d1") == items[0]


def test_summarize_counts_alerts_by_severity_and_decisions_by_type():
    alert_items = [
        _envelope({"severity": "critical"}),
        _envelope({"severity": "critical"}),
        _envelope({"severity": "warning"}),
    ]
    decision_items = [{"decision_type": "route"}, {"decision_type": "route"}, {"decision_type": "dedup"}]

    result = summarize(events_count=10, alert_items=alert_items, decision_items=decision_items, window_limit=500)

    assert result == {
        "events_in_window": 10,
        "alerts_in_window": 3,
        "alerts_by_severity": {"critical": 2, "warning": 1},
        "decisions_by_type": {"route": 2, "dedup": 1},
        "window_limit": 500,
    }


def test_summarize_with_no_data_returns_zeroed_counts():
    result = summarize(events_count=0, alert_items=[], decision_items=[], window_limit=500)

    assert result == {
        "events_in_window": 0,
        "alerts_in_window": 0,
        "alerts_by_severity": {},
        "decisions_by_type": {},
        "window_limit": 500,
    }


def test_decisions_are_storable_by_their_own_id():
    """Regression: MessageStore defaulted to `message_id`, which a Decision
    does not have. add() raised KeyError, KafkaTopicConsumer classified that
    as a malformed message and dropped it, and the exception took the rest of
    handle_alert down with it -- so on a deployed platform no decision was
    ever stored, published, audited or turned into a notification, and the
    only trace was a "dropping malformed Kafka message" warning.
    """
    store = MessageStore(10, id_field="decision_id")
    decision = Decision(
        decision_type="route", alert_id=uuid4(), action="open_incident", reason="first alert"
    ).model_dump(mode="json")

    assert store.add(decision) is True
    assert store.add(decision) is False, "the same decision must not be stored twice"
    assert store.list() == [decision]
