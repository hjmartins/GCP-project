from datetime import UTC, date, datetime, timedelta

import pyarrow.parquet as pq

from telemetry_gen.config import Config
from telemetry_gen.main import run


def test_writes_bronze_layout(tmp_path):
    config = Config(run_date=date(2026, 10, 1), output_uri=str(tmp_path))
    paths = run(config)
    assert set(paths) == {"users", "devices", "sessions", "readings"}
    for entity in paths:
        files = list((tmp_path / entity / "dt=2026-10-01").iterdir())
        assert [f.name for f in files] == ["part-000.parquet"]


def test_rerun_overwrites_and_is_identical(tmp_path):
    config = Config(run_date=date(2026, 10, 1), output_uri=str(tmp_path))
    first = pq.read_table(run(config)["readings"])
    second = pq.read_table(run(config)["readings"])
    assert first.equals(second)
    assert len(list((tmp_path / "readings").rglob("*.parquet"))) == 1


def test_config_from_env():
    config = Config.from_env(
        {"RUN_DATE": "2026-01-31", "SEED_BASE": "7", "OUTPUT_URI": "gs://b", "N_USERS": "10"}
    )
    assert config == Config(
        run_date=date(2026, 1, 31), seed_base=7, output_uri="gs://b", n_users=10
    )


def test_config_defaults_to_yesterday():
    config = Config.from_env({})
    assert config.run_date == datetime.now(UTC).date() - timedelta(days=1)
    assert config.seed_base == 42
