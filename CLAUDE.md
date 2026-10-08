# CLAUDE.md — gcp-telemetry-finops

## Contexto
Pipeline diário de telemetria sintética no GCP (free tier). Medalhão Bronze (GCS Parquet)
→ Silver/Gold (BigQuery) → camada fria Iceberg via BigLake. Foco: FinOps e qualidade de dados.
Documento de projeto completo: `Projeto GCP Free Tier — Telemetria sintética com FinOps, Qualidade e Iceberg.md`.

## Regras de custo (obrigatórias)
- NUNCA usar Cloud Composer, Dataflow, Dataproc, Cloud SQL ou VMs sempre ligadas.
- Região: us-central1 para tudo.
- Toda tabela de fatos/agregados BigQuery com partição por dia; readings clusterizada por device_id.
  Exceção: cadastros pequenos (silver_users, silver_devices) sem partição — as datas de 2024
  expirariam na hora com a expiração de partição de dev.
- Toda consulta com filtro de partição; nunca SELECT * em tabelas de leitura.
- Datasets com expiração padrão de partição em dev.
- Cloud Run Jobs com no máximo 1 vCPU e 512 MiB, salvo justificativa.
- Qualquer recurso novo entra via Terraform em infra/, nunca criado pelo console.

## Convenções
- Python 3.12, uv para dependências, ruff + pytest.
- Gerador determinístico: toda aleatoriedade passa por seed derivada de (seed_base, data).
- Loader idempotente: MERGE por chave; rodar o mesmo dia 2x não duplica.
- dbt: silver_* e gold_* como prefixos; todo modelo com testes em schema.yml.
- Configuração por variáveis de ambiente; nenhum segredo no código.

## Fluxo de trabalho
- Implementar uma fase por vez, seguindo a tabela de fases do documento de projeto.
- Ao fim de cada fase: testes passando, README atualizado, commit convencional (feat:, fix:, chore:).
- Antes de terraform apply, mostrar o plan e esperar confirmação.
