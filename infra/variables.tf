variable "project_id" {
  description = "ID do projeto GCP dedicado."
  type        = string
}

variable "region" {
  description = "Região de todos os recursos (free tier do GCS só vale nos EUA)."
  type        = string
  default     = "us-central1"
}

variable "env" {
  description = "Ambiente: dev ou prod. Em dev os datasets têm expiração de partição."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env deve ser dev ou prod."
  }
}

variable "billing_account_id" {
  description = "ID da conta de faturamento (formato XXXXXX-XXXXXX-XXXXXX)."
  type        = string
}

variable "budget_amount" {
  description = "Valor do alerta de orçamento mensal."
  type        = number
  default     = 1
}

variable "budget_currency" {
  description = "Moeda do orçamento; precisa ser a mesma da conta de faturamento (USD ou BRL, por exemplo)."
  type        = string
  default     = "USD"
}

variable "alert_email" {
  description = "E-mail que recebe alertas de orçamento e de falha do pipeline."
  type        = string
}

variable "dev_partition_expiration_days" {
  description = "Expiração padrão de partição em dev. Maior que 365 para o backfill de 12 meses sobreviver."
  type        = number
  default     = 400
}

variable "force_destroy_buckets" {
  description = "Permite terraform destroy apagar buckets com objetos (útil em dev)."
  type        = bool
  default     = true
}

variable "generator_image" {
  description = "Imagem do gerador (escrita por `make push` em images.auto.tfvars). Sem imagem, o job não é criado."
  type        = string
  default     = null
}

variable "loader_image" {
  description = "Imagem do loader + dbt (escrita por `make push` em images.auto.tfvars)."
  type        = string
  default     = null
}
