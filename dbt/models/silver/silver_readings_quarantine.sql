{{
    config(
        materialized='incremental',
        incremental_strategy='insert_overwrite',
        partition_by={'field': 'batch_date', 'data_type': 'date'},
        partitions=["date('" ~ var('run_date') ~ "')"],
        cluster_by=['quarantine_reason'],
        on_schema_change='append_new_columns',
    )
}}

-- select *: todas as colunas do checked, inclusive quarantine_reason e skin_temp (se existir).
SELECT
    *,
    date('{{var("run_date")}}') as batch_date,
    current_timestamp() as loaded_at
FROM {{ref('silver_readings_checked')}}
WHERE quarantine_reason is not null