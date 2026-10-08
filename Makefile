TF := terraform -chdir=infra

PROJECT_ID := $(shell sed -n 's/^project_id *= *"\(.*\)"/\1/p' infra/terraform.tfvars 2>/dev/null)
REGION := us-central1
REGISTRY := $(REGION)-docker.pkg.dev/$(PROJECT_ID)/pipeline
# Tag = commit atual; "-dirty" quando há mudanças não commitadas (inclusive arquivos novos)
# no código das imagens.
TAG := $(shell git rev-parse --short HEAD)$(shell test -z "$$(git status --porcelain -- generator loader dbt)" || echo -dirty)
RUN_DATE ?= $(shell date -u -d yesterday +%F)

.PHONY: tf-init tf-fmt tf-validate tf-plan tf-apply \
	test lint generate-local load-local build push run-generator run-loader run-day

# --- Terraform ---------------------------------------------------------------

tf-init:
	$(TF) init

tf-fmt:
	$(TF) fmt -recursive

tf-validate:
	$(TF) validate

tf-plan:
	$(TF) plan -out=tfplan

# Aplica somente o plan revisado por tf-plan.
tf-apply:
	$(TF) apply tfplan

# --- Qualidade do código -----------------------------------------------------

test:
	cd generator && uv run pytest -q
	cd loader && uv run pytest -q

lint:
	cd generator && uv run ruff check . && uv run ruff format --check .
	cd loader && uv run ruff check . && uv run ruff format --check .

# --- Execução local ----------------------------------------------------------

# Gera um dia em ./data (não toca na nuvem).
generate-local:
	cd generator && RUN_DATE=$(RUN_DATE) OUTPUT_URI=../data uv run telemetry-gen

# Carrega um dia já gravado no bucket Bronze e roda o dbt, com o seu login (ADC).
load-local:
	cd loader && RUN_DATE=$(RUN_DATE) GCP_PROJECT=$(PROJECT_ID) \
		BRONZE_BUCKET=$(PROJECT_ID)-bronze uv run telemetry-loader

# --- Imagens e Cloud Run -----------------------------------------------------

build:
	docker build --provenance=false -t $(REGISTRY)/generator:$(TAG) generator
	docker build --provenance=false -t $(REGISTRY)/loader:$(TAG) -f loader/Dockerfile .

# Publica as imagens e grava as tags em infra/images.auto.tfvars (lido pelo tf-plan).
push: build
	docker push $(REGISTRY)/generator:$(TAG)
	docker push $(REGISTRY)/loader:$(TAG)
	printf 'generator_image = "%s"\nloader_image    = "%s"\n' \
		$(REGISTRY)/generator:$(TAG) $(REGISTRY)/loader:$(TAG) > infra/images.auto.tfvars

run-generator:
	gcloud run jobs execute generator --region $(REGION) --wait --update-env-vars RUN_DATE=$(RUN_DATE)

run-loader:
	gcloud run jobs execute loader --region $(REGION) --wait --update-env-vars RUN_DATE=$(RUN_DATE)

# Um dia completo na nuvem: gera e carrega. Ex.: make run-day RUN_DATE=2026-10-01
run-day: run-generator run-loader
