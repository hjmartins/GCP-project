import json
import sys

from telemetry_gen.config import Config
from telemetry_gen.entities import generate_catalog
from telemetry_gen.readings import generate_day
from telemetry_gen.storage import write_table


def log(message: str, **fields) -> None:
    # JSON em uma linha: o Cloud Logging transforma em log estruturado.
    print(json.dumps({"severity": "INFO", "message": message, **fields}), file=sys.stdout)


def run(config: Config) -> dict[str, str]:
    catalog = generate_catalog(config.seed_base, config.n_users)
    daily = generate_day(catalog.devices, config.seed_base, config.run_date)
    tables = {
        "users": catalog.users,
        "devices": catalog.devices,
        "sessions": daily.sessions,
        "readings": daily.readings,
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
    )
    run(config)


if __name__ == "__main__":
    main()
