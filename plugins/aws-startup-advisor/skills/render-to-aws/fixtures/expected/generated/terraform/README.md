# Terraform baseline

This configuration implements the balanced selected infrastructure design. Capacity-preserving and right-sized totals are estimate scenarios, not separate Terraform stacks.

Run `terraform init -backend=false -input=false`, `terraform fmt -check -recursive .`, and `terraform validate` before configuring remote state. For external DNS, first request the public web certificate in ACM, create every DNS validation record at the external DNS provider, wait until ACM reports `Issued`, and then set the required `issued_certificate_arn`; this stack never attaches a pending certificate. Supply the distinct immutable `web_image`, `private_image`, and `worker_image` references for their bound Render source service IDs. Populate sensitive variables through an approved secret channel; never commit a tfvars file.

No AI or Workflow resources are generated: AI is `deferred_shared_ai_engine`, and Workflow generation is `conditional_workflow_generation_unsupported` for this fixture.
