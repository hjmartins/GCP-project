"""Cadastro sintético: usuários e dispositivos.

Depende só da seed base, então é idêntico em todos os dias gerados.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pyarrow as pa

from telemetry_gen.seeds import catalog_rng

AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
AGE_WEIGHTS = [0.14, 0.27, 0.24, 0.17, 0.11, 0.07]
MODELS = ["Pulse S1", "Pulse S2", "Pulse Pro", "FitBand 3"]
FIRMWARES = ["2.1.0", "2.2.1", "2.3.0", "3.0.0"]
# Lista fixa em vez de Faker: cidades reais agrupam bem no painel, e a saída do Faker
# pode mudar entre versões da biblioteca (quebraria o determinismo).
CITIES = {
    "São Paulo": 0.22,
    "Rio de Janeiro": 0.13,
    "Belo Horizonte": 0.08,
    "Brasília": 0.08,
    "Curitiba": 0.07,
    "Porto Alegre": 0.07,
    "Salvador": 0.07,
    "Recife": 0.06,
    "Fortaleza": 0.06,
    "Campinas": 0.05,
    "Florianópolis": 0.04,
    "Goiânia": 0.04,
    "Manaus": 0.03,
}

# Cadastros em 2024: todo o histórico gerado (backfill de 12 meses) já tem usuários ativos.
SIGNUP_START = date(2024, 1, 1)
SIGNUP_DAYS = 366
MAX_ACTIVATION_DELAY_DAYS = 30
DEVICES_PER_USER = 1.25

USERS_SCHEMA = pa.schema(
    [
        ("user_id", pa.string()),
        ("faixa_etaria", pa.string()),
        ("cidade", pa.string()),
        ("data_cadastro", pa.date32()),
    ]
)

DEVICES_SCHEMA = pa.schema(
    [
        ("device_id", pa.string()),
        ("user_id", pa.string()),
        ("modelo", pa.string()),
        ("firmware", pa.string()),
        ("ativado_em", pa.date32()),
    ]
)


@dataclass(frozen=True)
class Catalog:
    users: pa.Table
    devices: pa.Table


def generate_catalog(seed_base: int, n_users: int) -> Catalog:
    rng = catalog_rng(seed_base)

    user_ids = np.array([f"U{i:05d}" for i in range(1, n_users + 1)])
    signup_offsets = rng.integers(0, SIGNUP_DAYS, n_users)
    signup_dates = [SIGNUP_START + timedelta(days=int(d)) for d in signup_offsets]
    users = pa.table(
        {
            "user_id": user_ids,
            "faixa_etaria": rng.choice(AGE_BANDS, n_users, p=AGE_WEIGHTS),
            "cidade": rng.choice(list(CITIES), n_users, p=list(CITIES.values())),
            "data_cadastro": signup_dates,
        },
        schema=USERS_SCHEMA,
    )

    # Todo usuário tem um dispositivo; uma parte tem um segundo.
    n_extra = round(n_users * (DEVICES_PER_USER - 1))
    owner_idx = np.concatenate(
        [np.arange(n_users), np.sort(rng.choice(n_users, n_extra, replace=False))]
    )
    n_devices = len(owner_idx)
    activation_delay = rng.integers(0, MAX_ACTIVATION_DELAY_DAYS, n_devices)
    devices = pa.table(
        {
            "device_id": [f"D{i:05d}" for i in range(1, n_devices + 1)],
            "user_id": user_ids[owner_idx],
            "modelo": rng.choice(MODELS, n_devices),
            "firmware": rng.choice(FIRMWARES, n_devices),
            "ativado_em": [
                signup_dates[u] + timedelta(days=int(d))
                for u, d in zip(owner_idx, activation_delay, strict=True)
            ],
        },
        schema=DEVICES_SCHEMA,
    )
    return Catalog(users=users, devices=devices)
