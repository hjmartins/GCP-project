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
    silver_dataset: str = "silver"
    dbt_dir: Path = DEFAULT_DBT_DIR
    # Backfill: carrega BACKFILL_START..RUN_DATE de uma vez e roda o dbt com --full-refresh.
    backfill_start: date | None = None

    @property
    def is_backfill(self) -> bool:
        return self.backfill_start is not None

    @property
    def lookback_days(self) -> int:
        """Janela do dbt. No backfill cobre o intervalo todo + os 3 dias de atraso (com folga)."""
        if self.backfill_start is None:
            return 7
        return (self.run_date - self.backfill_start).days + 7

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
            silver_dataset=env.get("SILVER_DATASET", cls.silver_dataset),
            dbt_dir=Path(env.get("DBT_DIR", DEFAULT_DBT_DIR)),
            backfill_start=(
                date.fromisoformat(env["BACKFILL_START"]) if env.get("BACKFILL_START") else None
            ),
        )
