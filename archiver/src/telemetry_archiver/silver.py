"""Leitura da Silver pela BigQuery Storage Read API.

Ler pela Storage Read API não é uma consulta: não fatura bytes processados como um SELECT.
A lista de partições vem da API de metadados da tabela, também sem consulta.
"""

from datetime import date, timedelta

import pyarrow as pa
from google.cloud import bigquery
from google.cloud.bigquery_storage import BigQueryReadClient, types

COLUMNS = ["device_id", "ts", "heart_rate", "steps", "spo2", "battery", "skin_temp", "batch_date"]


def list_partition_ids(client: bigquery.Client, table: str) -> list[str]:
    return list(client.list_partitions(table))


def existing_columns(client: bigquery.Client, table: str) -> list[str]:
    """As colunas que a Silver tem hoje (skin_temp só existe depois da mudança de schema)."""
    names = {field.name for field in client.get_table(table).schema}
    return [c for c in COLUMNS if c in names]


def row_restriction(first: date, last: date) -> str:
    """Filtro de partição em ts, alinhado ao dia: [first 00:00, last+1 00:00)."""
    end = last + timedelta(days=1)
    return f"ts >= TIMESTAMP('{first.isoformat()}') AND ts < TIMESTAMP('{end.isoformat()}')"


def read_days(
    read_client: BigQueryReadClient,
    project: str,
    table_path: str,
    columns: list[str],
    first: date,
    last: date,
) -> pa.Table:
    """Lê as leituras de first..last (inclusive). table_path: projects/p/datasets/d/tables/t."""
    session = read_client.create_read_session(
        parent=f"projects/{project}",
        read_session=types.ReadSession(
            table=table_path,
            data_format=types.DataFormat.ARROW,
            read_options=types.ReadSession.TableReadOptions(
                selected_fields=columns, row_restriction=row_restriction(first, last)
            ),
        ),
        max_stream_count=1,
    )
    if not session.streams:
        return pa.table({c: pa.array([]) for c in columns})
    return read_client.read_rows(session.streams[0].name).to_arrow(session)
