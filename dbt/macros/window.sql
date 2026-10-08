{# Início da janela de reprocessamento: run_date - lookback_days. #}
{% macro window_start_date() -%}
    date_sub(date('{{ var("run_date") }}'), interval {{ var("lookback_days") }} day)
{%- endmacro %}

{% macro window_start_ts() -%}
    timestamp({{ window_start_date() }})
{%- endmacro %}

{% macro run_date_end_ts() -%}
    timestamp(date_add(date('{{ var("run_date") }}'), interval 1 day))
{%- endmacro %}

{# Filtro de leitura da Silver para os modelos Gold: só a janela recente nas execuções
   incrementais; o histórico todo num full refresh. O limite inferior explícito também
   satisfaz o require_partition_filter da silver_readings. #}
{% macro incremental_ts_filter(column) -%}
    {%- if is_incremental() -%}
        {{ column }} >= {{ window_start_ts() }}
    {%- else -%}
        {{ column }} >= timestamp('2000-01-01')
    {%- endif %}
    and {{ column }} < {{ run_date_end_ts() }}
{%- endmacro %}
