# Alerta de falha do pipeline: o Workflows grava um log de sistema ERROR (executions_system)
# em qualquer execução que termina FAILED, inclusive em passos fora do try do YAML.
# O log "pipeline_failed" gravado pelo próprio workflow fica para consulta (tem o run_date).
#
# Custo: grátis hoje; o Google anunciou cobrança de alertas a partir de 01/09/2027
# (~US$ 0,35/mês por condição baseada em log).
resource "google_monitoring_alert_policy" "pipeline_failed" {
  display_name = "Pipeline diário falhou"
  combiner     = "OR"

  conditions {
    display_name = "Execução do daily-pipeline terminou com erro"
    condition_matched_log {
      filter = <<-EOT
        resource.type="workflows.googleapis.com/Workflow"
        resource.labels.workflow_id="${google_workflows_workflow.daily_pipeline.name}"
        logName="projects/${var.project_id}/logs/workflows.googleapis.com%2Fexecutions_system"
        severity=ERROR
      EOT
      label_extractors = {
        erro = "REGEXP_EXTRACT(jsonPayload.failure.exception, \"^([^\\\\n]{0,200})\")"
      }
    }
  }

  # Alertas por log exigem limite de notificação: no máximo um e-mail a cada 5 min.
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }

  # TODO: definir como notificar falhas do pipeline (e-mail retirado em 2026-10-09).
  # Sem canal, o alerta continua abrindo incidentes no console (Monitoring → Alertas).
  # Para voltar ao e-mail: [google_monitoring_notification_channel.email.id]
  notification_channels = []

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      O workflow **daily-pipeline** falhou.

      1. Veja a execução: Console → Workflows → daily-pipeline → Execuções.
      2. O log `jsonPayload.event="pipeline_failed"` traz o `run_date` e o erro.
      3. Corrigido o problema, reprocesse o dia (é idempotente):
         `gcloud workflows run daily-pipeline --location ${var.region} --data='{"run_date":"AAAA-MM-DD"}'`
    EOT
  }
}
