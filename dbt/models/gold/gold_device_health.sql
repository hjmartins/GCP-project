{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['device_id', 'metric_date'],
        partition_by={'field': 'metric_date', 'data_type': 'date'},
        cluster_by=['device_id'],
        incremental_predicates=['DBT_INTERNAL_DEST.metric_date >= ' ~ window_start_date()],
    )
}}

{% set readings_per_day = 288 %}

with daily as (
    select
        device_id,
        date(ts) as metric_date,
        count(*) as readings_count,
        avg(battery) as battery_avg,
        min(battery) as battery_min,
        max(ts) as last_reading_at
    from {{ ref('silver_readings') }}
    where {{ incremental_ts_filter('ts') }}
    group by 1, 2
),

-- Grade dispositivo x dia: um dispositivo que parou de enviar aparece com 0 leituras,
-- em vez de simplesmente sumir da tabela.
dates as (
    select metric_date
    from unnest(generate_date_array(
        (select min(metric_date) from daily),
        date('{{ var("run_date") }}')
    )) as metric_date
),

spine as (
    select d.device_id, d.user_id, d.modelo, d.firmware, dates.metric_date
    from {{ ref('silver_devices') }} as d
    cross join dates
    where d.ativado_em <= dates.metric_date
)

select
    spine.device_id,
    spine.metric_date,
    spine.user_id,
    spine.modelo,
    spine.firmware,
    coalesce(daily.readings_count, 0) as readings_count,
    round(coalesce(daily.readings_count, 0) / {{ readings_per_day }}, 3) as completeness,
    round(daily.battery_avg, 1) as battery_avg,
    daily.battery_min,
    daily.last_reading_at,
    coalesce(daily.readings_count, 0) > 0 as has_signal
from spine
left join daily using (device_id, metric_date)
