from google.cloud import bigquery

from telemetry_loader.schema import new_columns

BASE = [
    bigquery.SchemaField("device_id", "STRING"),
    bigquery.SchemaField("ts", "TIMESTAMP"),
    bigquery.SchemaField("heart_rate", "INTEGER"),
]


def test_no_change_when_staging_matches_silver():
    assert new_columns(BASE, BASE) == []


def test_new_staging_column_is_reported():
    staging = [*BASE, bigquery.SchemaField("skin_temp", "FLOAT")]
    assert [f.name for f in new_columns(staging, BASE)] == ["skin_temp"]


def test_silver_only_columns_are_not_a_change():
    # batch_date e loaded_at são criadas pelo dbt; não vêm do lote e não são mudança de schema.
    silver = [*BASE, bigquery.SchemaField("batch_date", "DATE")]
    assert new_columns(BASE, silver) == []


def test_comparison_ignores_case():
    staging = [bigquery.SchemaField("Heart_Rate", "INTEGER"), *BASE[:2]]
    assert new_columns(staging, BASE) == []
