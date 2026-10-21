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


def test_single_day_when_no_end_date():
    config = Config.from_env({"RUN_DATE": "2026-10-01"})
    assert config.dates() == [date(2026, 10, 1)]


def test_backfill_range_is_inclusive():
    config = Config.from_env({"START_DATE": "2026-01-01", "END_DATE": "2026-01-10"})
    dates = config.dates()
    assert dates[0] == date(2026, 1, 1) and dates[-1] == date(2026, 1, 10)
    assert len(dates) == 10


def test_tasks_split_the_range_without_gaps_or_overlap():
    env = {"START_DATE": "2025-10-21", "END_DATE": "2026-10-20", "CLOUD_RUN_TASK_COUNT": "4"}
    shards = [Config.from_env({**env, "CLOUD_RUN_TASK_INDEX": str(i)}).dates() for i in range(4)]
    all_dates = [d for shard in shards for d in shard]
    assert len(all_dates) == len(set(all_dates)) == 365
    assert max(len(s) for s in shards) - min(len(s) for s in shards) <= 1
