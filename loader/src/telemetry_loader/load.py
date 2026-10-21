"""Load jobs do Bronze (Parquet no GCS) para as tabelas de staging `bronze.<entidade>`.

Por que load job e não tabela externa: load jobs do BigQuery não cobram bytes processados,
e consultar uma tabela externa cobra. O staging guarda só o lote do dia (WRITE_TRUNCATE).
"""

from datetime import date, timedelta

from google.cloud import bigquery

# Cadastro vem completo todo dia: no backfill basta o último dia (carregar todos duplicaria).
SNAPSHOT_ENTITIES = {"users", "devices"}

# Coluna de partição diária do staging. Cadastro (users, devices) é pequeno e não é particionado.
ENTITIES: dict[str, str | None] = {
    "users": None,
    "devices": None,
    "sessions": "inicio",
    "readings": "ts",
}


def source_uri(bucket: str, entity: str, day: date) -> str:
    return f"gs://{bucket}/{entity}/dt={day.isoformat()}/*.parquet"


def job_config(partition_field: str | None) -> bigquery.LoadJobConfig:
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    if partition_field:
        config.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY, field=partition_field
        )
    return config


def source_uris(bucket: str, entity: str, start: date, end: date) -> list[str]:
    """Um curinga por dia do intervalo; cadastro só do último dia."""
    if entity in SNAPSHOT_ENTITIES:
        return [source_uri(bucket, entity, end)]
    days = (end - start).days + 1
    return [source_uri(bucket, entity, start + timedelta(days=i)) for i in range(days)]


def load_range(
    client: bigquery.Client, bucket: str, dataset: str, start: date, end: date
) -> dict[str, int]:
    """Carrega as 4 entidades de start..end (um load job por entidade, gratuito) e devolve o
    número de linhas de cada uma. Dia a dia, start == end."""
    jobs = {
        entity: client.load_table_from_uri(
            source_uris(bucket, entity, start, end),
            f"{client.project}.{dataset}.{entity}",
            job_config=job_config(partition_field),
        )
        for entity, partition_field in ENTITIES.items()
    }
    return {entity: job.result().output_rows for entity, job in jobs.items()}
