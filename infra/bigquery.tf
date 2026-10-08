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
