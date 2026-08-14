"""Пример: чтение данных с датчика и вывод отчёта."""
import json
from dataclasses import dataclass


@dataclass
class SensorReading:
    """Показание датчика."""
    name: str
    value: float
    unit: str

    def is_critical(self, low: float, high: float) -> bool:
        return self.value < low or self.value > high


def load_readings(path: str) -> list[SensorReading]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [SensorReading(**item) for item in data]


def main():
    readings = [
        SensorReading("Температура", 23.5, "°C"),
        SensorReading("Влажность", 65.0, "%"),
        SensorReading("Давление", 1013.25, "гПа"),
    ]
    for r in readings:
        status = "НОРМА"
        if r.name == "Температура" and r.is_critical(18, 28):
            status = "КРИТИЧНО"
        print(f"{r.name}: {r.value} {r.unit} [{status}]")


if __name__ == "__main__":
    main()
