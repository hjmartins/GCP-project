# Criação de duas identidades, com permissões mínimas para o seu papel:
# - scheduler-invoker: inicia a execução do workflow.
# - workflow-runner: executa os Cloud Run Jobs.
# Foi decidido criar duas identidades separadas para que o workflow possa ser invocado por
# um terceiro (ex.: Cloud Scheduler) sem que este tenha acesso à execução dos jobs em si.

resource "google_service_account" "workflow" {
  account_id   = "workflow-runner"
  display_name = "Workflow Runner"

  depends_on = [google_project_service.apis]
}

# Papel dado só nos jobs do pipeline, não no projeto inteiro. Os nomes vêm dos próprios
# recursos de job: o Terraform cria os jobs antes, e um job sem imagem (count = 0) é ignorado.
resource "google_cloud_run_v2_job_iam_member" "workflow_runs_jobs" {
  for_each = toset(concat(
    google_cloud_run_v2_job.generator[*].name,
    google_cloud_run_v2_job.loader[*].name,
  ))

  name     = each.value
  location = var.region
  role     = "roles/run.jobsExecutorWithOverrides"
  member   = google_service_account.workflow.member
}

# O connector do Cloud Run dispara o job e depois acompanha a operação até terminar, o que
# exige run.operations.get. O papel pronto com essa permissão (roles/run.viewer) lê tudo do
# Cloud Run; o papel customizado dá só o necessário. Operações não têm IAM por recurso,
# então vai no projeto.
resource "google_project_iam_custom_role" "run_operations_reader" {
  role_id     = "runOperationsReader"
  title       = "Cloud Run Operations Reader"
  description = "Só acompanha operações do Cloud Run (usado pelo connector do Workflows)."
  permissions = ["run.operations.get"]
}

resource "google_project_iam_member" "workflow_reads_run_operations" {
  project = var.project_id
  role    = google_project_iam_custom_role.run_operations_reader.id
  member  = google_service_account.workflow.member
}

# sys.log grava no Cloud Logging como a conta do workflow (logs de sucesso e de falha).
resource "google_project_iam_member" "workflow_writes_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = google_service_account.workflow.member
}

resource "google_service_account" "scheduler" {
  account_id   = "scheduler-invoker"
  display_name = "Scheduler Invoker"

  depends_on = [google_project_service.apis]
}

# O Workflows não tem IAM por workflow no Terraform, então o papel vai no projeto:
# esta conta pode iniciar qualquer workflow do projeto (hoje só existe o daily-pipeline).
resource "google_project_iam_member" "scheduler_invokes_workflows" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = google_service_account.scheduler.member
}

# Deploy do pipeline diário. O YAML fica em workflows/ para ser lido e revisado como código.
resource "google_workflows_workflow" "daily_pipeline" {
  name                = "daily-pipeline"
  region              = var.region
  description         = "Gerador → loader (staging + dbt build) para um run_date."
  service_account     = google_service_account.workflow.id
  source_contents     = file("${path.module}/../workflows/daily_pipeline.yaml")
  deletion_protection = false
  labels              = local.labels

  depends_on = [google_project_service.apis]
}
