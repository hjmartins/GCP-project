"""Detecção de mudança de schema entre o staging (bronze) e a Silver.

Depois do load, o staging tem as colunas que vieram no Parquet do dia. Uma coluna que existe
no staging e ainda não existe na Silver é uma mudança de schema: o loader registra um evento
em silver.schema_events, e o dbt acrescenta a coluna na Silver como nullable
(on_schema_change='append_new_columns').
"""

from dataclasses import dataclass
from datetime import date

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from telemetry_loader.load import ENTITIES

EVENTS_TABLE = "schema_events"


@dataclass(frozen=True)
class SchemaChange:
    table_name: str
    column_name: str
    column_type: str


def new_columns(
    staging: list[bigquery.SchemaField], silver: list[bigquery.SchemaField]
) -> list[bigquery.SchemaField]:
    """Colunas do staging que a Silver ainda não tem (comparação sem diferenciar maiúsculas)."""
    known = {field.name.lower() for field in silver}
    return [field for field in staging if field.name.lower() not in known]


def detect_changes(
    client: bigquery.Client, staging_dataset: str, silver_dataset: str
) -> list[SchemaChange]:
    """Compara cada bronze.<entidade> com silver.silver_<entidade>.

    Se a tabela da Silver ainda não existe (primeira carga), não há com o que comparar.
    """
    changes = []
    for entity in ENTITIES:
        silver_name = f"silver_{entity}"
        try:
            silver = client.get_table(f"{client.project}.{silver_dataset}.{silver_name}").schema
        except NotFound:
            continue
        staging = client.get_table(f"{client.project}.{staging_dataset}.{entity}").schema
        changes += [
            SchemaChange(silver_name, field.name, field.field_type)
            for field in new_columns(staging, silver)
        ]
    return changes


# Só grava se o evento daquela coluna ainda não existe: reprocessar o dia (ou rodar de novo
# depois de uma falha do dbt) não duplica o registro.
_INSERT_EVENT = """
insert into `{table}` (detected_at, batch_date, table_name, column_name, column_type, change)
select current_timestamp(), @batch_date, @table_name, @column_name, @column_type, 'added'
from (select 1)
where not exists (
    select 1 from `{table}`
    where table_name = @table_name and column_name = @column_name
)
"""


def record_changes(
    client: bigquery.Client, silver_dataset: str, day: date, changes: list[SchemaChange]
) -> None:
    table = f"{client.project}.{silver_dataset}.{EVENTS_TABLE}"
    for change in changes:
        params = [
            bigquery.ScalarQueryParameter("batch_date", "DATE", day),
            bigquery.ScalarQueryParameter("table_name", "STRING", change.table_name),
            bigquery.ScalarQueryParameter("column_name", "STRING", change.column_name),
            bigquery.ScalarQueryParameter("column_type", "STRING", change.column_type),
        ]
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        client.query(_INSERT_EVENT.format(table=table), job_config=job_config).result()
