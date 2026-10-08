{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='session_id',
        partition_by={'field': 'inicio', 'data_type': 'timestamp', 'granularity': 'day'},
        cluster_by=['device_id'],
        incremental_predicates=['DBT_INTERNAL_DEST.inicio >= ' ~ window_start_ts()],
    )
}}

with batch as (
    select session_id, device_id, tipo, inicio, fim
    from {{ source('bronze', 'sessions') }}
    where session_id is not null
        and inicio >= {{ window_start_ts() }}
        and inicio < {{ run_date_end_ts() }}
)

select
    session_id,
    device_id,
    tipo,
    inicio,
    fim,
    timestamp_diff(fim, inicio, minute) as duracao_min,
    date('{{ var("run_date") }}') as batch_date,
    current_timestamp() as loaded_at
from batch
qualify row_number() over (partition by session_id order by inicio) = 1
