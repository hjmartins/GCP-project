import pyarrow as pa
import pyarrow.compute as pc
import pytest

from telemetry_gen.faults import ROW_FAULTS, inject_row_faults, set_values

from .conftest import DAY

RATE = 0.02


@pytest.fixture(scope="module")
def faulty(daily):
    return inject_row_faults(daily.readings, seed_base=42, day=DAY, fault_rate=RATE)


def test_rate_zero_changes_nothing(daily):
    readings, counts = inject_row_faults(daily.readings, seed_base=42, day=DAY, fault_rate=0)
    assert readings is daily.readings
    assert counts == {}


def test_injection_is_deterministic(daily, faulty):
    again = inject_row_faults(daily.readings, seed_base=42, day=DAY, fault_rate=RATE)
    assert again[0].equals(faulty[0])
    assert again[1] == faulty[1]


def test_every_fault_type_hits_the_expected_number_of_rows(daily, faulty):
    _, counts = faulty
    expected = round(daily.readings.num_rows * RATE)  # 1440
    assert set(counts) == set(ROW_FAULTS) | {"duplicate"}
    assert all(n == expected for n in counts.values())


def test_duplicates_are_exact_copies(daily, faulty):
    readings, counts = faulty
    assert readings.num_rows == daily.readings.num_rows + counts["duplicate"]
    # As cópias são idênticas à original em todas as colunas, não só na chave.
    columns = [readings[c].to_pylist() for c in readings.column_names]
    n_distinct_rows = len(set(zip(*columns, strict=True)))
    assert readings.num_rows - n_distinct_rows == counts["duplicate"]


def test_clean_data_does_not_depend_on_faults(daily, faulty):
    # Desligar a injeção não muda as leituras limpas: os erros têm seed própria.
    readings, _ = faulty
    assert readings.slice(0, 10)["device_id"].equals(daily.readings.slice(0, 10)["device_id"])


def test_rate_too_high_is_rejected(daily):
    # Os blocos de todos os tipos precisam caber nas linhas do dia.
    too_high = 1 / (len(ROW_FAULTS) + 1) + 0.01
    with pytest.raises(ValueError, match="alto demais"):
        inject_row_faults(daily.readings, seed_base=42, day=DAY, fault_rate=too_high)


def test_set_values_supports_nulls():
    table = pa.table({"x": pa.array([1, 2, 3], pa.int32())})
    out = set_values(table, "x", [0, 2], [None, 9])
    assert out["x"].to_pylist() == [None, 2, 9]
    assert out.schema == table.schema


def _count(mask) -> int:
    return pc.sum(pc.fill_null(mask, False)).as_py()


def test_out_of_range_breaks_exactly_the_dbt_ranges(faulty):
    readings, counts = faulty
    # Mesmas faixas dos testes do dbt (silver/schema.yml).
    bad_hr = pc.or_(pc.less(readings["heart_rate"], 30), pc.greater(readings["heart_rate"], 250))
    bad_spo2 = pc.greater(readings["spo2"], 100)
    assert _count(bad_hr) + _count(bad_spo2) == counts["out_of_range"]
    assert _count(pc.less(readings["heart_rate"], 0)) > 0
    assert _count(pc.greater(readings["heart_rate"], 250)) > 0


def test_null_key_splits_between_device_id_and_ts(faulty):
    readings, counts = faulty
    null_device = readings["device_id"].null_count
    null_ts = readings["ts"].null_count
    assert null_device + null_ts == counts["null_key"]
    assert null_device > 0 and null_ts > 0


def test_orphans_are_unique_and_outside_the_catalog(catalog, faulty):
    readings, counts = faulty
    known = pa.array(catalog.devices["device_id"].to_pylist())
    ids = readings["device_id"].drop_null()
    orphans = ids.filter(pc.invert(pc.is_in(ids, value_set=known)))
    assert len(orphans) == counts["orphan_device"]
    assert pc.count_distinct(orphans).as_py() == len(orphans)
