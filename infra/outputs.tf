output "bronze_bucket" {
  value = google_storage_bucket.bronze.name
}

output "cold_bucket" {
  value = google_storage_bucket.cold.name
}

output "datasets" {
  value = [for d in google_bigquery_dataset.layers : d.dataset_id]
}

output "pipeline_service_account" {
  value = google_service_account.pipeline.email
}

output "registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.pipeline.repository_id}"
}
