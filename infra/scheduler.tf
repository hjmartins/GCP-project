# Dispara o daily-pipeline todo dia às 06:00 de Brasília, sem argumento: o workflow
# processa "ontem". Free tier: 3 jobs do Scheduler por conta de faturamento.
resource "google_cloud_scheduler_job" "daily_pipeline" {
  name        = "daily-pipeline"
  region      = var.region
  description = "Executa o workflow daily-pipeline (processa o dia anterior)."
  schedule    = "0 6 * * *"
  time_zone   = "America/Sao_Paulo"

  # O Scheduler só cria a execução (a resposta é imediata); o pipeline roda no Workflows.
  attempt_deadline = "60s"
  retry_config {
    retry_count = 2
  }

  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.daily_pipeline.id}/executions"
    body        = base64encode(jsonencode({}))
    headers = {
      "Content-Type" = "application/json"
    }

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_project_iam_member.scheduler_invokes_workflows]
}
