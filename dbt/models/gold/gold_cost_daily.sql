{{
    config(
        materialized='incremental',
        incremental_strategy='insert_overwrite',
        partition_by={'field': 'cost_date', 'data_type': 'date'},
        partitions=["date('" ~ var('run_date') ~ "')"],
    )
}}

-- Custo do projeto por dia, em formato longo: uma linha por (dia, categoria, componente, métrica).
-- Base do painel de FinOps. Reprocessar o dia substitui a partição.
--
--   category   'query' | 'storage'
--   component  query: 'pipeline' ou 'manual'   storage: o dataset (bronze, silver, gold)
--   unit       'bytes' | 'count' | 'usd'
--
-- O custo estimado ignora o free tier (mostra quanto custaria fora dele), com os preços
-- on-demand de us-central1 da Cloud Billing Catalog API (finops/experiments.md): US$ 6,25 por
-- TiB consultado; storage lógico US$ 0,023/GiB/mês ativo e US$ 0,016/GiB/mês long-term (dado
-- sem alteração há 90 dias).

{% set run_date = "date('" ~ var('run_date') ~ "')" %}
{% set region = 'region-' ~ target.location %}
{% set datasets = ['bronze', 'silver', 'gold'] %}

-- Consultas do dia, por origem. A conta do pipeline precisa de bigquery.jobs.listAll para ler
-- as consultas de todo o projeto (papel customizado em infra/main.tf).
with queries_agg as (
    select
        if(starts_with(user_email, 'pipeline-runner'), 'pipeline', 'manual') as component,
        cast(count(*) as float64) as queries,
        cast(sum(total_bytes_processed) as float64) as bytes_processed,
        cast(sum(total_bytes_billed) as float64) as bytes_billed,
        sum(total_bytes_billed) / pow(2, 40) * 6.25 as estimated_cost
    from `{{ target.project }}`.`{{ region }}`.INFORMATION_SCHEMA.JOBS
    where job_type = 'QUERY'
        and state = 'DONE'
        and date(creation_time) = {{ run_date }}
    group by component
),

queries_long as (
    select
        'query' as category,
        component,
        metric,
        coalesce(value, 0) as value,
        case metric
            when 'queries' then 'count'
            when 'estimated_cost' then 'usd'
            else 'bytes'
        end as unit
    from queries_agg
    unpivot include nulls (value for metric in (queries, bytes_processed, bytes_billed, estimated_cost))
),

-- Storage lógico por camada no momento da execução (fotografia do dia), separando o que é
-- cobrado como ativo do que já virou long-term.
{% for dataset in datasets %}
storage_{{ dataset }} as (
    select
        '{{ dataset }}' as component,
        cast(coalesce(sum(if(storage_tier = 'ACTIVE', total_logical_bytes, 0)), 0) as float64)
            as active_logical_bytes,
        cast(coalesce(sum(if(storage_tier = 'LONG_TERM', total_logical_bytes, 0)), 0) as float64)
            as long_term_logical_bytes
    from `{{ target.project }}`.{{ dataset }}.INFORMATION_SCHEMA.PARTITIONS
),
{% endfor %}

storage_agg as (
    select
        *,
        active_logical_bytes / pow(2, 30) * 0.023
            + long_term_logical_bytes / pow(2, 30) * 0.016 as estimated_monthly_cost
    from (
        {% for dataset in datasets %}
        select * from storage_{{ dataset }}
        {% if not loop.last %}union all{% endif %}
        {% endfor %}
    )
),

storage_long as (
    select
        'storage' as category,
        component,
        metric,
        value,
        if(metric = 'estimated_monthly_cost', 'usd', 'bytes') as unit
    from storage_agg
    unpivot (value for metric in (
        active_logical_bytes, long_term_logical_bytes, estimated_monthly_cost
    ))
)

select {{ run_date }} as cost_date, category, component, metric, value, unit from queries_long
union all
select {{ run_date }} as cost_date, category, component, metric, value, unit from storage_long
