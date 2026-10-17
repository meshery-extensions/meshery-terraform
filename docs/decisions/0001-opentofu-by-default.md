# ADR 0001: OpenTofu by default; Terraform CLI only as a user-supplied binary

- Status: Proposed
- Date: 2026-10-16
- Decision issue: ISSUE_0001
- Context: [architecture.md section 7.1](../architecture.md#71-licensing-bsl-vs-mpl)

## Context

Terraform CLI 1.6.0 and later is licensed BSL 1.1. Its additional use grant excludes offering the work "on a hosted or embedded basis" to compete with the licensor's paid versions. OpenTofu, `hashicorp/hcl`, `terraform-json`, `terraform-exec`, `terraform-plugin-go`, and providers are MPL-2.0.

## Decision (proposed)

1. Build only on MPL-2.0 libraries.
2. Ship, bundle, and host only OpenTofu as the execution engine.
3. Self-hosted users may point Meshery at a Terraform binary they install themselves.
4. Record the provider license in generated model metadata (schema change S9).
5. Do not persist raw state by default (see architecture section 7.3).

## Consequences

- Removes BSL risk from the engineering critical path.
- Some users standardized on Terraform may see small engine divergence; record engine and version per design.

## Open questions for counsel

- Does a paid Layer5 Cloud or Kanvas tier that runs plan/apply count as a "competitive offering"?
- Terms for bulk programmatic provider downloads from `registry.terraform.io` vs `registry.opentofu.org`.
