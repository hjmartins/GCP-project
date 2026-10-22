# Camada fria: Iceberg escrito pelo archiver (PyIceberg) no bucket frio e lido pelo BigQuery
# como tabela externa BigLake. A tabela Iceberg gerenciada pelo BigQuery foi descartada por
# custo: a manutenção automática é cobrada em DCUs e a exportação de metadados usa slots
# Enterprise, fora do free tier. Aqui o BigQuery só lê; o custo é o do GCS (Standard) e das
# consultas (dentro do 1 TB grátis).

# Conexão do BigQuery com o GCS. O Google cria uma conta de serviço só dela, que lê os
# arquivos da tabela externa em nome de quem consulta.
resource "google_bigquery_connection" "biglake" {
  connection_id = "biglake"
  location      = var.region
  friendly_name = "BigLake (camada fria)"
  description   = "Leitura das tabelas Iceberg externas no bucket frio."

  cloud_resource {}

  depends_on = [google_project_service.apis]
}

# A conexão só lê: quem escreve os arquivos é o archiver (pipeline-runner, objectAdmin no
# bucket frio desde a fase 0).
resource "google_storage_bucket_iam_member" "biglake_reads_cold" {
  bucket = google_storage_bucket.cold.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_bigquery_connection.biglake.cloud_resource[0].service_account_id}"
}

# O archiver recria a tabela externa apontando para o metadata.json novo, e para isso precisa
# usar a conexão. Papel dado só nesta conexão.
resource "google_bigquery_connection_iam_member" "pipeline_uses_biglake" {
  location      = google_bigquery_connection.biglake.location
  connection_id = google_bigquery_connection.biglake.connection_id
  role          = "roles/bigquery.connectionUser"
  member        = google_service_account.pipeline.member
}

# CREATE EXTERNAL TABLE ... WITH CONNECTION exige bigquery.connections.delegate (a conta delega
# a leitura dos arquivos à conta da conexão). O connectionUser não tem essa permissão, e o papel
# pronto que tem (connectionAdmin) também permite alterar e apagar a conexão: daí o papel
# customizado só com o delegate, dado só nesta conexão.
resource "google_project_iam_custom_role" "connection_delegate" {
  role_id     = "bigqueryConnectionDelegate"
  title       = "BigQuery Connection Delegate"
  description = "Só delega o uso de uma conexão (criar tabela externa WITH CONNECTION)."
  permissions = ["bigquery.connections.delegate"]
}

resource "google_bigquery_connection_iam_member" "pipeline_delegates_biglake" {
  location      = google_bigquery_connection.biglake.location
  connection_id = google_bigquery_connection.biglake.connection_id
  role          = google_project_iam_custom_role.connection_delegate.id
  member        = google_service_account.pipeline.member
}

output "biglake_connection_id" {
  description = "Usado no WITH CONNECTION da tabela externa."
  value       = google_bigquery_connection.biglake.id
}

output "biglake_connection_sa" {
  value = google_bigquery_connection.biglake.cloud_resource[0].service_account_id
}
