TF := terraform -chdir=infra

.PHONY: tf-init tf-fmt tf-validate tf-plan tf-apply

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
