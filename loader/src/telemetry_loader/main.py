import json
import sys

from dbt.cli.main import dbtRunner
from google.cloud import bigquery

from telemetry_loader.config import Config
from telemetry_loader.load import load_day


def log(message: str, severity: str = "INFO", **fields) -> None:
    # JSON em uma linha: o Cloud Logging transforma em log estruturado.
    print(json.dumps({"severity": severity, "message": message, **fields}), flush=True)


def dbt_args(config: Config) -> list[str]:
    return [
        "build",
        "--project-dir",
        str(config.dbt_dir),
        "--profiles-dir",
        str(config.dbt_dir),
        "--vars",
        json.dumps({"run_date": config.run_date.isoformat()}),
    ]


def main() -> None:
    config = Config.from_env()
    log("carregando lote", run_date=config.run_date.isoformat())

    client = bigquery.Client(project=config.project_id, location=config.location)
    rows = load_day(client, config.bronze_bucket, config.staging_dataset, config.run_date)
    log("staging carregado", rows=rows)

    result = dbtRunner().invoke(dbt_args(config))
    if not result.success:
        log("dbt build falhou", severity="ERROR", run_date=config.run_date.isoformat())
        sys.exit(1)
    log("dbt build concluído", run_date=config.run_date.isoformat())


if __name__ == "__main__":
    main()
