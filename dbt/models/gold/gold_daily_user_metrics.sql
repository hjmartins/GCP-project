{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['user_id', 'metric_date'],
        partition_by={'field': 'metric_date', 'data_type': 'date'},
        cluster_by=['user_id'],
        incremental_predicates=['DBT_INTERNAL_DEST.metric_date >= ' ~ window_start_date()],
    )
}}

-- Recalcula a janela inteira a cada execução: se chegar leitura atrasada, o dia afetado
-- é corrigido no MERGE.
with device_day as (
    select
        r.device_id,
        date(r.ts) as metric_date,
        sum(r.steps) as steps,
        sum(r.heart_rate) as hr_sum,
        count(r.heart_rate) as hr_count,
        min(r.heart_rate) as hr_min,
        max(r.heart_rate) as hr_max
    from {{ ref('silver_readings') }} as r
    where {{ incremental_ts_filter('r.ts') }}
    group by 1, 2
),

sleep as (
    select
        device_id,
        date(inicio) as metric_date,
        sum(duracao_min) as sleep_minutes
    from {{ ref('silver_sessions') }}
    where tipo = 'sono' and {{ incremental_ts_filter('inicio') }}
    group by 1, 2
)

-- Usuário com 2 dispositivos: passos e sono vêm do dispositivo com o maior valor no dia
-- (somar contaria a mesma caminhada duas vezes); a FC usa todas as leituras.
select
    d.user_id,
    dd.metric_date,
    max(dd.steps) as steps,
    round(sum(dd.hr_sum) / sum(dd.hr_count), 1) as hr_avg,
    min(dd.hr_min) as hr_min,
    max(dd.hr_max) as hr_max,
    coalesce(max(s.sleep_minutes), 0) as sleep_minutes,
    count(distinct dd.device_id) as devices_reporting
from device_day as dd
inner join {{ ref('silver_devices') }} as d using (device_id)
left join sleep as s using (device_id, metric_date)
group by 1, 2
