"""Tabela Iceberg da camada fria, escrita com PyIceberg.

- Partição por dia de ts: consultas com filtro de data leem só os arquivos daqueles dias.
- Escrita idempotente: cada lote SUBSTITUI os dias que traz (overwrite com filtro), então rodar
  o mesmo lote de novo não duplica nada.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import pyarrow as pa
import pyarrow.fs as pafs
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

# Cada commit gera um metadata.json novo; sem limite, eles se acumulam para sempre. O Iceberg
# apaga os mais antigos sozinho, guardando os últimos N (folga para a tabela externa do
# BigQuery, que aponta para um metadata.json específico até o archiver recriá-la).
TABLE_PROPERTIES = {
    "write.metadata.delete-after-commit.enabled": "true",
    "write.metadata.previous-versions-max": "50",
}


def open_catalog(sqlite_path: str, warehouse: str) -> SqlCatalog:
    """Catálogo SQLite local (o arquivo é baixado/devolvido ao bucket por catalog_sync)."""
    return SqlCatalog(NAMESPACE, uri=f"sqlite:///{sqlite_path}", warehouse=warehouse)


def ensure_table(catalog: Catalog, name: str, location: str) -> Table:
    catalog.create_namespace_if_not_exists(NAMESPACE)
    table = catalog.create_table_if_not_exists(
        (NAMESPACE, name),
        schema=SCHEMA,
        partition_spec=PARTITION_SPEC,
        location=location,
        properties=TABLE_PROPERTIES,
    )
    # Tabelas criadas antes desta configuração recebem as propriedades agora.
    missing = {k: v for k, v in TABLE_PROPERTIES.items() if table.properties.get(k) != v}
    if missing:
        with table.transaction() as tx:
            tx.set_properties(**missing)
    return table


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


@dataclass(frozen=True)
class CleanupResult:
    snapshots_before: int
    snapshots_after: int
    files_deleted: int
    bytes_freed: int


def expire_and_remove_orphans(
    table: Table, keep_days: int, now: datetime, min_file_age: timedelta = timedelta(hours=1)
) -> CleanupResult:
    """Apaga versões (snapshots) com mais de keep_days e os arquivos de dados que nenhuma versão
    restante usa.

    O expire_snapshots do PyIceberg só tira as versões dos metadados: os arquivos continuam no
    bucket (e sendo cobrados). Por isso a segunda etapa compara os arquivos da pasta data/ com os
    referenciados (inspect.all_files) e apaga a diferença. min_file_age protege arquivos que
    acabaram de ser gravados e ainda não entraram num commit.
    """
    before = len(table.metadata.snapshots)
    table.maintenance.expire_snapshots().older_than(now - timedelta(days=keep_days)).commit()
    table = table.refresh()

    referenced = {_strip_scheme(p) for p in table.inspect.all_files()["file_path"].to_pylist()}
    fs, data_root = pafs.FileSystem.from_uri(f"{table.location()}/data")
    files = fs.get_file_info(pafs.FileSelector(data_root, recursive=True, allow_not_found=True))

    deleted = freed = 0
    for info in files:
        if info.type != pafs.FileType.File or _strip_scheme(info.path) in referenced:
            continue
        if info.mtime is not None and now - info.mtime < min_file_age:
            continue
        fs.delete_file(info.path)
        deleted += 1
        freed += info.size or 0
    return CleanupResult(before, len(table.metadata.snapshots), deleted, freed)


def _strip_scheme(path: str) -> str:
    """'gs://b/x' e 'b/x' (como o pyarrow lista) viram o mesmo caminho."""
    return path.split("://", 1)[-1]
