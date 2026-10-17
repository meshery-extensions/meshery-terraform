# ADR 0004: Curated provider model subsets with lazy loading

- Status: Proposed
- Date: 2026-10-16
- Decision issue: [#4](https://github.com/meshery-extensions/meshery-terraform/issues/4)
- Context: [architecture.md sections 3.6 and 7.2](../architecture.md#36-measured-findings-that-constrain-the-design), [findings](../../findings/README.md)

## Context

Four providers produce 5,876 components and 35.6 MB of schema; the worst component schema is 3.8 MB. Eager boot-time registration of whole providers is not viable for registry size, boot time, or form rendering.

## Decision (proposed)

1. A MeshKit `terraform` registrant generator turns provider schemas into models (approach 4.A).
2. Ship curated static models at pinned versions for `kubernetes`, `aws`, `google`, `azurerm`, `random`, starting from the most used resource types.
3. Register other types lazily, on demand (when imported or searched).
4. Deduplicate repeated nested subtrees with `$ref`; render nested blocks collapsibly.
5. Enrich descriptions from registry documentation where schemas lack them.
6. Retention: keep the latest N minor provider versions; generate others on demand.

## Consequences

- Who curates, and by what usage signal, needs an owner.
- Registry must support lazy model materialization.
