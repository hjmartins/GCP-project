"""Dados diários: sessões e leituras a cada 5 minutos.

Tudo é vetorizado em matrizes (dispositivo x slot de 5 min); nada de loop por linha,
para o backfill de 12 meses (~26 milhões de leituras) rodar em segundos.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from telemetry_gen.seeds import daily_rng

INTERVAL_MIN = 5
SLOTS_PER_DAY = 24 * 60 // INTERVAL_MIN  # 288

# Rotina diária, em slots de 5 min.
WAKE_SLOTS = (66, 91)  # acorda entre 05:30 e 07:30
WORKOUT_START_SLOTS = (204, 240)  # treino começa entre 17:00 e 20:00
WORKOUT_LEN_SLOTS = (9, 19)  # 45 a 90 min
WORKOUT_PROBABILITY = 0.7

# Bateria: gasto por slot em cada estado; recarrega até 100 ao chegar em 15.
BATTERY_DRAIN = {"sono": 0.12, "dia": 0.3, "treino": 0.9}
BATTERY_RECHARGE_AT = 15

TS_TYPE = pa.timestamp("us", tz="UTC")

SESSIONS_SCHEMA = pa.schema(
    [
        ("session_id", pa.string()),
        ("device_id", pa.string()),
        ("tipo", pa.string()),
        ("inicio", TS_TYPE),
        ("fim", TS_TYPE),
    ]
)

READINGS_SCHEMA = pa.schema(
    [
        ("device_id", pa.string()),
        ("ts", TS_TYPE),
        ("heart_rate", pa.int32()),
        ("steps", pa.int32()),
        ("spo2", pa.int32()),
        ("battery", pa.int32()),
    ]
)


@dataclass(frozen=True)
class DailyData:
    sessions: pa.Table
    readings: pa.Table


def generate_day(devices: pa.Table, seed_base: int, day: date) -> DailyData:
    rng = daily_rng(seed_base, day)
    active = devices.filter(pc.less_equal(devices["ativado_em"], pa.scalar(day, pa.date32())))
    device_ids = np.array(active["device_id"].to_pylist(), dtype=object)
    n = len(device_ids)

    wake = rng.integers(*WAKE_SLOTS, n)
    has_workout = rng.random(n) < WORKOUT_PROBABILITY
    workout_start = rng.integers(*WORKOUT_START_SLOTS, n)
    workout_end = workout_start + rng.integers(*WORKOUT_LEN_SLOTS, n)

    slots = np.arange(SLOTS_PER_DAY)
    asleep = slots < wake[:, None]
    working_out = (
        has_workout[:, None] & (slots >= workout_start[:, None]) & (slots < workout_end[:, None])
    )
    awake = ~asleep & ~working_out

    midnight = np.datetime64(day.isoformat(), "us")
    step = np.timedelta64(INTERVAL_MIN, "m")

    sessions = _sessions(
        device_ids, day, midnight, step, wake, has_workout, workout_start, workout_end
    )
    readings = _readings(rng, device_ids, midnight, step, slots, asleep, working_out, awake)
    return DailyData(sessions=sessions, readings=readings)


def _sessions(device_ids, day, midnight, step, wake, has_workout, workout_start, workout_end):
    """Sono da meia-noite até acordar, 'dia' de acordar até meia-noite e, em alguns dias,
    um treino aninhado dentro do período 'dia'."""
    day_end = SLOTS_PER_DAY
    ymd = day.strftime("%Y%m%d")
    w = has_workout
    parts = [
        ("sono", device_ids, np.zeros_like(wake), wake),
        ("dia", device_ids, wake, np.full_like(wake, day_end)),
        ("treino", device_ids[w], workout_start[w], workout_end[w]),
    ]
    ids, tipos, devs, starts, ends = [], [], [], [], []
    for tipo, devs_part, start, end in parts:
        ids.append([f"{d}-{ymd}-{tipo}" for d in devs_part])
        tipos.append(np.full(len(devs_part), tipo, dtype=object))
        devs.append(devs_part)
        starts.append(midnight + start * step)
        ends.append(midnight + end * step)

    table = pa.table(
        {
            "session_id": np.concatenate(ids),
            "device_id": np.concatenate(devs),
            "tipo": np.concatenate(tipos),
            "inicio": pa.array(np.concatenate(starts)).cast(TS_TYPE),
            "fim": pa.array(np.concatenate(ends)).cast(TS_TYPE),
        },
        schema=SESSIONS_SCHEMA,
    )
    return table.sort_by([("device_id", "ascending"), ("inicio", "ascending")])


def _readings(rng, device_ids, midnight, step, slots, asleep, working_out, awake):
    n = len(device_ids)
    shape = (n, SLOTS_PER_DAY)

    resting_hr = rng.normal(64, 6, n)[:, None]
    workout_hr = rng.uniform(125, 165, n)[:, None]
    heart_rate = np.select(
        [asleep, working_out], [resting_hr - 8, workout_hr], default=resting_hr + 18
    ) + rng.normal(0, 4, shape)

    steps = rng.poisson(np.select([asleep, working_out], [0.0, 650.0], default=45.0))

    spo2 = np.where(asleep, rng.normal(95.5, 1.2, shape), rng.normal(97.5, 1.0, shape))

    drain = np.select(
        [asleep, working_out, awake],
        [BATTERY_DRAIN["sono"], BATTERY_DRAIN["treino"], BATTERY_DRAIN["dia"]],
    )
    start_level = rng.uniform(55, 100, n)[:, None]
    usable = 100 - BATTERY_RECHARGE_AT
    # Ao chegar no limite, recarrega até 100 e volta a descer (o módulo faz o "serrote").
    battery = BATTERY_RECHARGE_AT + np.mod(
        start_level - BATTERY_RECHARGE_AT - np.cumsum(drain, axis=1), usable
    )

    ts = midnight + slots * step
    return pa.table(
        {
            "device_id": np.repeat(device_ids, SLOTS_PER_DAY),
            "ts": pa.array(np.tile(ts, n)).cast(TS_TYPE),
            "heart_rate": np.clip(np.rint(heart_rate), 35, 210).astype(np.int32).ravel(),
            "steps": steps.astype(np.int32).ravel(),
            "spo2": np.clip(np.rint(spo2), 88, 100).astype(np.int32).ravel(),
            "battery": np.floor(battery).astype(np.int32).ravel(),
        },
        schema=READINGS_SCHEMA,
    )
