-- O custo do dia precisa trazer, no mínimo: as consultas do pipeline (ele roda todo dia) e o
-- storage das três camadas do BigQuery. Retorna as combinações que faltam.
with expected as (
    select 'query' as category, 'pipeline' as component, metric
    from unnest(['queries', 'bytes_processed', 'bytes_billed', 'estimated_cost']) as metric
    union all
    select 'storage', dataset, metric
    from unnest(['bronze', 'silver', 'gold']) as dataset,
        unnest(['active_logical_bytes', 'long_term_logical_bytes', 'estimated_monthly_cost']) as metric
)

select e.*
from expected as e
left join {{ ref('gold_cost_daily') }} as c
    on c.category = e.category
    and c.component = e.component
    and c.metric = e.metric
    and c.cost_date = date('{{ var("run_date") }}')
where c.metric is null
