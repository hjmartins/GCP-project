resource "google_artifact_registry_repository" "pipeline" {
  repository_id = "pipeline"
  location      = var.region
  format        = "DOCKER"
  description   = "Imagens dos Cloud Run Jobs do pipeline."
  labels        = local.labels

  # Free tier: 0,5 GB. As duas imagens somam ~390 MB comprimidas, então guardamos
  # só a versão mais recente de cada (rollback = rebuild a partir do git).
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-latest"
    action = "KEEP"
    most_recent_versions {
      keep_count = 1
    }
  }
  cleanup_policies {
    id     = "delete-older"
    action = "DELETE"
    condition {
      tag_state = "ANY"
    }
  }

  depends_on = [google_project_service.apis]
}

locals {
  bronze_uri = "gs://${google_storage_bucket.bronze.name}"
}

# Os jobs só existem depois que a imagem foi publicada (make push).
resource "google_cloud_run_v2_job" "generator" {
  count = var.generator_image == null ? 0 : 1

  name                = "generator"
  location            = var.region
  deletion_protection = false
  labels              = local.labels

  template {
    task_count = 1
    template {
      service_account = google_service_account.pipeline.email
      max_retries     = 1
      timeout         = "600s"

      containers {
        image = var.generator_image
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
        env {
          name  = "OUTPUT_URI"
          value = local.bronze_uri
        }
        env {
          name  = "SEED_BASE"
          value = "42"
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job" "loader" {
  count = var.loader_image == null ? 0 : 1

  name                = "loader"
  location            = var.region
  deletion_protection = false
  labels              = local.labels

  template {
    task_count = 1
    template {
      service_account = google_service_account.pipeline.email
      max_retries     = 1
      timeout         = "1200s"

      containers {
        image = var.loader_image
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
        env {
          name  = "GCP_PROJECT"
          value = var.project_id
        }
        env {
          name  = "BRONZE_BUCKET"
          value = google_storage_bucket.bronze.name
        }
      }
    }
  }
}
