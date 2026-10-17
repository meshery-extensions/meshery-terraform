# ADR 0002: Include Terraform mode in component identity

- Status: Proposed
- Date: 2026-10-16
- Decision issue: ISSUE_0002
- Context: [architecture.md section 6.2, S3](../architecture.md#62-schema-changes-in-order-mesheryschemas-first), [findings](../../findings/README.md)

## Context

In the four measured providers, 1,050 type names exist both as a managed resource and as a data source (396 in AWS alone, for example `aws_s3_bucket`). Meshery component identity today is effectively model plus `component.kind`, so a naive import collides.

## Decision (proposed)

Add a typed `iac` object to component metadata in `meshery/schemas` (`engine`, `mode` = `managed` | `data` | `ephemeral`, `address`, `providerConfigKey`, `schemaVersion`, `instanceKey`, raw `count` / `forEach` expressions), and make `mode` part of uniqueness.

Two options need a choice:

- **A. Mode-qualified kind**: `component.kind` = `data.aws_s3_bucket` for data sources. Simple and visible; diverges from Terraform's type name.
- **B. Uniqueness includes `iac.mode`**: `kind` stays the Terraform type; registry keys on (model, kind, mode). Exact mapping; requires registry and lookup changes.

Recommendation: B if registry changes are acceptable, otherwise A.

## Consequences

- Must land before any provider import (Phase 1).
- Also formalizes `dependsOn` as a typed metadata property (S4), which the planner already reads.
