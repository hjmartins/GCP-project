from datetime import date, timedelta

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from telemetry_gen.batch import build_batch
from telemetry_gen.faults import DROPOUT_DAYS, LATE_DAYS, silent_devices
from telemetry_gen.readings import generate_day

from .conftest import DAY

RATE = 0.02
SKIN_SINCE = date(2026, 11, 1)


def _batch(catalog, day, rate=RATE, since=SKIN_SINCE):
    return build_batch(catalog.devices, 42, day, rate, since)


def _keys(table: pa.Table) -> set[tuple]:
    ids, ts = table["device_id"].to_pylist(), table["ts"].to_pylist()
    return {(d, t) for d, t in zip(ids, ts, strict=True) if d is not None and t is not None}


def _dates(table: pa.Table) -> set[date]:
    return {t.date() for t in table["ts"].drop_null().to_pylist()}


@pytest.fixture(scope="module")
def batch(catalog):
    return _batch(catalog, DAY)


def test_rate_zero_is_the_clean_day(catalog, daily):
    clean = _batch(catalog, DAY, rate=0, since=None)
    assert clean.readings.equals(daily.readings)
    assert clean.sessions.equals(daily.sessions)
    assert clean.fault_counts == {}


def test_batch_is_deterministic(catalog, batch):
    again = _batch(catalog, DAY)
    assert again.readings.equals(batch.readings)
    assert again.sessions.equals(batch.sessions)
    assert again.fault_counts == batch.fault_counts


def test_late_readings_leave_today_and_arrive_three_days_later(catalog, daily, batch):
    arrival = _batch(catalog, DAY + timedelta(days=LATE_DAYS))
    late = arrival.readings.filter(
        pc.less(
            pc.cast(arrival.readings["ts"], pa.date32()),
            pa.scalar(DAY + timedelta(days=LATE_DAYS), pa.date32()),
        )
    )
    late_keys = _keys(late)

    assert len(late_keys) == arrival.fault_counts["late_arrival"] == 1440
    assert _dates(late) == {DAY}
    # Não estavam no lote do próprio dia, mas existem no dia limpo: chegaram atrasadas.
    assert late_keys.isdisjoint(_keys(batch.readings))
    assert late_keys <= _keys(daily.readings)


def test_silent_devices_send_nothing(catalog, batch):
    silent = silent_devices(catalog.devices["device_id"].to_pylist(), 42, DAY, RATE)
    assert len(silent) == batch.fault_counts["silent_devices"] > 0
    today = pc.equal(pc.cast(batch.readings["ts"], pa.date32()), pa.scalar(DAY, pa.date32()))
    reporting = set(batch.readings.filter(today)["device_id"].drop_null().to_pylist())
    assert silent.isdisjoint(reporting)
    assert silent.isdisjoint(batch.sessions["device_id"].to_pylist())


def test_dropout_lasts_several_days(catalog):
    ids = catalog.devices["device_id"].to_pylist()
    window = [silent_devices(ids, 42, DAY + timedelta(days=i), RATE) for i in range(30)]
    # Todo sumiço dura de 2 a 5 dias seguidos.
    for device in set().union(*window):
        flags = [device in day for day in window]
        runs, current = [], 0
        for flag in flags:
            if flag:
                current += 1
            elif current:
                runs.append(current)
                current = 0
        complete = runs[1:]  # o primeiro pode ter começado antes da janela
        assert all(DROPOUT_DAYS[0] <= r <= DROPOUT_DAYS[1] for r in complete)


def test_skin_temp_appears_from_the_configured_date(catalog):
    before = _batch(catalog, SKIN_SINCE - timedelta(days=1))
    after = _batch(catalog, SKIN_SINCE)
    assert "skin_temp" not in before.readings.column_names
    assert after.readings.column_names[-1] == "skin_temp"
    stats = pc.min_max(after.readings["skin_temp"])
    assert stats["min"].as_py() > 30 and stats["max"].as_py() < 37


def test_skin_temp_does_not_change_other_columns(catalog):
    with_col = _batch(catalog, SKIN_SINCE)
    without = _batch(catalog, SKIN_SINCE, since=None)
    assert with_col.readings.drop_columns(["skin_temp"]).equals(without.readings)


def test_row_faults_still_injected(batch):
    for name in ["out_of_range", "null_key", "orphan_device", "duplicate"]:
        assert batch.fault_counts[name] > 0


def test_clean_generation_untouched(catalog, daily):
    # Os erros têm seeds próprias: o dia limpo continua o mesmo de antes da Fase 5.
    assert generate_day(catalog.devices, 42, DAY).readings.equals(daily.readings)
