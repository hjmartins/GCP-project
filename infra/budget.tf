data "google_project" "this" {
  project_id = var.project_id
}

resource "google_monitoring_notification_channel" "email" {
  display_name = "Alertas gcp-telemetry-finops"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.apis]
}

resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account_id
  display_name    = "gcp-telemetry-finops (${var.env})"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
    # Conta também gastos cobertos por créditos (ex.: trial de US$ 300),
    # para o alerta refletir o consumo real.
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = tostring(var.budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.email.id]
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.apis]
}
