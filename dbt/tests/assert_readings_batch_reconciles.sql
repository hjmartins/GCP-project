-- Nenhuma leitura do lote some no caminho:
--   linhas do lote = válidas na Silver + quarentena + duplicatas removidas.
-- As duplicatas são contadas direto no lote (linhas com chave completa além da primeira de
-- cada device_id, ts), sem usar a classificação do silver_readings_checked: assim o teste
-- confere a lógica dos modelos em vez de repeti-la. Pressupõe que linhas inválidas não vêm
-- duplicadas (verdade no gerador; os blocos de erro são disjuntos).
-- Retorna uma linha (= falha) quando a conta não fecha.

with batch as (
    select
        count(*) as total_rows,
        countif(device_id is not null and ts is not null) as rows_with_key,
        count(distinct if(
            device_id is not null and ts is not null,
            concat(device_id, '|', cast(ts as string)),
            null
        )) as distinct_keys
    from {{ source('bronze', 'readings') }}
),

silver as (
    select count(*) as valid_rows
    from {{ ref('silver_readings') }}
    where ts >= {{ window_start_ts() }}
        and batch_date = date('{{ var("run_date") }}')
),

quarantine as (
    select count(*) as quarantined_rows
    from {{ ref('silver_readings_quarantine') }}
    where batch_date = date('{{ var("run_date") }}')
)

select
    batch.total_rows,
    silver.valid_rows,
    quarantine.quarantined_rows,
    batch.rows_with_key - batch.distinct_keys as duplicates_removed
from batch, silver, quarantine
where batch.total_rows
    != silver.valid_rows + quarantine.quarantined_rows
    + (batch.rows_with_key - batch.distinct_keys)
