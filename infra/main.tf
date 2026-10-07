terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
  }

  # State local na Fase 0. Migrar para backend "gcs" depois que o bucket de state existir.
}

provider "google" {
  project = var.project_id
  region  = var.region

  # Necessário para a API de Billing Budgets com credenciais de usuário (ADC).
  billing_project       = var.project_id
  user_project_override = true
}

locals {
  apis = [
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "iam.googleapis.com",
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "bigqueryconnection.googleapis.com",
    "run.googleapis.com",
    "workflows.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "monitoring.googleapis.com",
  ]

  labels = {
    project = "gcp-telemetry-finops"
    env     = var.env
  }
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  service            = each.value
  disable_on_destroy = false
}

# Conta de serviço usada pelos Cloud Run Jobs (gerador, loader, archiver).
resource "google_service_account" "pipeline" {
  account_id   = "pipeline-runner"
  display_name = "Pipeline runner (Cloud Run Jobs)"

  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "pipeline_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = google_service_account.pipeline.member
}
