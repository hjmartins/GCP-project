# gcp-telemetry-finops

Pipeline diário de telemetria sintética de dispositivos vestíveis no GCP, 100% no free tier.
Arquitetura medalhão (Bronze GCS → Silver/Gold BigQuery) com camada fria em Apache Iceberg via BigLake.
Foco em **FinOps** e **qualidade de dados**. Detalhes no documento de projeto na raiz.

## Status

| Fase | Status |
| --- | --- |
| 0. Fundação | ✅ |
| 1. Gerador | ✅ |
| 2. Silver | ✅ |
| 3. Gold + dbt | ✅ modelos e testes; painel no Looker Studio pendente (manual) |
| 4. Orquestração | ✅ 7 dias seguidos sem intervenção (10–16/10); notificação do alerta a definir |
| 5. Qualidade | ✅ 7 erros injetados, todos detectados; Gold bloqueada acima do limite |
| 6. Camada fria + FinOps | — |

## Como funciona hoje

```
Cloud Scheduler 06:00 BRT → Workflows "daily-pipeline"
  → Cloud Run Job "generator"  →  gs://<project>-bronze/<entidade>/dt=YYYY-MM-DD/part-000.parquet
                                  (dados sintéticos + 2% de erros injetados)
  → Cloud Run Job "loader"     →  load job GCS → bronze.<entidade> (staging do dia)
                               →  detecção de schema → silver.schema_events
                               →  dbt build: silver_* (MERGE) + quarentena
                                  → gold_data_quality_daily → [bloqueio] → gold de negócio
```

| Componente | Pasta | O que faz |
| --- | --- | --- |
| Gerador | `generator/` | 200 usuários, 250 dispositivos, ~690 sessões e 72 mil leituras por dia, determinístico por `(SEED_BASE, RUN_DATE)`; injeta erros conhecidos (`FAULT_RATE`) |
| Loader | `loader/` | Load jobs do Bronze para `bronze.*`, detecção de colunas novas e `dbt build` com `run_date` |
| dbt | `dbt/` | Silver incremental (`MERGE`) + quarentena; Gold de qualidade e de negócio (`gold_daily_user_metrics`, `gold_device_health`) |
| Infra | `infra/` | Terraform: buckets, datasets, Artifact Registry, Cloud Run Jobs, orçamento |

### Decisões de projeto

- **Load job em vez de tabela externa no Bronze.** Load jobs do BigQuery não cobram bytes
  processados; consultar uma tabela externa cobra. O staging `bronze.*` guarda só o lote do dia.
- **MERGE limitado à janela recente.** Silver e Gold usam `incremental_predicates`: o MERGE só lê
  as partições dos últimos `lookback_days` (7) no destino, não a tabela inteira. A janela cobre
  chegadas atrasadas de até 3 dias com folga.
- **`silver_readings` exige filtro de partição** (`require_partition_filter`): consulta sem filtro
  de data falha em vez de varrer a tabela toda. Os testes dbt também olham só a janela.
- **`maximum_bytes_billed` de 1 GB** no profile do dbt: nenhuma consulta pode passar disso.
- **Cobrança mínima de 10 MB por consulta.** Um dia processa ~7 MB de dados, mas o BigQuery
  cobra no mínimo 10 MB por tabela referenciada em cada consulta. Com 6 modelos e 29 testes, uma
  execução custa ~350 MB faturados (~10 GB/mês, 1% do free tier). Medido em
  `INFORMATION_SCHEMA.JOBS`: 1,37 GB faturados em 143 consultas (4 execuções do pipeline + verificações).
- **Cadastros sem partição.** `silver_users` e `silver_devices` são pequenos, e as datas de cadastro
  (2024) expirariam na hora com a expiração de partição de 400 dias do ambiente de dev.
- **Usuários com 2 dispositivos.** Passos e sono vêm do dispositivo com maior valor no dia (somar
  contaria a mesma atividade duas vezes); a frequência cardíaca usa todas as leituras.
- **Cidades de uma lista fixa, sem Faker.** Agrupam bem no painel e não mudam entre versões de biblioteca.
- **Artifact Registry guarda só a última versão de cada imagem.** As duas imagens somam ~375 MB,
  e o free tier é 0,5 GB.
- **Orquestração.** O Cloud Scheduler dispara o workflow `daily-pipeline` às 06:00 (Brasília),
  que roda gerador e loader em sequência e espera cada um terminar. Retry só para erros
  transitórios da API; falha do job vai direto para o alerta (repetir um teste de dados que
  falhou não resolve). Três contas de serviço com papéis mínimos: `scheduler-invoker` (só
  inicia o workflow), `workflow-runner` (só executa os jobs, lê operações e grava logs) e
  `pipeline-runner` (dados).
- **Alerta de falha por log.** Uma política do Cloud Monitoring escuta o log de sistema do
  Workflows e abre um incidente (notificação ainda a definir; e-mail desativado). Grátis hoje; o Google anunciou cobrança a partir de 01/09/2027
  (~US$ 0,35/mês por condição baseada em log).
- **Orçamento em R$ 5.** A meta do documento é US$ 1, mas a conta de faturamento é em BRL e a
  moeda do orçamento precisa ser a mesma da conta.

## Qualidade de dados (Fase 5)

O gerador estraga os dados de propósito (`FAULT_RATE`, padrão 2% por tipo) e o pipeline precisa
pegar cada erro. Cada erro tem seed própria: a mesma data gera sempre os mesmos erros.

