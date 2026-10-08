from datetime import UTC, date, datetime, timedelta

import pyarrow as pa
import pyarrow.compute as pc

from telemetry_gen.readings import SLOTS_PER_DAY, generate_day

from .conftest import DAY


def _min_max(column):
    stats = pc.min_max(column)
    return stats["min"].as_py(), stats["max"].as_py()


def test_same_day_is_identical(catalog, daily):
    again = generate_day(catalog.devices, seed_base=42, day=DAY)
    assert daily.readings.equals(again.readings)
    assert daily.sessions.equals(again.sessions)


def test_different_day_changes_data(catalog, daily):
    other = generate_day(catalog.devices, seed_base=42, day=DAY + timedelta(days=1))
    assert not daily.readings["heart_rate"].equals(other.readings["heart_rate"])


def test_one_reading_per_device_every_five_minutes(catalog, daily):
    readings = daily.readings
    assert readings.num_rows == catalog.devices.num_rows * SLOTS_PER_DAY == 72_000
    keys = pc.binary_join_element_wise(
        readings["device_id"], pc.cast(readings["ts"], pa.string()), "|"
    )
    assert pc.count_distinct(keys).as_py() == readings.num_rows


def test_timestamps_are_utc_micros_within_the_day(daily):
    ts_type = daily.readings.schema.field("ts").type
    assert ts_type == pa.timestamp("us", tz="UTC")
    start = datetime(2026, 10, 1, tzinfo=UTC)
    first, last = _min_max(daily.readings["ts"])
    assert first == start
    assert last == start + timedelta(days=1) - timedelta(minutes=5)


def test_values_within_physiological_ranges(daily):
    r = daily.readings
    hr_min, hr_max = _min_max(r["heart_rate"])
    assert hr_min >= 30 and hr_max <= 220
    spo2_min, spo2_max = _min_max(r["spo2"])
    assert spo2_min >= 85 and spo2_max <= 100
    battery_min, battery_max = _min_max(r["battery"])
    assert battery_min >= 0 and battery_max <= 100
    assert _min_max(r["steps"])[0] >= 0


def test_sleep_has_lower_heart_rate_and_no_steps(daily):
    # Entre 00:00 e 05:30 todo mundo está dormindo.
    r = daily.readings
    night = pc.less(r["ts"], pa.scalar(datetime(2026, 10, 1, 5, 30, tzinfo=UTC), r["ts"].type))
    asleep, rest = r.filter(night), r.filter(pc.invert(night))
    assert _min_max(asleep["steps"]) == (0, 0)
    assert pc.mean(asleep["heart_rate"]).as_py() < pc.mean(rest["heart_rate"]).as_py()


def test_sessions(catalog, daily):
    s = daily.sessions
    assert pc.count_distinct(s["session_id"]).as_py() == s.num_rows
    assert set(s["tipo"].to_pylist()) == {"sono", "dia", "treino"}
    # Sono e dia para todo dispositivo; treino em parte deles (~3 sessões/dispositivo).
    per_device = s.num_rows / catalog.devices.num_rows
    assert 2 < per_device <= 3
    assert pc.all(pc.less(s["inicio"], s["fim"])).as_py()
    devices = set(catalog.devices["device_id"].to_pylist())
    assert set(s["device_id"].to_pylist()) == devices


def test_devices_not_yet_activated_are_skipped(catalog):
    early = generate_day(catalog.devices, seed_base=42, day=date(2024, 3, 1))
    activated = pc.sum(
        pc.less_equal(catalog.devices["ativado_em"], pa.scalar(date(2024, 3, 1), pa.date32()))
    ).as_py()
    assert 0 < activated < catalog.devices.num_rows
    assert early.readings.num_rows == activated * SLOTS_PER_DAY
