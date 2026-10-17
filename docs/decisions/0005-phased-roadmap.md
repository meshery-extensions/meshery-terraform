# ADR 0005: Phased, schema-first roadmap order

- Status: Proposed
- Date: 2026-10-16
- Decision issue: ISSUE_0005
- Context: [architecture.md section 6.1](../architecture.md#61-phases)

## Decision (proposed)

| Phase | Deliverable |
| --- | --- |
| 0 | Schema RFC in `meshery/schemas` (S1 to S7, S9) |
| 1 | Models generated from provider schemas (curated, lazy) |
| 2 | HCL and plan-JSON import into designs; references and `depends_on` become relationships; source preserved |
| 3 | Semantic relationships and plan-time policy checks |
| 4 | Read-only state and drift view in Operator mode |
| 5 | Exact round-trip HCL export (PR-based via GitHub connection) |
| 6 | Orchestration: run hand-off first, native plan/apply later (ADR 0006) |
| Parallel | `terraform-provider-meshery` |

## Rationale

Phases 1 to 4 are read-mostly, deliver the highest assumed user value (visualize, understand, relate Kubernetes and cloud on one canvas) with low liability, and build the intermediate representation that export and orchestration need. Orchestration last keeps the BSL and secrets questions off the critical path.

## Alternatives

- Export first (design to HCL): attractive for greenfield users but needs fidelity work that depends on import.
- Orchestrator first: highest competitive overlap (HCP Terraform, Spacelift, env0) and highest liability.
