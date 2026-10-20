{{
    config(
        materialized='incremental',
        incremental_strategy='insert_overwrite',
        partition_by={'field': 'batch_date', 'data_type': 'date'},
        partitions=["date('" ~ var('run_date') ~ "')"],
    )
}}

-- Uma linha por verificação de qualidade por lote. Reprocessar o dia substitui a partição.
--
-- Cada verificação é uma CTE com as mesmas 5 colunas:
--   check_name, severity ('blocking' | 'warning'), rows_evaluated, rows_failed, threshold
-- threshold: fração máxima tolerada (bloqueantes). Avisos usam 0: qualquer falha vira 'warn'.
-- O status é calculado no select final, igual para todas.
--
-- Bloqueantes param a publicação da Gold de negócio: ver tests/assert_no_blocking_quality_failures.sql.

{% set run_date = "date('" ~ var('run_date') ~ "')" %}

with batch as (
    select device_id, ts
    from {{ source('bronze', 'readings') }}
),

quarantine as (
    select quarantine_reason
    from {{ ref('silver_readings_quarantine') }}
    where batch_date = {{ run_date }}
),

-- Duplicata: linhas com chave completa além da primeira de cada (device_id, ts).
duplicate_readings as (
    select
        'duplicate_readings' as check_name,
        'blocking' as severity,
        countif(device_id is not null and ts is not null) as rows_evaluated,
        countif(device_id is not null and ts is not null)
            - count(distinct if(
                device_id is not null and ts is not null,
                concat(device_id, '|', cast(ts as string)),
                null
            )) as rows_failed,
        0.05 as threshold
    from batch
),

-- Chave nula: contada na quarentena (motivo null_key), sobre o total do lote.
null_key as (
    select
        'null_key' as check_name,
        'blocking' as severity,
        (select count(*) from batch) as rows_evaluated,
        countif(quarantine_reason = 'null_key') as rows_failed,
        0.05 as threshold
    from quarantine
),

-- Mudança de schema: eventos registrados pelo loader neste lote.
schema_change as (
    select
        'schema_change' as check_name,
        'warning' as severity,
        cast(null as int64) as rows_evaluated,
        count(*) as rows_failed,
        0.0 as threshold
    from {{ source('silver', 'schema_events') }}
    where batch_date = {{ run_date }}
),

-- Motivos de quarentena que não bloqueiam: viram aviso no painel.
{% for reason in ['out_of_range', 'orphan_device', 'out_of_window'] %}
{{ reason }} as (
    select
        '{{ reason }}' as check_name,
        'warning' as severity,
        (select count(*) from batch) as rows_evaluated,
        countif(quarantine_reason = '{{ reason }}') as rows_failed,
        0.0 as threshold
    from quarantine
),
{% endfor %}

-- Chegada atrasada: leituras válidas deste lote cujo ts é de um dia anterior ao lote.
-- Não é erro do dado (a janela de 7 dias reprocessa o dia), mas vale acompanhar.
late_arrival as (
    select
        'late_arrival' as check_name,
        'warning' as severity,
        count(*) as rows_evaluated,
        countif(ts < timestamp({{ run_date }})) as rows_failed,
        0.0 as threshold
    from {{ ref('silver_readings') }}
    where ts >= {{ window_start_ts() }}
        and batch_date = {{ run_date }}
),

-- Dispositivo sumido: ativo na data, mas sem nenhuma leitura com ts no dia.
silent_devices as (
    select
        'silent_devices' as check_name,
        'warning' as severity,
        count(*) as rows_evaluated,
        countif(r.device_id is null) as rows_failed,
        0.0 as threshold
    from {{ ref('silver_devices') }} as d
    left join (
        select device_id
        from {{ ref('silver_readings') }}
        where ts >= timestamp({{ run_date }})
            and ts < {{ run_date_end_ts() }}
        group by device_id
    ) as r
        on d.device_id = r.device_id
    where d.ativado_em <= {{ run_date }}
),

checks as (
    select * from duplicate_readings
    union all select * from null_key
    union all select * from schema_change
    union all select * from out_of_range
    union all select * from orphan_device
    union all select * from out_of_window
    union all select * from late_arrival
    union all select * from silent_devices
)

select
    {{ run_date }} as batch_date,
    check_name,
    severity,
    rows_evaluated,
    rows_failed,
    round(safe_divide(rows_failed, rows_evaluated), 4) as failure_rate,
    threshold,
    case
        when severity = 'blocking'
            and safe_divide(rows_failed, rows_evaluated) > threshold then 'fail'
        when severity = 'warning' and rows_failed > 0 then 'warn'
        else 'pass'
    end as status,
    current_timestamp() as checked_at
from checks
