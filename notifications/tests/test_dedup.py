"""Pure logic tests for NotificationDeduplicator: dedup key is
(incident_id, target_id, webhook_url), window is measured from the last
successful delivery, and a failed delivery must not block a retry.
"""
from uuid import uuid4

from app.dedup import NotificationDeduplicator


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_not_a_duplicate_before_any_delivery():
    dedup = NotificationDeduplicator(window_seconds=60)
    incident_id = uuid4()

    assert dedup.is_duplicate(incident_id, "user-1", "https://hook.example/a") is False


def test_is_a_duplicate_within_the_window_after_delivery():
    clock = FakeClock()
    dedup = NotificationDeduplicator(window_seconds=60, clock=clock)
    incident_id = uuid4()

    dedup.mark_delivered(incident_id, "user-1", "https://hook.example/a")
    clock.now = 30

    assert dedup.is_duplicate(incident_id, "user-1", "https://hook.example/a") is True


def test_not_a_duplicate_once_the_window_has_passed():
    clock = FakeClock()
    dedup = NotificationDeduplicator(window_seconds=60, clock=clock)
    incident_id = uuid4()

    dedup.mark_delivered(incident_id, "user-1", "https://hook.example/a")
    clock.now = 61

    assert dedup.is_duplicate(incident_id, "user-1", "https://hook.example/a") is False


def test_different_target_is_not_a_duplicate():
    dedup = NotificationDeduplicator(window_seconds=60)
    incident_id = uuid4()

    dedup.mark_delivered(incident_id, "user-1", "https://hook.example/a")

    assert dedup.is_duplicate(incident_id, "user-2", "https://hook.example/a") is False


def test_different_channel_for_the_same_address_is_not_a_duplicate():
    """Same person, but a different channel (e.g. TrueConf vs email) --
    both should still be delivered.
    """
    dedup = NotificationDeduplicator(window_seconds=60)
    incident_id = uuid4()

    dedup.mark_delivered(incident_id, "user-1", "https://hook.example/trueconf")

    assert dedup.is_duplicate(incident_id, "user-1", "https://hook.example/email") is False


def test_different_incident_to_the_same_channel_and_address_is_not_a_duplicate():
    dedup = NotificationDeduplicator(window_seconds=60)

    dedup.mark_delivered(uuid4(), "user-1", "https://hook.example/a")

    assert dedup.is_duplicate(uuid4(), "user-1", "https://hook.example/a") is False
