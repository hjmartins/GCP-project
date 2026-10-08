-- Cadastro pequeno (~250 linhas) e enviado completo todo dia: tabela recriada, sem partição.
{{ config(materialized='table') }}

select device_id, user_id, modelo, firmware, ativado_em
from {{ source('bronze', 'devices') }}
