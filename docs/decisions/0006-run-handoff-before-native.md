# ADR 0006: Hand off runs to the user's existing runner before native plan/apply

- Status: Proposed
- Date: 2026-10-16
- Decision issue: ISSUE_0006
- Context: [architecture.md section 4.E](../architecture.md#4e-meshery-as-a-terraform-orchestrator-planapply-runner-remote-backend)

## Context

Most Terraform users already run plan/apply in a runner (HCP Terraform, Spacelift, env0, Atlantis, GitHub Actions) that holds state, credentials, and encryption keys. Running plan/apply inside Meshery duplicates that and puts raw state and secrets in Meshery.

## Decision (proposed)

1. First, a delegating adapter (E'): Meshery triggers the user's runner (via a `terraform-runner` connection) or opens a PR, then ingests the redacted plan JSON for overlay and policy checks.
2. Later, an optional full adapter running OpenTofu via `terraform-exec` over the Deployment Engine adapter path, with an `iacRun` construct (S8) and an optional HTTP backend.

## Consequences

- No raw state or plan persisted by Meshery in the first iteration.
- Mixed Kubernetes plus Terraform deploys wait for the native adapter.
