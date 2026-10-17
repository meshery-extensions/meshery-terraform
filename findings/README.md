# Findings: provider schema scale

Measured on 2026-10-16 with OpenTofu 1.13.1 against the four providers in [main.tf](main.tf). Raw dumps (35.6 MB schema, 32 MB converted JSONL) are **not committed**; regenerate them with [scripts/regenerate.sh](scripts/regenerate.sh) (outputs land in `findings/out/`, which is gitignored). [scripts/stats.py](scripts/stats.py) recomputes every number below.

| Provider (version) | Resources | Data sources | Ephemeral | Functions | Resource attributes (incl. nested) | Descriptions present | Sensitive attrs | Resource/data source name collisions | Largest resource (attrs) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| aws (6.69.1) | 1,735 | 685 | 11 | 4 | 109,786 | 5% | 264 | 396 | `aws_wafv2_web_acl_rule` (21,265) |
| google (8.7.0) | 1,375 | 471 | 6 | 6 | 31,972 | 75% | 265 | 298 | `google_container_cluster` (577) |
| azurerm (5.10.0) | 1,106 | 396 | 2 | 2 | 23,328 | 8% | 718 | 334 | `azurerm_kubernetes_cluster` (273) |
| kubernetes (3.3.0) | 81 | 27 | 2 | 3 | 8,906 | 97% | 5 | 22 | `kubernetes_stateful_set` (548) |
| **Total** | **4,297** | **1,579** | 21 | 15 | 173,992 | | 1,252 | **1,050** | |

Converted with [the prototype](../prototype/tf2meshery/) (computed-only attributes dropped):

- 5,876 component definitions, 32 MB JSONL.
- Median `component.schema` 796 bytes, p95 about 7.7 KB.
- Largest: `aws_wafv2_web_acl_rule` 3.8 MB, `aws_wafv2_web_acl` 1.9 MB, `aws_quicksight_dashboard` 1.8 MB (recursive nested blocks fully unrolled).

## What these numbers drive

- 1,050 name collisions between resources and data sources: component identity must include mode. See [ADR 0002](../docs/decisions/0002-component-identity-mode.md).
- Megabyte schemas and about 5,900 components for four providers: curated subsets, lazy loading, and `$ref` dedup. See [ADR 0004](../docs/decisions/0004-curated-models-lazy-loading.md).
- Sparse AWS and Azure descriptions: palette tooltips need registry docs ingestion, not just schema.

## Reproduce

```bash
# needs OpenTofu (or set TOFU=terraform) and Python 3
./findings/scripts/regenerate.sh
```
