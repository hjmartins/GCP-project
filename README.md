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
| 6. Camada fria + FinOps | ✅ backfill, camada fria Iceberg, archiver, custo diário e 6 experimentos medidos ([finops/experiments.md](finops/experiments.md)) |

## Como funciona hoje

```
Cloud Scheduler 06:00 BRT → Workflows "daily-pipeline"
  → Cloud Run Job "generator"  →  gs://<project>-bronze/<entidade>/dt=YYYY-MM-DD/part-000.parquet
                                  (dados sintéticos + 2% de erros injetados)
  → Cloud Run Job "loader"     →  load job GCS → bronze.<entidade> (staging do dia)
                               →  detecção de schema → silver.schema_events
                               →  dbt build: silver_* (MERGE) + quarentena
                                  → gold_data_quality_daily → [bloqueio] → gold de negócio
                                  → gold_cost_daily (bytes por origem + storage por camada)
  → Cloud Run Job "archiver"   →  Silver com mais de 90 dias → Iceberg em gs://<project>-cold/readings
     (mesma imagem do loader)  →  recria cold.readings (tabela externa BigLake) → apaga da Silver
```

| Componente | Pasta | O que faz |
| --- | --- | --- |
| Gerador | `generator/` | 200 usuários, 250 dispositivos, ~690 sessões e 72 mil leituras por dia, determinístico por `(SEED_BASE, RUN_DATE)`; injeta erros conhecidos (`FAULT_RATE`) |
| Loader | `loader/` | Load jobs do Bronze para `bronze.*`, detecção de colunas novas e `dbt build` com `run_date` |
| dbt | `dbt/` | Silver incremental (`MERGE`) + quarentena; Gold de qualidade e de negócio (`gold_daily_user_metrics`, `gold_device_health`) |
| Archiver | `archiver/` | Silver antiga → Iceberg (PyIceberg) no bucket frio, tabela externa `cold.readings` e limpeza de versões antigas; roda com a imagem do loader |
| Infra | `infra/` | Terraform: buckets, datasets, conexão BigLake, Artifact Registry, Cloud Run Jobs, Workflows, Scheduler, alerta, orçamento |

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

## Camada fria e FinOps (Fase 6)

### Backfill de 12 meses

O caminho dia a dia levaria ~24 h (365 execuções de ~4 min) e ~13 mil consultas pequenas, cada
uma cobrada pelo mínimo de 10 MB. O modo backfill faz tudo em lote:

1. `make backfill-generate`: o job do gerador com 4 tarefas paralelas (`CLOUD_RUN_TASK_INDEX`),
   cada uma com uma fatia das datas → 365 dias em **3 min 42 s**.
2. `make backfill-load`: um load job por entidade (gratuitos) com todas as datas e um único
   `dbt build --full-refresh` com a janela aberta para o intervalo todo → **2 min 48 s**.

| Medido | Valor |
| --- | --- |
| Consultas faturadas no backfill | **6,7 GB** (47 consultas; a maior, 1,27 GB) |
| Teto por consulta (`DBT_MAX_BYTES_BILLED`) | 5 GB no backfill, 1 GB no dia a dia: acima disso o BigQuery recusa antes de cobrar |
| Resultado | 24,4 milhões de leituras na Silver, 46/46 testes do dbt |

No backfill todas as linhas recebem o mesmo `batch_date` (o último dia), então a linha de
qualidade daquele dia mostra `late_arrival` perto de 100%. É efeito do modo lote, não erro.

### Iceberg externo, e não gerenciado

As duas opções guardam os dados no GCS, no nosso bucket; muda quem escreve e quem mantém.

| | Iceberg gerenciado pelo BigQuery | **Iceberg externo (escolhido)** |
| --- | --- | --- |
| Quem escreve | BigQuery (`INSERT`/`MERGE`) | o archiver, com PyIceberg |
| Manutenção (compactação, limpeza) | automática, **cobrada em DCU** | nossa, no archiver |
| `EXPORT METADATA` | slots da edição Enterprise (pagos) | — |
| BigQuery | lê e escreve | só lê (tabela externa BigLake) |
| Custo aqui | fora do free tier | **zero**: GCS Standard + consultas dentro do 1 TB |