| Erro injetado | Como o gerador cria | Onde é detectado | O que acontece |
| --- | --- | --- | --- |
| Duplicata | Reenvia leituras idênticas | `qualify` + `MERGE`; verificação `duplicate_readings` | Deduplica; **bloqueia** acima de 5% |
| Chave nula | `device_id` ou `ts` nulo | `silver_readings_checked` → `null_key` | Quarentena; **bloqueia** acima de 5% |
| Fora da faixa | `heart_rate` < 0 ou > 250, `spo2` > 100 | `out_of_range` | Quarentena + aviso |
| Dispositivo órfão | `device_id` fora do cadastro (`D9xxxx`) | `left join` com `silver_devices` → `orphan_device` | Quarentena + aviso |
| Chegada atrasada | Últimas 12 h de alguns dispositivos chegam 3 dias depois | `ts` anterior ao lote → `late_arrival` | Entra na partição certa; a janela de 7 dias recalcula a Gold |
| Dispositivo sumido | 1 dispositivo/dia some por 2 a 5 dias | Dispositivo ativo sem leitura → `silent_devices`; `gold_device_health.has_signal` | Aviso |
| Mudança de schema | Coluna `skin_temp` a partir de `SKIN_TEMP_SINCE` | Loader compara staging × Silver → `silver.schema_events` | Coluna aceita como nullable (`on_schema_change`) + aviso |

**Peças principais**
- `silver_readings_checked` (ephemeral) etiqueta cada linha do lote com `quarantine_reason`; a
  `silver_readings` recebe as válidas e a `silver_readings_quarantine` as inválidas, com o motivo.
- `tests/assert_readings_batch_reconciles.sql`: nenhuma linha some — lote = Silver + quarentena +
  duplicatas removidas.
- `gold_data_quality_daily`: uma linha por verificação por dia (`rows_evaluated`, `rows_failed`,
  `failure_rate`, `status`), base do painel de qualidade.
- `tests/assert_no_blocking_quality_failures.sql` olha só a tabela de qualidade, e a Gold de
  negócio depende dela (`depends_on`): se um bloqueante falha, o dbt pula a Gold, o loader sai com
  erro, o workflow falha e o alerta abre um incidente. A Silver e a quarentena ficam gravadas.

**Resultados medidos**

| Dia | Erros | Resultado |
| --- | --- | --- |
| 2026-10-20 (2%) | 1.394 de cada tipo por linha, 1.440 atrasadas, 3 sumidos, 1 coluna nova | Todos detectados com a contagem exata; bloqueantes `pass`, avisos `warn`; Gold publicada |
| 2026-09-15 (8%, teste forçado) | 4.919 de cada tipo | `duplicate_readings` 7,4% e `null_key` 6,9% → `fail`; Gold **não** publicada |

**Reprocessar um dia cujo conteúdo mudou.** O `MERGE` insere e atualiza, mas não apaga: se o lote
de um dia já carregado muda (ex.: nova versão do gerador), as linhas antigas que não vieram de novo
ficam na Silver e a reconciliação acusa. Nesse caso, apague o lote antes:
`delete from silver.silver_readings where ts >= '<dia - 7>' and batch_date = '<dia>'`.

## Uso

Pré-requisitos: `gcloud`, `terraform` (>= 1.6), `uv`, Docker e um projeto GCP com faturamento.

```bash
gcloud auth login
gcloud auth application-default login
gcloud auth application-default set-quota-project <PROJECT_ID>
gcloud auth configure-docker us-central1-docker.pkg.dev
```

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars   # preencher
make tf-init && make tf-plan    # revisar o plan
make tf-apply
make push                       # build + push das imagens; grava infra/images.auto.tfvars
make tf-plan && make tf-apply   # cria/atualiza os Cloud Run Jobs com as imagens novas
```

| Comando | O que faz |
| --- | --- |
| `make test` / `make lint` | pytest e ruff do gerador e do loader |
| `make generate-local RUN_DATE=2026-10-01` | Gera um dia em `./data`, sem nuvem |
| `make run-day RUN_DATE=2026-10-01` | Roda gerador + loader na nuvem para um dia (direto nos jobs) |
| `FAULT_RATE=0.08 make generate-local` | Gera um dia com mais erros (ex.: testar o bloqueio) |
| `gcloud workflows run daily-pipeline --location us-central1 --data='{"run_date":"2026-10-01"}'` | Roda o dia pelo workflow, como o agendamento fará |
| `make load-local RUN_DATE=...` | Roda o loader e o dbt localmente, com o seu login |

## Painel no Looker Studio (Fase 3)

1. Em [lookerstudio.google.com](https://lookerstudio.google.com), crie um relatório com a fonte
   **BigQuery** → projeto → dataset `gold`.
2. Adicione `gold_daily_user_metrics` e `gold_device_health`, com `metric_date` como dimensão de período.
3. Sugestões: passos e sono médios por dia, FC média por faixa etária (junte com `silver.silver_users`),
   completude e bateria média por modelo/firmware.

### Página de qualidade (Fase 5)

Fonte: `gold.gold_data_quality_daily`, com `batch_date` como dimensão de período.

- **Tabela de status do dia:** `check_name`, `severity`, `rows_failed`, `failure_rate`, `status`,
  com formatação condicional (`fail` vermelho, `warn` amarelo).
- **Série temporal:** `failure_rate` por `check_name`, com uma linha de referência em 0,05 (o limite
  dos bloqueantes).
- **Quarentena por motivo:** `silver.silver_readings_quarantine`, contagem por `quarantine_reason`
  e `batch_date`.
- **Dispositivos sem sinal:** `gold.gold_device_health` filtrado em `has_signal = false`.
