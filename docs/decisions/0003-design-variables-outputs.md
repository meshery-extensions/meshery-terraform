# ADR 0003: Typed design-level variables and outputs

- Status: Proposed
- Date: 2026-10-16
- Decision issue: [#3](https://github.com/meshery-extensions/meshery-terraform/issues/3)
- Context: [architecture.md sections 3.2 and 6.2, S6](../architecture.md#32-variables-and-outputs-the--in-the-brief)

## Context

Terraform modules are parameterized by `variable` blocks and expose `output` blocks. Meshery designs have no typed inputs or outputs, so a module cannot import as a reusable design, and designs cannot wire into one another.

## Decision (proposed)

Add `variables` and `outputs` to the design construct (`schemas/constructs/v1beta3/design/design.yaml` and the design payload in `api.yml`), each typed (JSON Schema), with `sensitive`, `ephemeral`, `default`, `description`, and validation rules. Component configuration may reference a variable through an opaque expression wrapper (`x-iac-expr`).

Also adopt vendor-neutral JSON Schema extensions (`x-iac-computed`, `x-iac-sensitive`, `x-iac-write-only`, `x-iac-ephemeral`, `x-iac-nesting-mode`, `x-iac-unknown`) documented in meshery/schemas (S5).

## Consequences

- Unblocks module import and the Patterns roadmap.
- Useful beyond Terraform (Helm values, Pulumi config).
- If added to a published schema version in a non-additive way, bump the version.
