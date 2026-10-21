import json
import sys

from dbt.cli.main import dbtRunner
from google.cloud import bigquery

from telemetry_loader.config import Config
from telemetry_loader.load import load_range
from telemetry_loader.schema import detect_changes, record_changes


def log(message: str, severity: str = "INFO", **fields) -> None:
    # JSON em uma linha: o Cloud Logging transforma em log estruturado.
    print(json.dumps({"severity": severity, "message": message, **fields}), flush=True)


def dbt_args(config: Config) -> list[str]:
    dbt_vars = {"run_date": config.run_date.isoformat(), "lookback_days": config.lookback_days}
    args = [
        "build",
        "--project-dir",
        str(config.dbt_dir),
        "--profiles-dir",
        str(config.dbt_dir),
        "--vars",
        json.dumps(dbt_vars),
    ]
    # Backfill recria Silver e Gold do zero com o histórico inteiro.
    return [*args, "--full-refresh"] if config.is_backfill else args


def main() -> None:
    config = Config.from_env()
    start = config.backfill_start or config.run_date
    log(
        "carregando lote",
        start=start.isoformat(),
        run_date=config.run_date.isoformat(),
        backfill=config.is_backfill,
    )

    client = bigquery.Client(project=config.project_id, location=config.location)
    rows = load_range(client, config.bronze_bucket, config.staging_dataset, start, config.run_date)
    log("staging carregado", rows=rows)

    changes = detect_changes(client, config.staging_dataset, config.silver_dataset)
    if changes:
        record_changes(client, config.silver_dataset, config.run_date, changes)
        log(
            "mudança de schema detectada",
            severity="WARNING",
            event="schema_change",
            run_date=config.run_date.isoformat(),
            columns=[f"{c.table_name}.{c.column_name} ({c.column_type})" for c in changes],
        )

    result = dbtRunner().invoke(dbt_args(config))
    if not result.success:
        log("dbt build falhou", severity="ERROR", run_date=config.run_date.isoformat())
        sys.exit(1)
    log("dbt build concluído", run_date=config.run_date.isoformat())


if __name__ == "__main__":
    main()
