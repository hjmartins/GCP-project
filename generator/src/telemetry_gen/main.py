import json
import sys

from telemetry_gen.batch import build_batch
from telemetry_gen.config import Config
from telemetry_gen.entities import generate_catalog
from telemetry_gen.storage import write_table


def log(message: str, **fields) -> None:
    # JSON em uma linha: o Cloud Logging transforma em log estruturado.
    print(json.dumps({"severity": "INFO", "message": message, **fields}), file=sys.stdout)


def run(config: Config) -> dict[str, str]:
    catalog = generate_catalog(config.seed_base, config.n_users)
    batch = build_batch(
        catalog.devices,
        config.seed_base,
        config.run_date,
        config.fault_rate,
        config.skin_temp_since,
    )
    log(
        "erros injetados",
        fault_rate=config.fault_rate,
        counts=batch.fault_counts,
        readings_columns=batch.readings.column_names,
    )
    tables = {
        "users": catalog.users,
        "devices": catalog.devices,
        "sessions": batch.sessions,
        "readings": batch.readings,
    }
    paths = {}
    for entity, table in tables.items():
        paths[entity] = write_table(table, config.output_uri, entity, config.run_date)
        log("tabela gravada", entity=entity, rows=table.num_rows, path=paths[entity])
    return paths


def main() -> None:
    config = Config.from_env()
    log(
        "gerando dia",
        run_date=config.run_date.isoformat(),
        seed_base=config.seed_base,
        output_uri=config.output_uri,
        fault_rate=config.fault_rate,
        skin_temp_since=str(config.skin_temp_since),
    )
    run(config)


if __name__ == "__main__":
    main()
