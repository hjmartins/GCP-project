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

# Camada fria: tabelas Iceberg escritas pelo archiver. Fica em Standard: é a única classe
# coberta pelo free tier do GCS, e Nearline/Coldline cobram leitura (retrieval) a cada consulta
# e exclusão antecipada quando arquivos são reescritos antes de 30/90 dias. A comparação entre
# classes é feita como projeção no experimento 4 de FinOps (finops/experiments.md).
resource "google_storage_bucket" "cold" {
  name     = "${var.project_id}-cold"
  location = upper(var.region)

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_buckets
  labels                      = merge(local.labels, { layer = "cold" })

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
