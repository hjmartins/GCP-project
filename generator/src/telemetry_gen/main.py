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
    """Gera um dia (config.run_date). Devolve o caminho gravado de cada entidade."""
    catalog = generate_catalog(config.seed_base, config.n_users)
    return _run_day(config, catalog, config.run_date)


def _run_day(config: Config, catalog, day) -> dict[str, str]:
    batch = build_batch(
        catalog.devices,
        config.seed_base,
        day,
        config.fault_rate,
        config.skin_temp_since,
    )
    log(
        "erros injetados",
        run_date=day.isoformat(),
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
        paths[entity] = write_table(table, config.output_uri, entity, day)
        log("tabela gravada", entity=entity, rows=table.num_rows, path=paths[entity])
    return paths


def main() -> None:
    config = Config.from_env()
    dates = config.dates()
    log(
        "gerando dias",
        first=dates[0].isoformat() if dates else None,
        last=dates[-1].isoformat() if dates else None,
        days=len(dates),
        task=f"{config.task_index + 1}/{config.task_count}",
        seed_base=config.seed_base,
        output_uri=config.output_uri,
        fault_rate=config.fault_rate,
        skin_temp_since=str(config.skin_temp_since),
    )
    catalog = generate_catalog(config.seed_base, config.n_users)
    for day in dates:
        _run_day(config, catalog, day)


if __name__ == "__main__":
    main()
