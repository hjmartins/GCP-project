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

# O archiver lê a Silver pela Storage Read API (sem consulta, sem bytes faturados como SELECT).
resource "google_project_iam_member" "pipeline_bq_read_session" {
  project = var.project_id
  role    = "roles/bigquery.readSessionUser"
  member  = google_service_account.pipeline.member
}

# gold_cost_daily lê INFORMATION_SCHEMA.JOBS do projeto inteiro (consultas de todas as contas),
# o que exige bigquery.jobs.listAll. O papel pronto com essa permissão (bigquery.resourceViewer)
# também lê reservas e capacidade: daí o papel customizado só com o listAll.
resource "google_project_iam_custom_role" "jobs_list_all" {
  role_id     = "bigqueryJobsListAll"
  title       = "BigQuery Jobs List All"
  description = "Só lista os jobs de todas as contas do projeto (custo diário em gold_cost_daily)."
  permissions = ["bigquery.jobs.listAll"]
}

resource "google_project_iam_member" "pipeline_lists_all_jobs" {
  project = var.project_id
  role    = google_project_iam_custom_role.jobs_list_all.id
  member  = google_service_account.pipeline.member
}