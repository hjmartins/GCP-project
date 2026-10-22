import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


@dataclass(frozen=True)
class Config:
    run_date: date
    project_id: str
    cold_bucket: str
    location: str = "us-central1"
    silver_dataset: str = "silver"
    silver_table: str = "silver_readings"
    cold_dataset: str = "cold"
    cold_table: str = "readings"
    connection_id: str = "biglake"
    # Leituras com mais de N dias saem da Silver e vão para o Iceberg.
    archive_after_days: int = 90
    # Dias por lote: limita a memória (~460 mil leituras por lote de 7 dias).
    chunk_days: int = 7
    # Objeto do catálogo Iceberg (SQLite) no bucket frio.
    catalog_object: str = "catalog/iceberg_catalog.db"

    @property
    def cutoff(self) -> date:
        """Primeiro dia que fica na Silver; tudo antes dele é arquivado."""
        return self.run_date - timedelta(days=self.archive_after_days)

    @property
    def connection(self) -> str:
        """Formato do WITH CONNECTION no SQL: projeto.região.conexão."""
        return f"{self.project_id}.{self.location}.{self.connection_id}"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        """Sem RUN_DATE, usa o dia anterior (UTC), igual ao gerador e ao loader."""
        raw_date = env.get("RUN_DATE")
        run_date = (
            date.fromisoformat(raw_date)
            if raw_date
            else datetime.now(UTC).date() - timedelta(days=1)
        )
        return cls(
            run_date=run_date,
            project_id=env["GCP_PROJECT"],
            cold_bucket=env["COLD_BUCKET"],
            location=env.get("BQ_LOCATION", cls.location),
            archive_after_days=int(env.get("ARCHIVE_AFTER_DAYS", cls.archive_after_days)),
            chunk_days=int(env.get("CHUNK_DAYS", cls.chunk_days)),
            # Sobrescritas usadas em ensaios: apontar para cópias, sem tocar em produção.
            silver_table=env.get("SILVER_TABLE", cls.silver_table),
            cold_table=env.get("COLD_TABLE", cls.cold_table),
            catalog_object=env.get("CATALOG_OBJECT", cls.catalog_object),
        )
