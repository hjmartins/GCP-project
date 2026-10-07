# Bronze: Parquet cru do gerador. Fica em Standard (única classe coberta pelo free tier).
resource "google_storage_bucket" "bronze" {
  name     = "${var.project_id}-bronze"
  location = upper(var.region)

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_buckets
  labels                      = merge(local.labels, { layer = "bronze" })

  depends_on = [google_project_service.apis]
}

# Camada fria: tabelas Iceberg. Lifecycle Nearline aos 30 dias e Coldline aos 90
# (regra a validar no experimento 3 de FinOps).
resource "google_storage_bucket" "cold" {
  name     = "${var.project_id}-cold"
  location = upper(var.region)

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_buckets
  labels                      = merge(local.labels, { layer = "cold" })

  lifecycle_rule {
    condition {
      age                   = 30
      matches_storage_class = ["STANDARD"]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age                   = 90
      matches_storage_class = ["NEARLINE"]
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "pipeline_bronze" {
  bucket = google_storage_bucket.bronze.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.pipeline.member
}

resource "google_storage_bucket_iam_member" "pipeline_cold" {
  bucket = google_storage_bucket.cold.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.pipeline.member
}