Com um escritor só, uma vez por dia, e volume pequeno, o externo sai de graça sem trabalho
operacional relevante. Em produção, com vários escritores, seria preciso um catálogo de verdade
(BigLake metastore, Glue, Polaris) no lugar do SQLite que usamos.

O bucket frio ficou em **Standard, sem lifecycle**: é a única classe do free tier do GCS, e
Nearline/Coldline cobram leitura a cada consulta e exclusão antecipada quando o Iceberg reescreve
arquivos. A comparação entre classes vira projeção no experimento 4.

### Archiver

Roda todo dia depois do loader e move para o Iceberg o que passou de 90 dias:

1. Lista as partições da Silver anteriores ao corte (metadados, sem consulta).
2. Lê em lotes de 7 dias pela **Storage Read API** (não fatura como `SELECT`), grava no Iceberg
   **substituindo os dias** (idempotente) e confere que as contagens batem.
3. Apaga versões do Iceberg com mais de 7 dias **e os arquivos órfãos**: o `expire_snapshots`
   do PyIceberg só tira as versões dos metadados, os arquivos continuam no bucket.
4. Recria `cold.readings` apontando para o `metadata.json` novo (DDL não é cobrado).
5. Só então apaga esses dias da Silver: `DELETE ... WHERE ts < TIMESTAMP(@cutoff)`, por partição
   inteira, **0 bytes faturados**. A coluna de partição fica sem função no `WHERE` de propósito.

| Primeira execução (2026-10-22) | Valor |
| --- | --- |
| Arquivado | 278 dias, **18.391.290 leituras** (Silver = Iceberg = apagadas) |
| Tempo no Cloud Run | 3 min 17 s (1 vCPU, 512 MiB; pico medido no ensaio: 358 MB) |
| `DELETE` na Silver | 0 bytes faturados |
| Silver depois | 90 dias, 6,08 milhões de leituras, 0,52 GB (era 1,69 GB) |
| Consulta de 1 mês na camada fria | 50 MB lidos de 147 MB: a partição por dia do Iceberg é respeitada |

O archiver roda com a **mesma imagem do loader** (outro `command`): uma imagem a menos mantém o
Artifact Registry em ~410 MB, dentro do free tier de 0,5 GB.

### Custo diário (`gold.gold_cost_daily`)

Uma linha por (dia, categoria, componente, métrica), base do painel de FinOps:

- **query:** consultas, bytes processados, bytes faturados e custo estimado (US$ 6,25/TiB), por
  origem (`pipeline` ou `manual`), a partir de `INFORMATION_SCHEMA.JOBS`.
- **storage:** bytes ativos e long-term e custo mensal estimado por camada (US$ 0,023 e 0,016 por
  GiB lógico; bronze, silver, gold),
  a partir de `<dataset>.INFORMATION_SCHEMA.PARTITIONS`.

O custo estimado ignora o free tier: mostra quanto o projeto custaria fora dele. O storage é a
fotografia do momento da execução (as views de metadados não guardam histórico).
`INFORMATION_SCHEMA.TABLE_STORAGE` respondeu Access Denied mesmo para o dono do projeto; a
`PARTITIONS` por dataset dá a mesma informação de storage lógico, com a classe (ativo/long-term).

### Permissões mínimas

Onde o papel pronto daria mais do que o necessário, há um papel customizado com uma permissão só:

| Papel customizado | Permissão | Quem | Por quê |
| --- | --- | --- | --- |
| `runOperationsReader` | `run.operations.get` | workflow | acompanhar o job até terminar |
| `bigqueryConnectionDelegate` | `bigquery.connections.delegate` | pipeline (na conexão) | `CREATE EXTERNAL TABLE ... WITH CONNECTION` |
| `bigqueryJobsListAll` | `bigquery.jobs.listAll` | pipeline | ler os jobs do projeto no custo diário |

O `delegate` só apareceu na primeira execução na nuvem: o ensaio local rodou com a credencial de
dono do projeto, que tem tudo. Ensaiar também com a conta de serviço teria pegado antes.

### Resultados: quente × frio, medido

Detalhes, método e preços oficiais (Cloud Billing Catalog API) em
[finops/experiments.md](finops/experiments.md). Medições em 2026-10-22, sem cache.

