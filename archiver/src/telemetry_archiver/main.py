"""Archiver diário: Silver com mais de ARCHIVE_AFTER_DAYS dias → Iceberg no bucket frio.

1. Lista as partições da Silver anteriores ao corte (metadados, sem consulta).
2. Para cada lote de dias: lê pela Storage Read API, grava no Iceberg (substituindo os dias)
   e confere que o Iceberg tem exatamente as linhas lidas.
3. Devolve o catálogo ao bucket.
4. Recria a tabela externa cold.<tabela> apontando para o metadata.json novo (sql/).
5. Só então apaga esses dias da Silver (sql/). Se algo falhar antes, a Silver fica intacta e
   a próxima execução refaz os lotes (a escrita é idempotente).
"""

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from google.cloud import bigquery, storage
from google.cloud.bigquery_storage import BigQueryReadClient

from telemetry_archiver import bq_sql, catalog_sync, iceberg_store, plan, silver
from telemetry_archiver.config import Config


def log(message: str, severity: str = "INFO", **fields) -> None:
    print(json.dumps({"severity": severity, "message": message, **fields}, default=str), flush=True)


class ArchiveMismatch(RuntimeError):
    """O Iceberg não tem as mesmas linhas que foram lidas da Silver: não apagar nada."""


def run(config: Config) -> None:
    silver_table = f"{config.project_id}.{config.silver_dataset}.{config.silver_table}"
    bq = bigquery.Client(project=config.project_id, location=config.location)

    days = plan.dates_to_archive(silver.list_partition_ids(bq, silver_table), config.cutoff)
    log("arquivando", run_date=config.run_date, cutoff=config.cutoff, days=len(days))
    if not days:
        log("nada a arquivar")
        return

    gcs = storage.Client(project=config.project_id)
    read_client = BigQueryReadClient()
    table_path = (
        f"projects/{config.project_id}/datasets/{config.silver_dataset}"
        f"/tables/{config.silver_table}"
    )
    columns = silver.existing_columns(bq, silver_table)
    archived_at = datetime.now(UTC)

    with tempfile.TemporaryDirectory() as tmp:
        catalog_path = Path(tmp) / "catalog.db"
        generation = catalog_sync.download(
            gcs, config.cold_bucket, config.catalog_object, catalog_path
        )
        catalog = iceberg_store.open_catalog(str(catalog_path), f"gs://{config.cold_bucket}")
        table = iceberg_store.ensure_table(
            catalog, config.cold_table, f"gs://{config.cold_bucket}/{config.cold_table}"
        )

        total = 0
        for chunk in plan.chunks(days, config.chunk_days):
            first, last = chunk[0], chunk[-1]
            rows = silver.read_days(
                read_client, config.project_id, table_path, columns, first, last
            )
            iceberg_store.write_days(
                table, iceberg_store.to_iceberg_arrow(rows, archived_at), first, last
            )
            in_iceberg = iceberg_store.count_days(table, first, last)
            if in_iceberg != rows.num_rows:
                raise ArchiveMismatch(
                    f"{first}..{last}: silver={rows.num_rows} iceberg={in_iceberg}"
                )
            total += rows.num_rows
            log("lote arquivado", first=first, last=last, rows=rows.num_rows)

        catalog_sync.upload(
            gcs, config.cold_bucket, config.catalog_object, catalog_path, generation
        )
        metadata_uri = table.metadata_location

    identifiers = {
        "project": config.project_id,
        "cold_dataset": config.cold_dataset,
        "cold_table": config.cold_table,
        "connection": config.connection,
        "metadata_uri": metadata_uri,
        "silver_dataset": config.silver_dataset,
        "silver_table": config.silver_table,
    }
    bq_sql.run(bq, bq_sql.render("refresh_external_table.sql", **identifiers))
    log("tabela externa atualizada", metadata_uri=metadata_uri)

    job = bq_sql.run(bq, bq_sql.render("delete_archived.sql", **identifiers), cutoff=config.cutoff)
    log(
        "silver limpa",
        deleted_rows=job.num_dml_affected_rows,
        bytes_billed=job.total_bytes_billed,
        archived_rows=total,
    )


def main() -> None:
    try:
        run(Config.from_env())
    except Exception as exc:  # log estruturado antes de sair com erro (o workflow pega o exit 1)
        log("archiver falhou", severity="ERROR", error=repr(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
