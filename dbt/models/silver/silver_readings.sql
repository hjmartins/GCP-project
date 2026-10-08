{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['device_id', 'ts'],
        partition_by={'field': 'ts', 'data_type': 'timestamp', 'granularity': 'day'},
        cluster_by=['device_id'],
        require_partition_filter=true,
        incremental_predicates=['DBT_INTERNAL_DEST.ts >= ' ~ window_start_ts()],
    )
}}

-- O MERGE só lê as partições da janela no destino (incremental_predicates), não a tabela toda.
-- Linhas com chave nula ou fora da janela ficam de fora; a Fase 5 manda essas para a quarentena.
with batch as (
    select device_id, ts, heart_rate, steps, spo2, battery
    from {{ source('bronze', 'readings') }}
    where device_id is not null
        and ts >= {{ window_start_ts() }}
        and ts < {{ run_date_end_ts() }}
)

select
    device_id,
    ts,
    heart_rate,
    steps,
    spo2,
    battery,
    date('{{ var("run_date") }}') as batch_date,
    current_timestamp() as loaded_at
from batch
-- Duplicatas de (device_id, ts) dentro do lote: mantém uma. O MERGE falha se duas linhas
-- da origem casarem com a mesma linha do destino.
qualify row_number() over (partition by device_id, ts order by ts) = 1