**Consulta de 1 mês (2.005.920 leituras), mesma consulta nas duas camadas:**

| | Quente: BigQuery (`silver_readings`) | Frio: Iceberg via BigLake (`cold.readings`) |
| --- | --- | --- |
| Bytes faturados | 65 MB | 65 MB |
| Tempo (mediana de 5) | **182 ms** | **1.167 ms** (6× mais lento) |
| Processamento (slot-ms) | 336 | 2.744 |
| Bytes por linha armazenada | 64 (lógico) · 3,0 (físico) | **3,2** (Parquet zstd) |

**Storage dos 9 meses de histórico, custo mensal sem free tier:**

| Onde fica o histórico | Hoje (250 dispositivos) | Projeção: 10 mil dispositivos |
| --- | --- | --- |
| BigQuery, storage lógico long-term (padrão) | US$ 0,018 | US$ 0,70 |
| BigQuery, storage físico long-term | US$ 0,001 | US$ 0,04 |
| **Iceberg no GCS Standard (escolhido)** | **US$ 0,001** | **US$ 0,044** |
| Iceberg no GCS Coldline | US$ 0,0003 | US$ 0,014 |

O que os números dizem:

1. **Consultar o frio não sai mais barato**: o BigQuery cobra os mesmos bytes, e a consulta é 6×
   mais lenta. A economia está só no storage: 20× menos bytes no Iceberg do que no storage lógico.
2. **O corte de 90 dias fica.** O painel olha os últimos 30 dias, que continuam rápidos no quente;
   mover antes economizaria centavos e deixaria lenta a janela mais usada.
3. **A maior alavanca não é a camada fria, é o modelo de cobrança.** Com storage **físico**, o
   BigQuery cobra o dado comprimido e fica no mesmo patamar do Iceberg: na Silver de hoje, 522 MB
   lógicos viram 93 MB físicos e o custo cai 3×; em escala, ~90%. É uma linha de Terraform
   (`storage_billing_model = "PHYSICAL"`). Com ela, a camada fria passaria a se justificar pelo
   formato aberto (ler o histórico com Spark ou Trino), não pelo preço.
4. **Coldline economizaria US$ 0,03/mês** em escala: não paga o risco das taxas de permanência
   mínima com o Iceberg reescrevendo arquivos. O bucket frio fica em Standard, no free tier.

**Outros resultados medidos:** particionar reduziu uma consulta de 7 dias de 195 MB para 16 MB
(12×); o clustering quase não ajudou (4%) porque as partições têm só ~4 MB; e a Gold como tabela
só fica mais barata que uma view acima de ~26–44 consultas por mês, por causa da cobrança mínima
de 10 MB por tabela.

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
| `make test` / `make lint` | pytest e ruff do gerador, do loader e do archiver |
| `make generate-local RUN_DATE=2026-10-01` | Gera um dia em `./data`, sem nuvem |
| `make run-day RUN_DATE=2026-10-01` | Roda gerador + loader na nuvem para um dia (direto nos jobs) |
| `FAULT_RATE=0.08 make generate-local` | Gera um dia com mais erros (ex.: testar o bloqueio) |
| `gcloud workflows run daily-pipeline --location us-central1 --data='{"run_date":"2026-10-01"}'` | Roda o dia pelo workflow, como o agendamento fará |
| `make load-local RUN_DATE=...` | Roda o loader e o dbt localmente, com o seu login |
| `make run-archiver RUN_DATE=...` | Roda o archiver na nuvem para um dia |
| `make backfill-generate backfill-load BACKFILL_START=... BACKFILL_END=...` | Gera e carrega um intervalo de datas em lote |

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

### Página de custo (Fase 6)

Fonte: `gold.gold_cost_daily`, com `cost_date` como dimensão de período.

- **Bytes faturados por dia**, empilhado por `component` (pipeline × manual), com
  `metric = bytes_billed`.
- **Custo estimado acumulado no mês** (`metric = estimated_cost`), comparado com o equivalente do
  free tier (1 TiB = US$ 6,25).
- **Storage por camada** (`category = storage`, `metric = active_logical_bytes`): mostra a Silver
  encolhendo quando o archiver move dados para a camada fria.
