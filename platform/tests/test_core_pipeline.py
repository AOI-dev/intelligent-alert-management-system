from app.contracts.messages import Decision, MonitoringAlert
from app.core.pipeline import CorrelationEngine, PassThroughSequenceTransform, default_key
from app.core.window import TimeBoundedWindow


def _alert(**overrides) -> MonitoringAlert:
    fields: dict = dict(rule="cpu-high", severity="critical", source="zabbix", metric="cpu", value=99.0, threshold=90.0)
    fields.update(overrides)
    return MonitoringAlert(**fields)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_window_evicts_entries_older_than_window_seconds():
    clock = FakeClock()
    window = TimeBoundedWindow(window_seconds=10, now_fn=clock)

    window.add("key", _alert())
    clock.now = 5
    window.add("key", _alert())
    clock.now = 11
    contents = window.add("key", _alert())

    assert len(contents) == 2


def test_window_keeps_independent_keys_separate():
    window = TimeBoundedWindow(window_seconds=10, now_fn=lambda: 0.0)

    window.add("a", _alert(source="a"))
    window.add("b", _alert(source="b"))

    assert len(window.snapshot("a")) == 1
    assert len(window.snapshot("b")) == 1


def test_default_key_groups_by_source_and_metric():
    assert default_key(_alert(source="zabbix", metric="cpu")) == "zabbix:cpu"
    assert default_key(_alert(source="zabbix", metric="disk")) != default_key(_alert(source="zabbix", metric="cpu"))


def test_engine_defaults_are_pass_through_and_produce_no_decisions():
    engine = CorrelationEngine()

    decisions = engine.process(_alert())

    assert decisions == []


def test_engine_applies_alert_transforms_before_windowing():
    seen_severities = []

    class RecordingTransform:
        def apply(self, alert):
            seen_severities.append(alert.severity)
            return alert.model_copy(update={"severity": "downgraded"})

    engine = CorrelationEngine(alert_transforms=[RecordingTransform()])
    engine.process(_alert(severity="critical"))

    assert seen_severities == ["critical"]


def test_engine_collects_decisions_from_injected_sequence_transform():
    class AlwaysSuppress:
        def apply(self, key, window):
            return [
                Decision(decision_type="suppress", alert_id=window[-1].alert_id, action="suppress", reason="test")
            ]

    engine = CorrelationEngine(sequence_transforms=[PassThroughSequenceTransform(), AlwaysSuppress()])

    decisions = engine.process(_alert())

    assert len(decisions) == 1
    assert decisions[0].decision_type == "suppress"


def test_engine_uses_injected_key_fn():
    seen_keys = []

    class RecordingWindow(TimeBoundedWindow):
        def add(self, key, alert):
            seen_keys.append(key)
            return super().add(key, alert)

    engine = CorrelationEngine(window=RecordingWindow(60, now_fn=lambda: 0.0), key_fn=lambda alert: "fixed-key")
    engine.process(_alert())

    assert seen_keys == ["fixed-key"]
