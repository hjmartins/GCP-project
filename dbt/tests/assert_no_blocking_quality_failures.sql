-- Teste bloqueante: falha se alguma verificação 'blocking' do lote falhou.
-- Olha um único modelo (gold_data_quality_daily) de propósito: assim o dbt build pula os
-- modelos que dependem dele (Gold de negócio), e o pipeline não publica dado ruim.
select check_name, rows_evaluated, rows_failed, failure_rate, threshold
from {{ ref('gold_data_quality_daily') }}
where batch_date = date('{{ var("run_date") }}')
    and severity = 'blocking'
    and status = 'fail'
