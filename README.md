# gcp-telemetry-finops

Pipeline diário de telemetria sintética de dispositivos vestíveis no GCP, 100% no free tier.
Arquitetura medalhão (Bronze GCS → Silver/Gold BigQuery) com camada fria em Apache Iceberg via BigLake.
Foco em **FinOps** e **qualidade de dados**. Detalhes no documento de projeto na raiz.

## Status

| Fase | Status |
| --- | --- |
| 0. Fundação | Em andamento |
| 1. Gerador | — |
| 2. Silver | — |
| 3. Gold + dbt | — |
| 4. Orquestração | — |
| 5. Qualidade | — |
| 6. Camada fria + FinOps | — |

## Fase 0 — Fundação

O Terraform em `infra/` cria:

- APIs necessárias ao projeto
- Buckets `<project>-bronze` (Standard) e `<project>-cold` (lifecycle Nearline 30d → Coldline 90d)
- Datasets BigQuery `silver` e `gold` em `us-central1` (expiração de partição em dev)
- Conta de serviço `pipeline-runner` com acesso mínimo aos buckets e datasets
- Alerta de orçamento de US$ 1 (50%, 100% e 100% previsto) com canal de e-mail

### Pré-requisitos

- `gcloud`, `terraform` (>= 1.6)
- Projeto GCP dedicado com faturamento vinculado

```bash
gcloud auth login
gcloud auth application-default login
gcloud auth application-default set-quota-project <PROJECT_ID>
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com billingbudgets.googleapis.com --project <PROJECT_ID>
```

### Subir a infra

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars   # preencher
make tf-init
make tf-plan     # revisar
make tf-apply
```
