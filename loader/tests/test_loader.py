import json
from datetime import date
from pathlib import Path

from google.cloud import bigquery

from telemetry_loader.config import Config
from telemetry_loader.load import ENTITIES, job_config, source_uri
from telemetry_loader.main import dbt_args


def test_source_uri_matches_generator_layout():
    uri = source_uri("b", "readings", date(2026, 10, 1))
    assert uri == "gs://b/readings/dt=2026-10-01/*.parquet"


def test_staging_is_truncated_and_partitioned_for_facts():
    readings = job_config(ENTITIES["readings"])
    assert readings.write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE
    assert readings.source_format == bigquery.SourceFormat.PARQUET
    assert readings.time_partitioning.field == "ts"
    assert job_config(ENTITIES["users"]).time_partitioning is None


def test_config_from_env():
    config = Config.from_env(
        {
            "RUN_DATE": "2026-10-01",
            "GCP_PROJECT": "p",
            "BRONZE_BUCKET": "p-bronze",
            "DBT_DIR": "/app/dbt",
        }
    )
    assert config.run_date == date(2026, 10, 1)
    assert config.location == "us-central1"
    assert config.dbt_dir == Path("/app/dbt")


def test_default_dbt_dir_points_to_repo_project():
    assert (
        Config.from_env({"GCP_PROJECT": "p", "BRONZE_BUCKET": "b"}).dbt_dir / "dbt_project.yml"
    ).exists()


def test_dbt_receives_run_date():
    config = Config(run_date=date(2026, 10, 1), project_id="p", bronze_bucket="b")
    args = dbt_args(config)
    assert args[0] == "build"
    assert json.loads(args[args.index("--vars") + 1]) == {"run_date": "2026-10-01"}
