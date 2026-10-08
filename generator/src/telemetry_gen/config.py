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
        )
