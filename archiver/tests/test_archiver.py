from datetime import UTC, date, datetime, timedelta

import pyarrow as pa
import pytest

from telemetry_archiver import bq_sql, iceberg_store, plan, silver
from telemetry_archiver.config import Config

ARCHIVED_AT = datetime(2026, 10, 22, tzinfo=UTC)


def _silver_rows(
    first: date, days: int, per_day: int = 3, with_skin_temp: bool = False
) -> pa.Table:
    ts, ids = [], []
    for d in range(days):
        midnight = datetime.combine(first + timedelta(days=d), datetime.min.time(), tzinfo=UTC)
        for i in range(per_day):
            ts.append(midnight + timedelta(minutes=5 * i))
            ids.append(f"D{i:05d}")
    n = len(ts)
    data = {
        "device_id": pa.array(ids),
        "ts": pa.array(ts, pa.timestamp("us", tz="UTC")),
        "heart_rate": pa.array([70] * n, pa.int64()),
        "steps": pa.array([10] * n, pa.int64()),
        "spo2": pa.array([97] * n, pa.int64()),
        "battery": pa.array([80] * n, pa.int64()),
        "batch_date": pa.array([first] * n, pa.date32()),
    }
    if with_skin_temp:
        data["skin_temp"] = pa.array([33.5] * n)
    return pa.table(data)


# --- config e plano -------------------------------------------------------------------


def test_cutoff_keeps_last_90_days_in_silver():
    config = Config(run_date=date(2026, 10, 21), project_id="p", cold_bucket="b")
    assert config.cutoff == date(2026, 7, 23)
    assert config.connection == "p.us-central1.biglake"


def test_only_partitions_before_cutoff_are_archived():
    ids = ["20260720", "20260722", "20260723", "20260801", "__NULL__"]
    assert plan.dates_to_archive(ids, date(2026, 7, 23)) == [date(2026, 7, 20), date(2026, 7, 22)]


def test_chunks_cover_all_days_in_order():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(16)]
    chunks = plan.chunks(days, 7)
    assert [len(c) for c in chunks] == [7, 7, 2]
    assert [d for c in chunks for d in c] == days


def test_row_restriction_is_day_aligned():
    assert silver.row_restriction(date(2026, 1, 1), date(2026, 1, 7)) == (
        "ts >= TIMESTAMP('2026-01-01') AND ts < TIMESTAMP('2026-01-08')"
    )


# --- alinhamento ao schema Iceberg ------------------------------------------------------


def test_missing_skin_temp_becomes_null_column():
    out = iceberg_store.to_iceberg_arrow(_silver_rows(date(2026, 1, 1), 1), ARCHIVED_AT)
    assert out.schema == iceberg_store.SCHEMA.as_arrow()
    assert out["skin_temp"].null_count == out.num_rows
    assert set(out["archived_at"].to_pylist()) == {ARCHIVED_AT}


def test_existing_skin_temp_is_kept():
    rows = _silver_rows(date(2026, 1, 1), 1, with_skin_temp=True)
    out = iceberg_store.to_iceberg_arrow(rows, ARCHIVED_AT)
    assert out["skin_temp"].to_pylist() == [33.5] * rows.num_rows


# --- Iceberg de verdade, em disco local -------------------------------------------------


@pytest.fixture
def table(tmp_path):
    catalog = iceberg_store.open_catalog(str(tmp_path / "catalog.db"), f"file://{tmp_path}")
    return iceberg_store.ensure_table(catalog, "readings", f"file://{tmp_path}/readings")


def _write(table, first: date, days: int, per_day: int = 3) -> None:
    rows = iceberg_store.to_iceberg_arrow(_silver_rows(first, days, per_day), ARCHIVED_AT)
    last = first + timedelta(days=days - 1)
    iceberg_store.write_days(table, rows, first, last)


def test_write_and_count(table):
    _write(table, date(2026, 1, 1), days=7)
    assert iceberg_store.count_days(table, date(2026, 1, 1), date(2026, 1, 7)) == 21
    assert iceberg_store.count_days(table, date(2026, 1, 1), date(2026, 1, 1)) == 3


def test_rewriting_the_same_days_does_not_duplicate(table):
    _write(table, date(2026, 1, 1), days=7)
    _write(table, date(2026, 1, 1), days=7)
    assert iceberg_store.count_days(table, date(2026, 1, 1), date(2026, 1, 7)) == 21


def test_overwrite_only_touches_its_own_days(table):
    _write(table, date(2026, 1, 1), days=7)
    _write(table, date(2026, 1, 8), days=7, per_day=5)
    _write(table, date(2026, 1, 8), days=7, per_day=2)  # refaz só o segundo lote
    assert iceberg_store.count_days(table, date(2026, 1, 1), date(2026, 1, 7)) == 21
    assert iceberg_store.count_days(table, date(2026, 1, 8), date(2026, 1, 14)) == 14


def test_table_is_partitioned_by_day(table):
    _write(table, date(2026, 1, 1), days=3)
    assert table.spec().fields[0].name == "ts_day"
    files = list(table.scan().plan_files())
    assert len(files) == 3  # um arquivo por dia


# --- os SQLs (escritos à parte em archiver/sql/) -----------------------------------------

IDENTIFIERS = {
    "project": "proj",
    "cold_dataset": "cold",
    "cold_table": "readings",
    "connection": "proj.us-central1.biglake",
    "metadata_uri": "gs://bucket/readings/metadata/00001-abc.metadata.json",
    "silver_dataset": "silver",
    "silver_table": "silver_readings",
}


def _code(sql: str) -> str:
    """O SQL sem os comentários, em minúsculas."""
    lines = [line.split("--")[0] for line in sql.splitlines()]
    return " ".join(" ".join(lines).split()).lower()


def test_refresh_sql_points_external_iceberg_table_to_new_metadata():
    sql = _code(bq_sql.render("refresh_external_table.sql", **IDENTIFIERS))
    assert "create or replace external table `proj.cold.readings`" in sql
    assert "with connection `proj.us-central1.biglake`" in sql
    assert "'iceberg'" in sql
    assert IDENTIFIERS["metadata_uri"] in sql


def test_delete_sql_removes_only_rows_before_cutoff():
    sql = _code(bq_sql.render("delete_archived.sql", **IDENTIFIERS))
    assert sql.startswith("delete from `proj.silver.silver_readings`")
    assert "@cutoff" in sql
    assert "ts <" in sql


def test_rehearsal_overrides_point_away_from_production():
    config = Config.from_env(
        {
            "GCP_PROJECT": "p",
            "COLD_BUCKET": "b",
            "SILVER_TABLE": "silver_readings_archtest",
            "COLD_TABLE": "readings_test",
            "CATALOG_OBJECT": "catalog/test.db",
        }
    )
    assert (config.silver_table, config.cold_table, config.catalog_object) == (
        "silver_readings_archtest",
        "readings_test",
        "catalog/test.db",
    )
    defaults = Config.from_env({"GCP_PROJECT": "p", "COLD_BUCKET": "b"})
    assert (defaults.silver_table, defaults.cold_table) == ("silver_readings", "readings")
