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
| 4. Orquestração | — |
| 5. Qualidade | — |
| 6. Camada fria + FinOps | — |

## Como funciona hoje

```
Cloud Run Job "generator"  →  gs://<project>-bronze/<entidade>/dt=YYYY-MM-DD/part-000.parquet
Cloud Run Job "loader"     →  load job GCS → bronze.<entidade> (staging do dia)
                           →  dbt build: silver_* (MERGE) → gold_* + 29 testes
```

| Componente | Pasta | O que faz |
| --- | --- | --- |
| Gerador | `generator/` | 200 usuários, 250 dispositivos, ~690 sessões e 72 mil leituras por dia, determinístico por `(SEED_BASE, RUN_DATE)` |
| Loader | `loader/` | Load jobs do Bronze para `bronze.*` e `dbt build` com `run_date` |
| dbt | `dbt/` | Silver incremental (`MERGE`) e Gold (`gold_daily_user_metrics`, `gold_device_health`) |
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
- **Orçamento em R$ 5.** A meta do documento é US$ 1, mas a conta de faturamento é em BRL e a
  moeda do orçamento precisa ser a mesma da conta.

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
| `make run-day RUN_DATE=2026-10-01` | Roda gerador + loader na nuvem para um dia |
| `make load-local RUN_DATE=...` | Roda o loader e o dbt localmente, com o seu login |

## Painel no Looker Studio (Fase 3)

1. Em [lookerstudio.google.com](https://lookerstudio.google.com), crie um relatório com a fonte
   **BigQuery** → projeto → dataset `gold`.
2. Adicione `gold_daily_user_metrics` e `gold_device_health`, com `metric_date` como dimensão de período.
3. Sugestões: passos e sono médios por dia, FC média por faixa etária (junte com `silver.silver_users`),
   completude e bateria média por modelo/firmware.
