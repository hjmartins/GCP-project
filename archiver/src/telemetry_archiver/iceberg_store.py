"""Tabela Iceberg da camada fria, escrita com PyIceberg.

- Partição por dia de ts: consultas com filtro de data leem só os arquivos daqueles dias.
- Escrita idempotente: cada lote SUBSTITUI os dias que traz (overwrite com filtro), então rodar
  o mesmo lote de novo não duplica nada.
"""

from datetime import UTC, date, datetime, time, timedelta

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.expressions import And, GreaterThanOrEqual, LessThan
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import DayTransform
from pyiceberg.types import (
    DateType,
    DoubleType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

NAMESPACE = "cold"

SCHEMA = Schema(
    NestedField(1, "device_id", StringType(), required=False),
    NestedField(2, "ts", TimestamptzType(), required=False),
    NestedField(3, "heart_rate", LongType(), required=False),
    NestedField(4, "steps", LongType(), required=False),
    NestedField(5, "spo2", LongType(), required=False),
    NestedField(6, "battery", LongType(), required=False),
    NestedField(7, "skin_temp", DoubleType(), required=False),
    NestedField(8, "batch_date", DateType(), required=False),
    NestedField(9, "archived_at", TimestamptzType(), required=False),
)

PARTITION_SPEC = PartitionSpec(
    PartitionField(source_id=2, field_id=1000, transform=DayTransform(), name="ts_day")
)


def open_catalog(sqlite_path: str, warehouse: str) -> SqlCatalog:
    """Catálogo SQLite local (o arquivo é baixado/devolvido ao bucket por catalog_sync)."""
    return SqlCatalog(NAMESPACE, uri=f"sqlite:///{sqlite_path}", warehouse=warehouse)


def ensure_table(catalog: Catalog, name: str, location: str) -> Table:
    catalog.create_namespace_if_not_exists(NAMESPACE)
    return catalog.create_table_if_not_exists(
        (NAMESPACE, name), schema=SCHEMA, partition_spec=PARTITION_SPEC, location=location
    )


def to_iceberg_arrow(rows: pa.Table, archived_at: datetime) -> pa.Table:
    """Alinha as colunas lidas da Silver ao schema Iceberg: mesma ordem e tipos, colunas que
    ainda não existiam na Silver (ex.: skin_temp antes da mudança de schema) viram nulas."""
    target = SCHEMA.as_arrow()
    columns = []
    for field in target:
        if field.name == "archived_at":
            column = pa.array([archived_at] * rows.num_rows, type=field.type)
        elif field.name in rows.column_names:
            column = rows[field.name].cast(field.type)
        else:
            column = pa.nulls(rows.num_rows, type=field.type)
        columns.append(column)
    return pa.Table.from_arrays(columns, schema=target)


def _day_bounds(first: date, last: date) -> tuple[str, str]:
    start = datetime.combine(first, time(), tzinfo=UTC)
    end = datetime.combine(last + timedelta(days=1), time(), tzinfo=UTC)
    return start.isoformat(), end.isoformat()


def days_filter(first: date, last: date):
    start, end = _day_bounds(first, last)
    return And(GreaterThanOrEqual("ts", start), LessThan("ts", end))


def write_days(table: Table, rows: pa.Table, first: date, last: date) -> None:
    """Substitui os dias first..last no Iceberg pelas linhas recebidas (idempotente)."""
    table.overwrite(rows, overwrite_filter=days_filter(first, last))


def count_days(table: Table, first: date, last: date) -> int:
    """Linhas do Iceberg em first..last, contadas pelos metadados dos arquivos (sem ler dados)."""
    tasks = table.scan(row_filter=days_filter(first, last)).plan_files()
    return sum(task.file.record_count for task in tasks)
