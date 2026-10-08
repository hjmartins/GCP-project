-- Cadastro pequeno (200 linhas) e enviado completo todo dia: tabela recriada, sem partição.
{{ config(materialized='table') }}

select user_id, faixa_etaria, cidade, data_cadastro
from {{ source('bronze', 'users') }}
