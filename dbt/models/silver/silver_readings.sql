{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['device_id', 'ts'],
        partition_by={'field': 'ts', 'data_type': 'timestamp', 'granularity': 'day'},
        cluster_by=['device_id'],
        require_partition_filter=true,
        incremental_predicates=['DBT_INTERNAL_DEST.ts >= ' ~ window_start_ts()],
        on_schema_change='append_new_columns',
    )
}}

-- select * except: leva todas as colunas do checked, inclusive skin_temp quando existir no lote.
-- Exceção à regra de evitar select *: a origem é um ephemeral com colunas já explícitas.
select
    * except (quarantine_reason),
    date('{{ var("run_date") }}') as batch_date,
    current_timestamp() as loaded_at
from {{ref('silver_readings_checked')}}
WHERE quarantine_reason is null
-- Duplicatas de (device_id, ts) dentro do lote: mantém uma. O MERGE falha se duas linhas
-- da origem casarem com a mesma linha do destino.
qualify row_number() over (partition by device_id, ts order by ts) = 1
