locals {
  # Em dev, partições expiram sozinhas para o storage não crescer sem controle.
  partition_expiration_ms = var.env == "dev" ? var.dev_partition_expiration_days * 24 * 60 * 60 * 1000 : null

  datasets = {
    bronze = "Staging do lote diário carregado do GCS (sobrescrito a cada execução)."
    silver = "Dados deduplicados e tipados; inclui silver.quarantine."
    gold   = "Agregados de negócio, qualidade e custo."
  }
}

resource "google_bigquery_dataset" "layers" {
  for_each = local.datasets

  dataset_id                      = each.key
  description                     = each.value
  location                        = var.region
  default_partition_expiration_ms = local.partition_expiration_ms
  delete_contents_on_destroy      = var.env == "dev"
  labels                          = merge(local.labels, { layer = each.key })

  depends_on = [google_project_service.apis]
}

resource "google_bigquery_dataset_iam_member" "pipeline_editor" {
  for_each = google_bigquery_dataset.layers

  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.pipeline.member
}

# A conexão BigLake (camada fria Iceberg) entra na Fase 6.

# Mudanças de schema detectadas pelo loader (Fase 5): uma linha por coluna nova.
resource "google_bigquery_table" "schema_events" {
  dataset_id          = google_bigquery_dataset.layers["silver"].dataset_id
  table_id            = "schema_events"
  description         = "Colunas novas detectadas no lote (staging) que ainda não existiam na Silver."
  deletion_protection = false
  labels              = local.labels

  time_partitioning {
    type  = "DAY"
    field = "batch_date"
  }

  schema = jsonencode([
    { name = "detected_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "batch_date", type = "DATE", mode = "REQUIRED", description = "Lote em que a coluna apareceu" },
    { name = "table_name", type = "STRING", mode = "REQUIRED" },
    { name = "column_name", type = "STRING", mode = "REQUIRED" },
    { name = "column_type", type = "STRING", mode = "REQUIRED" },
    { name = "change", type = "STRING", mode = "REQUIRED", description = "Por enquanto só 'added'" },
  ])
}
