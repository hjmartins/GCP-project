"""Monta o lote do dia: dados limpos + todos os erros injetados.

Ordem:
1. Gera o dia limpo e tira os dispositivos sumidos (sem leituras nem sessões).
2. Separa as leituras atrasadas do dia: elas saem do lote de hoje.
3. Aplica os erros por linha (duplicata, fora da faixa, nulo, órfão).
4. Acrescenta as leituras atrasadas de 3 dias atrás, recalculadas com os passos 1 e 2 para
   aquela data. Ficam limpas: são leituras válidas, só que fora de hora.
5. A partir de skin_temp_since, acrescenta a coluna skin_temp (mudança de schema).
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pyarrow as pa

from telemetry_gen.faults import (
    LATE_DAYS,
    add_skin_temp,
    drop_devices,
    inject_row_faults,
    late_rows,
    silent_devices,
)
from telemetry_gen.readings import generate_day


@dataclass(frozen=True)
class DailyBatch:
    sessions: pa.Table
    readings: pa.Table
    fault_counts: dict[str, int]


def _on_time_and_late(
    devices: pa.Table, seed_base: int, day: date, fault_rate: float
) -> tuple[pa.Table, pa.Table, pa.Table, set[str]]:
    """Dia limpo sem os dispositivos sumidos, dividido em leituras no prazo e atrasadas."""
    daily = generate_day(devices, seed_base, day)
    device_ids = daily.readings["device_id"].unique().to_pylist()
    silent = silent_devices(device_ids, seed_base, day, fault_rate)
    readings = drop_devices(daily.readings, silent)
    sessions = drop_devices(daily.sessions, silent)

    late_idx = late_rows(readings, seed_base, day, fault_rate)
    on_time_mask = np.ones(readings.num_rows, dtype=bool)
    on_time_mask[late_idx] = False
    late = readings.take(pa.array(late_idx, pa.int64()))
    return readings.filter(pa.array(on_time_mask)), late, sessions, silent


def build_batch(
    devices: pa.Table,
    seed_base: int,
    day: date,
    fault_rate: float,
    skin_temp_since: date | None,
) -> DailyBatch:
    if fault_rate > 0:
        readings, _, sessions, silent = _on_time_and_late(devices, seed_base, day, fault_rate)
        readings, counts = inject_row_faults(readings, seed_base, day, fault_rate)
        _, late, _, _ = _on_time_and_late(
            devices, seed_base, day - timedelta(days=LATE_DAYS), fault_rate
        )
        readings = pa.concat_tables([readings, late])
        counts |= {"late_arrival": late.num_rows, "silent_devices": len(silent)}
    else:
        daily = generate_day(devices, seed_base, day)
        readings, sessions, counts = daily.readings, daily.sessions, {}

    if skin_temp_since is not None and day >= skin_temp_since:
        readings = add_skin_temp(readings, seed_base, day)
    return DailyBatch(sessions=sessions, readings=readings, fault_counts=counts)
