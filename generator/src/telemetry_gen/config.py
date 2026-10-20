import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


@dataclass(frozen=True)
class Config:
    run_date: date
    seed_base: int = 42
    output_uri: str = "./data"
    n_users: int = 200
    # Fração das leituras afetada por cada tipo de erro injetado (Fase 5). 0 desliga.
    fault_rate: float = 0.02
    # A partir desta data as leituras trazem a coluna skin_temp (mudança de schema).
    # SKIN_TEMP_SINCE vazio desliga.
    skin_temp_since: date | None = date(2026, 11, 1)

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        """Lê a configuração das variáveis de ambiente.

        Sem RUN_DATE, gera o dia anterior (UTC): o pipeline diário processa o dia fechado.
        """
        raw_date = env.get("RUN_DATE")
        run_date = (
            date.fromisoformat(raw_date)
            if raw_date
            else datetime.now(UTC).date() - timedelta(days=1)
        )
        return cls(
            run_date=run_date,
            seed_base=int(env.get("SEED_BASE", cls.seed_base)),
            output_uri=env.get("OUTPUT_URI", cls.output_uri),
            n_users=int(env.get("N_USERS", cls.n_users)),
            fault_rate=float(env.get("FAULT_RATE", cls.fault_rate)),
            skin_temp_since=_optional_date(env.get("SKIN_TEMP_SINCE"), cls.skin_temp_since),
        )


def _optional_date(raw: str | None, default: date | None) -> date | None:
    if raw is None:
        return default
    return date.fromisoformat(raw) if raw else None
