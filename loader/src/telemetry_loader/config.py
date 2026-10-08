import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

DEFAULT_DBT_DIR = Path(__file__).resolve().parents[3] / "dbt"


@dataclass(frozen=True)
class Config:
    run_date: date
    project_id: str
    bronze_bucket: str
    location: str = "us-central1"
    staging_dataset: str = "bronze"
    dbt_dir: Path = DEFAULT_DBT_DIR

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        """Sem RUN_DATE, processa o dia anterior (UTC), igual ao gerador."""
        raw_date = env.get("RUN_DATE")
        run_date = (
            date.fromisoformat(raw_date)
            if raw_date
            else datetime.now(UTC).date() - timedelta(days=1)
        )
        return cls(
            run_date=run_date,
            project_id=env["GCP_PROJECT"],
            bronze_bucket=env["BRONZE_BUCKET"],
            location=env.get("BQ_LOCATION", cls.location),
            staging_dataset=env.get("STAGING_DATASET", cls.staging_dataset),
            dbt_dir=Path(env.get("DBT_DIR", DEFAULT_DBT_DIR)),
        )
