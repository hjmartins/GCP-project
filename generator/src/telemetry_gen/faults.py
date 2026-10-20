"""Injeção de erros conhecidos nas leituras (Fase 5).

O pipeline precisa detectar cada erro injetado aqui; é isso que prova que os testes funcionam.

Como funciona:
- Cada tipo de erro afeta round(linhas * fault_rate) leituras do dia.
- As linhas são sorteadas com a seed de erros (seeds.faults_rng): o mesmo (seed_base, dia,
  fault_rate) estraga sempre as mesmas linhas.
- Os tipos recebem blocos disjuntos de uma única permutação das linhas: uma leitura nunca
  sofre dois erros ao mesmo tempo, então a contagem de cada tipo é exata.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from telemetry_gen.readings import SLOTS_PER_DAY
from telemetry_gen.seeds import dropout_rng, faults_rng, late_rng, skin_temp_rng

# Um erro por linha recebe a tabela, os índices sorteados para ele e o gerador aleatório,
# e devolve a tabela alterada. Erros que acrescentam linhas (duplicata) não entram aqui.
RowFault = Callable[[pa.Table, np.ndarray, np.random.Generator], pa.Table]


def inject_row_faults(
    readings: pa.Table, seed_base: int, day: date, fault_rate: float
) -> tuple[pa.Table, dict[str, int]]:
    """Aplica os erros por linha e devolve a tabela estragada + quantas linhas cada erro afetou."""
    if fault_rate <= 0:
        return readings, {}

    rng = faults_rng(seed_base, day)
    k = round(readings.num_rows * fault_rate)
    n_types = len(ROW_FAULTS) + 1  # +1: o bloco da duplicata
    if k * n_types > readings.num_rows:
        raise ValueError(f"fault_rate {fault_rate} alto demais para {n_types} tipos de erro")

    perm = rng.permutation(readings.num_rows)
    blocks = [np.sort(perm[i * k : (i + 1) * k]) for i in range(n_types)]

    counts: dict[str, int] = {}
    for (name, fault), idx in zip(ROW_FAULTS.items(), blocks, strict=False):
        readings = fault(readings, idx, rng)
        counts[name] = len(idx)

    # Duplicata por último: as cópias vêm de um bloco que nenhum outro erro tocou,
    # então são cópias exatas de leituras válidas.
    readings = duplicate_rows(readings, blocks[-1])
    counts["duplicate"] = len(blocks[-1])
    return readings, counts


def duplicate_rows(table: pa.Table, idx: np.ndarray) -> pa.Table:
    """Reenvia as mesmas leituras: (device_id, ts) repetido, com os mesmos valores.

    Detectado por: MERGE na Silver (dedup) + teste de unicidade de (device_id, ts).
    """
    return pa.concat_tables([table, table.take(pa.array(idx))])


def set_values(table: pa.Table, column: str, idx: np.ndarray, values: Sequence) -> pa.Table:
    """Troca os valores de `column` nas linhas `idx`. Um valor None vira nulo.

    Ajuda para escrever os erros por linha sem mexer em Arrow diretamente.
    """
    data = table[column].to_pylist()
    for i, value in zip(idx, values, strict=True):
        data[i] = value
    position = table.schema.get_field_index(column)
    field = table.schema.field(position)
    return table.set_column(position, field, pa.array(data, type=field.type))


# --- Erros por linha --------------------------------------------------------------


def out_of_range(table: pa.Table, idx: np.ndarray, rng: np.random.Generator) -> pa.Table:
    """Metade com heart_rate impossível (negativo ou > 250), metade com spo2 > 100.

    Detectado por: teste de faixa (accepted_range) → quarentena.
    """
    half = len(idx) // 2
    hr_idx, spo2_idx = idx[:half], idx[half:]

    negative = rng.random(len(hr_idx)) < 0.5
    hr_values = np.where(
        negative, -rng.integers(1, 50, len(hr_idx)), rng.integers(251, 300, len(hr_idx))
    )
    table = set_values(table, "heart_rate", hr_idx, [int(v) for v in hr_values])

    spo2_values = rng.integers(101, 111, len(spo2_idx))
    return set_values(table, "spo2", spo2_idx, [int(v) for v in spo2_values])


def null_key(table: pa.Table, idx: np.ndarray, rng: np.random.Generator) -> pa.Table:
    """Metade com device_id nulo, metade com ts nulo.

    Detectado por: not_null → quarentena. (Não usa sorteio; o rng fica pela assinatura comum.)
    """
    half = len(idx) // 2
    table = set_values(table, "device_id", idx[:half], [None] * half)
    return set_values(table, "ts", idx[half:], [None] * (len(idx) - half))


def orphan_device(table: pa.Table, idx: np.ndarray, rng: np.random.Generator) -> pa.Table:
    """device_id que não existe no cadastro (D9xxxx; o cadastro vai de D00001 a D00250).

    Um id diferente por linha: com um id fixo (ex.: "D99999"), duas leituras órfãs no mesmo
    horário virariam também uma chave duplicada, misturando dois tipos de erro.
    Detectado por: relationships com silver_devices → quarentena.
    """
    orphan_ids = [f"D9{i:04d}" for i in range(len(idx))]
    return set_values(table, "device_id", idx, orphan_ids)


ROW_FAULTS: dict[str, RowFault] = {
    "out_of_range": out_of_range,
    "null_key": null_key,
    "orphan_device": orphan_device,
}


# --- Erros no tempo -----------------------------------------------------------------
#
# O gerador não guarda estado: cada dia sai só de (seed_base, data). Por isso um erro que
# envolve vários dias é recalculado a partir das datas envolvidas, nunca "lembrado".

LATE_DAYS = 3
# Um dispositivo atrasado perde a sincronização da tarde/noite: as últimas 12 h do dia.
LATE_WINDOW_SLOTS = SLOTS_PER_DAY // 2
DROPOUT_DAYS = (2, 5)  # um dispositivo sumido fica de 2 a 5 dias sem enviar nada


def late_rows(readings: pa.Table, seed_base: int, day: date, fault_rate: float) -> np.ndarray:
    """Índices das leituras do dia `day` que só vão chegar em `day + LATE_DAYS`.

    Sorteia round(linhas * fault_rate / 144) dispositivos e pega as últimas 12 h de cada um
    (1440 linhas com 72 mil leituras e 2%). Pressupõe a tabela limpa de generate_day, em que
    cada dispositivo ocupa um bloco contínuo de 288 linhas.
    Detectado por: data do ts anterior à data do lote; a janela de 7 dias reprocessa o dia.
    """
    n_devices = readings.num_rows // SLOTS_PER_DAY
    n_late = min(n_devices, round(readings.num_rows * fault_rate / LATE_WINDOW_SLOTS))
    if n_late == 0:
        return np.array([], dtype=np.int64)
    positions = np.sort(late_rng(seed_base, day).choice(n_devices, n_late, replace=False))
    window = np.arange(SLOTS_PER_DAY - LATE_WINDOW_SLOTS, SLOTS_PER_DAY)
    return (positions[:, None] * SLOTS_PER_DAY + window).ravel()


def silent_devices(device_ids: list[str], seed_base: int, day: date, fault_rate: float) -> set[str]:
    """Dispositivos que não enviam nada em `day`.

    Todo dia começam round(n * fault_rate / 4) sumiços (1 com 250 dispositivos e 2%), cada um
    com duração de 2 a 5 dias. Para saber se um dispositivo está sumido hoje, basta olhar os
    sumiços que começaram nos últimos 5 dias, sem estado guardado.
    Detectado por: gold_device_health.has_signal = false.
    """
    starts_per_day = round(len(device_ids) * fault_rate / 4)
    if starts_per_day == 0:
        return set()
    silent = set()
    for back in range(DROPOUT_DAYS[1]):
        start = day - timedelta(days=back)
        rng = dropout_rng(seed_base, start)
        chosen = rng.choice(len(device_ids), starts_per_day, replace=False)
        durations = rng.integers(DROPOUT_DAYS[0], DROPOUT_DAYS[1] + 1, starts_per_day)
        silent.update(device_ids[i] for i, d in zip(chosen, durations, strict=True) if back < d)
    return silent


def add_skin_temp(readings: pa.Table, seed_base: int, day: date) -> pa.Table:
    """Mudança de schema: firmware novo passa a enviar a temperatura da pele (°C).

    Detectado por: comparação de schema no loader (coluna nova aceita como nullable).
    """
    rng = skin_temp_rng(seed_base, day)
    values = np.round(rng.normal(33.5, 0.6, readings.num_rows), 1)
    return readings.append_column(pa.field("skin_temp", pa.float64()), pa.array(values))


def drop_devices(table: pa.Table, devices: set[str]) -> pa.Table:
    if not devices:
        return table
    return table.filter(pc.invert(pc.is_in(table["device_id"], value_set=pa.array(list(devices)))))
