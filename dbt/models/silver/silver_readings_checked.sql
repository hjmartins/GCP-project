-- Classifica cada leitura do lote do dia. quarantine_reason nulo = leitura válida.
-- Ephemeral: não vira tabela; o dbt cola este SQL como CTE em quem fizer ref() dele
-- (silver_readings e silver_readings_quarantine).
{{ config(materialized='ephemeral') }}

{%- set source_col = adapter.get_columns_in_relation(source('bronze', 'readings'))
                        | map(attribute='name') | list -%}


SELECT 
    r.device_id,
    r.ts,
    r.heart_rate,
    r.steps,
    r.spo2,
    r.battery,
    {% if 'skin_temp' in source_col -%}
    r.skin_temp,
    {% endif -%}
    CASE 
        WHEN r.device_id is null or r.ts is null THEN 'null_key'  
        WHEN r.ts < {{window_start_ts()}} or r.ts >= {{run_date_end_ts()}} THEN 'out_of_window'
        WHEN d.device_id is null THEN 'orphan_device'
        WHEN (r.heart_rate is null or r.heart_rate NOT BETWEEN 30 AND 250) 
            OR (r.spo2 is null or r.spo2 NOT BETWEEN 70 AND 100) 
            OR (r.battery is null or r.battery NOT BETWEEN 0 AND 100)
            OR (r.steps < 0) THEN 'out_of_range'
        ELSE  null
    END as quarantine_reason
FROM {{source('bronze', 'readings')}} as r
LEFT JOIN {{ref('silver_devices')}} as d
    ON r.device_id = d.device_id

