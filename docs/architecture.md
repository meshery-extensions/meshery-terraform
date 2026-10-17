# Terraform and OpenTofu in Meshery and Kanvas: Architecture Deep Dive

- Author: Grok Bot, for Yi Nuo (Layer5 maintainer)
- Date: 2026-10-16 (America/Chicago)
- Status: Draft for maintainer review, not an accepted design
- Scope: Integrate Terraform (and OpenTofu) into Meshery first, then surface it in Kanvas
- Standing rule honored: every feature below starts as a JSON Schema / OpenAPI change in `meshery/schemas`, and reuses existing Meshery, MeshKit, and Kanvas code paths before adding new ones

---

## 0. TL;DR

1. Terraform and Meshery line up well on the *declaration* side: a provider is a model, a resource type is a component definition, a resource block is a component declaration in a design, a module is a design (or a future Pattern), and expression references plus `depends_on` are relationships plus Meshery's existing `metadata.dependsOn` ordering.
2. They do not line up on the *runtime* side. Terraform's truth is a state file, a plan, and a provider process; Meshery's truth is a design, MeshSync's view of Kubernetes, and a per-component deployment engine. State, plan, unknown values, `count`/`for_each` expansion, and secrets in state have no Meshery equivalent today. Meshery's semantic relationships, mutator/mutated patches, visual layout, annotations, and live Kubernetes operation have no Terraform equivalent.
3. Real provider schemas are large. I dumped `providers schema -json` for aws, google, azurerm, and kubernetes with OpenTofu 1.13.1: 4,297 resource types plus 1,579 data sources, 35.6 MB of schema, and one AWS resource that converts to a 3.8 MB JSON Schema. Importing "all of Terraform" into the registry naively is not viable.
4. Recommended path: schema-first RFC in `meshery/schemas`, then (1) a MeshKit `terraform` registrant generator that turns provider schemas into curated, lazily loaded models, (2) HCL and plan-JSON import into designs with references turned into relationships and the original source preserved byte-for-byte, (3) design-to-HCL export with round-trip tests, (4) state and refresh-only plan ingestion as a read-only Operator view with drift overlay, and only then (5) a Meshery adapter that runs OpenTofu (default) or a user-supplied Terraform binary for plan/apply.
5. License posture: build on MPL-2.0 pieces (OpenTofu, `hashicorp/hcl`, `terraform-json`, `terraform-exec`, `terraform-plugin-go`) and treat bundling or hosting the BSL-licensed Terraform CLI (1.6.0 and later) as a legal-review item, not an engineering default.

---

## 1. Method and evidence

What I actually looked at (all fetched or run on 2026-10-16):

| Source | What I used it for |
| --- | --- |
| docs.meshery.io concepts: [Models](https://docs.meshery.io/concepts/logical/models), [Components](https://docs.meshery.io/concepts/logical/components), [Relationships](https://docs.meshery.io/concepts/logical/relationships), [Designs](https://docs.meshery.io/concepts/logical/designs), [Patterns](https://docs.meshery.io/concepts/logical/patterns), [Policies](https://docs.meshery.io/concepts/logical/policies), [Registry](https://docs.meshery.io/concepts/logical/registry), [Connections](https://docs.meshery.io/concepts/logical/connections), [Credentials](https://docs.meshery.io/concepts/logical/credentials), [Environments](https://docs.meshery.io/concepts/logical/environments), [Workspaces](https://docs.meshery.io/concepts/logical/workspaces), [Deployment Engine](https://docs.meshery.io/concepts/architecture/deployment-engine) | Meshery construct semantics |
| `meshery/schemas` at `eb7f8e71` (master, 2026-10-15) | `component.yaml`, `design.yaml`, `design/api.yml`, `model.yaml`, `relationship.yaml`, `core/api.yml` (`IaCFileTypes`), `AGENTS.md` (dual-schema and casing rules) |
| `meshery/meshkit` at `919c7d5d` (2026-10-08) | `generators/generator.go` (registrant switch), `generators/models/interfaces.go` (`Package.GenerateComponents`), `files/identification.go` and `files/conversion.go` (IaC file identification and conversion pipeline), `converter/` (K8s and Helm exporters) |
| `meshery/meshery` `server/models/pattern/planner/planner.go` | How `dependsOn` is read today |
| [meshery/meshery#4051](https://github.com/meshery/meshery/issues/4051) "Terraform provider for meshery" | Prior community ask (open, milestone v1.2.0, labeled `terraform`) |
| [Kanvas docs](https://docs.layer5.io/kanvas/) | Designer vs Operator modes, hosted vs self-hosted capabilities |
| Terraform docs: [`providers schema`](https://developer.hashicorp.com/terraform/cli/commands/providers/schema), [JSON output format](https://developer.hashicorp.com/terraform/internals/json-format), [`depends_on`](https://developer.hashicorp.com/terraform/language/meta-arguments/depends_on), [sensitive data in state](https://developer.hashicorp.com/terraform/language/state/sensitive-data), [http backend](https://developer.hashicorp.com/terraform/language/backend/http), [CDKTF (deprecated)](https://developer.hashicorp.com/terraform/cdktf) | Terraform construct semantics |
| OpenTofu: [state and plan encryption](https://opentofu.org/docs/language/state/encryption/), repo license via GitHub API (MPL-2.0), latest release v1.13.1 (2026-10-01) | Engine choice, secrets story |
| Terraform `LICENSE` on `main` (BSL 1.1, "Terraform Version 1.6.0 or later", licensor now IBM); HashiCorp [BSL page](https://www.hashicorp.com/bsl) and [license FAQ](https://www.hashicorp.com/license-faq) via search excerpts (the FAQ page itself returned a bot checkpoint to my fetcher) | License analysis |

Experiments I ran on the box (reproducible; files left in `/workspace/tfscale` and `/workspace/tf2meshery`):

1. `tofu init && tofu providers schema -json` for `hashicorp/aws` v6.69.1, `hashicorp/google` v8.7.0, `hashicorp/azurerm` v5.10.0, `hashicorp/kubernetes` v3.3.0 to measure schema scale.
2. A roughly 100 line prototype converter, `tf2meshery/tfschema_to_jsonschema.py`, that maps a provider block schema to a Meshery `components.meshery.io/v1beta3`-shaped component definition with JSON Schema draft-07 in `component.schema`.
3. A small `random`/`local` config planned with `tofu plan -out` and `tofu show -json` to observe references, `depends_on`, `for_each` instance keys, and sensitivity propagation in plan JSON.

Uncertainty markers used below: **[verified]** means I read it in a source or observed it; **[inferred]** means a reasoned conclusion; **[unverified]** means plausible but I did not confirm it.

---

## 2. Assumptions about what users value most

Each assumption is stated with how it moves the design. Getting these wrong changes the phase order, so they are the first thing to validate with users.

| # | Assumption | Confidence | How it shifts the design |
| --- | --- | --- | --- |
| A1 | **Existing Terraform stays the source of truth.** Teams with Terraform estates will not move ownership of infrastructure into Meshery designs. They want to *see*, *review*, and *reason about* it in Kanvas. | High [inferred] | Import and visualization before authoring. Designs created from HCL carry a source binding (reuse `DesignSourceBinding` / `refreshPatternFromSource`) and Meshery treats the repo as authoritative. Export to HCL is a convenience, not the primary path. |
| A2 | **Plan review is the highest-value moment.** The riskiest Terraform step is reading a plan. A visual diff of create/update/replace/delete with blast radius is more valuable than a prettier static diagram. | High [inferred]; Pluralith, Rover, Brainboard, and HCP Terraform all invest here [verified, Section 5] | Plan-JSON ingestion and a "plan overlay" in Kanvas get prioritized ahead of a full provider-schema palette. |
| A3 | **One canvas across Kubernetes and cloud.** Meshery users already model Kubernetes richly; the gap is cloud resources and their links to cluster workloads (IAM role to ServiceAccount, RDS to Secret, LB to Service). | High [inferred]; Meshery already ships ACK, Azure, and Kubeform-based cloud models [verified: [models list](https://docs.meshery.io/extensions/models/)] | Cross-model relationships (Terraform model to Kubernetes model) matter more than intra-provider relationships. Relationship evaluation only loads relationships from models already in the design [verified], so mixed designs work, but cross-model relationship definitions must be authored. |
| A4 | **Nobody wants Meshery holding their state or cloud secrets by default.** State contains secrets in plaintext unless engine-encrypted [verified]. | High [inferred] | Default to read-through: Meshery reads state from the user's backend at view time using a Meshery Credential, redacts using `sensitive_values`, and does not persist raw state. Hosting a state backend is opt-in and later. |
| A5 | **OpenTofu and Terraform must both work.** Users are split, and Layer5 cannot pick for them. | High [inferred] | Engine is a design-level setting (`engine: opentofu` or `terraform`) with OpenTofu as the engine Layer5 ships. Parse with MPL libraries that both engines' file formats share; record engine version in metadata. |
| A6 | **Fidelity beats breadth.** A user who imports a module and gets mangled HCL back will not try again. | High [inferred] | Round-trip strategy (Section 4.I) is a gating requirement: unchanged blocks re-emit byte-identical; edits are applied surgically with `hclwrite`. |
| A7 | **Policies and relationships are Meshery's differentiator, not running Terraform.** Spacelift, env0, HCP Terraform, and Massdriver already run Terraform [verified, Section 5]. | Medium [inferred] | Orchestration (plan/apply) is a late phase and possibly an adapter that delegates to existing runners. Investment goes to semantic relationships, policy evaluation over plans, and collaborative review. |
| A8 | **Designers are not all Terraform experts.** Platform teams publish modules; app teams consume them via forms. | Medium [inferred]; Massdriver and Brainboard both sell this [verified] | Module-as-Pattern (single component with typed inputs and outputs) is a first-class target, aligned with Meshery's Patterns roadmap [verified: Patterns are "planned for v0.9.0"]. |

If A1 is false (users *do* want Meshery to own infrastructure), Approaches E and F move earlier and Meshery must take state custody seriously from day one.

---

## 3. Construct mapping

### 3.1 Congruent constructs

| Terraform / OpenTofu | Meshery | Fit | Notes |
| --- | --- | --- | --- |
| Provider (`registry.terraform.io/hashicorp/aws` at a version) | Model (`name` + `version`), registered by a Registrant | Strong | Models with the same `name` and `version` are duplicates [verified], so provider version maps cleanly to model version. The registrant would be a new `terraform-registry` / `opentofu-registry` connection kind; MeshKit's generator switch only knows `artifacthub` and `github` today [verified]. |
| Provider source host (registry) | Registrant (a Connection) | Strong | A registrant is a Connection that sourced entities [verified]. |
| Resource type schema (`resource_schemas.aws_s3_bucket`) | Component definition (`component.kind`, `component.version`, `component.schema`) | Strong | Block schema converts to JSON Schema mechanically (prototype works). The per-resource `schema.version` (int64) can feed `component.version`. |
| Data source schema (`data_source_schemas.aws_s3_bucket`) | Component definition | Partial | Collides with the resource of the same name: components with the same `kind`, `apiVersion`, `model.name` are duplicates [verified]. In AWS v6.69.1, **396 names exist as both a resource and a data source** [verified, measured]. Needs a mode-qualified kind (for example `data.aws_s3_bucket`) or a mode field in the uniqueness key. |
| Resource block in configuration (`resource "aws_s3_bucket" "logs" {}`) | Component declaration in a design (`id`, `displayName`, `configuration`) | Strong | Terraform address `aws_s3_bucket.logs` maps to a stable component id plus displayName. |
| Module (directory with variables/outputs) | Design; and when consumed, a future Pattern ("a complex design is represented as a single component") | Strong, with a gap | Designs can be imported, versioned, merged [verified]. Pattern semantics are the right target for `module` blocks, but Patterns are still roadmap [verified]. |
| `depends_on` | Component `metadata.dependsOn` (by component name), honored by the deployment planner | Strong | Meshery Server already reads `dependsOn` from component metadata `additionalProperties`, builds a DAG, rejects cycles, withholds dependents on failure [verified in `planner.go` and Deployment Engine docs]. It is not a typed schema property yet. |
| Implicit references (`aws_iam_role.app.arn` used in another resource) | Relationship `kind: edge`, `type: non-binding`, `subType: reference` with `mutatorRef` / `mutatedRef` paths | Strong | Meshery documents edge-reference as "one component refers to another by name, identifier, type, or scope", with patches copying values between paths [verified]. Plan JSON exposes `references` per expression [verified, observed]. |
| Provider configuration block (`provider "aws" { region = ... }`, aliases) | Connection plus Credential, grouped by Environment | Medium | Credentials authenticate Connections; Environments group Connections; Workspaces share Environments [verified]. Provider aliases (multiple regions or accounts) map to multiple Connections. |
| Terraform workspace (`terraform workspace`), or a root module per env | Meshery Environment | Medium | Name collision only: a Meshery *Workspace* is a collaboration and access-control space [verified], not a Terraform workspace. Map Terraform workspaces to Environments, never to Meshery Workspaces. |
| `lifecycle { prevent_destroy }` | Component capability or policy | Weak | No direct Meshery field; could be a policy that blocks undeploy. |
| `check`, `precondition`, `postcondition` | Policy (validation) | Medium | Both are declarative assertions; Meshery policies are relationship-centric today [verified]. |

### 3.2 Variables and outputs (the "?" in the brief)

There is no first-class Meshery construct for typed design inputs or outputs today. The nearest pieces:

- Patterns are described as "replacing the values of the variables in the design with the values provided by another user" [verified, Designs page], which implies a variable concept that is not in the schemas I read [inferred].
- Relationship patches move values between components (`mutatorRef` to `mutatedRef`) [verified]. That is a wiring mechanism, not a declared interface.

Proposal: `variables` and `outputs` become typed design-level properties in `meshery/schemas` (Section 6.2, change S6). A Terraform `variable` maps to a design input with JSON Schema type, default, `sensitive`, `ephemeral`, and validation; an `output` maps to a design output whose value references a component path. When a design is used as a Pattern, those become the Pattern component's `component.schema` and its exported paths, which in turn are what relationships can target. This one addition unlocks module import, Pattern authoring, and Spacelift-style cross-stack wiring.

### 3.3 Incongruent constructs (same word, different meaning, or different shape)

| Concept | Terraform meaning | Meshery meaning | Consequence |
| --- | --- | --- | --- |
| Workspace | Named state instance of one configuration | Team collaboration and access-control space | Never map one to the other. |
| Pattern | Not a Terraform term | Templated design as one component (roadmap) | Use for modules. |
| Policy | Sentinel or OPA on plans (in runners) | Relationship evaluation engine, a native Go port of the Rego engine, also compiled to WASM for the browser [verified] | Meshery policies evaluate designs, not plans. A "plan policy" is a new input type for the same engine. |
| Dependency | Ordering for create/update; inverted for destroy | Ordering for deploy; inverted for undeploy, plus withholding semantics on failure [verified] | Close enough to map; Meshery's per-component "withheld" reporting is richer than Terraform's stop-on-error. |
| Status | State attributes are whatever the provider returned | Component `status` is a registry status (enabled, ignored, ...); live status comes from MeshSync | Live status for Terraform-managed cloud objects needs a new source (state or provider read). |
| Nested blocks | `block_types` with `nesting_mode` single/list/set/map, `min_items`/`max_items` | JSON objects and arrays | Converts, but `set` semantics (unordered, identity by value) and `map` blocks need vendor extensions to round-trip [verified in schema format]. |
| Types | cty types incl. `dynamic`, `object`, `tuple` | JSON Schema | `dynamic` becomes `{}` (anything). Lists, sets, tuples all lower to JSON arrays; maps and objects both lower to JSON objects, which Terraform's own JSON docs say "does lose some information" [verified]. |

### 3.4 Underlaps: what Terraform has that Meshery lacks

| Terraform capability | Meshery today | Gap severity | Bridging idea |
| --- | --- | --- | --- |
| **State** (authoritative record of real objects, ids, computed attributes, deposed objects) | Designs are desired state; MeshSync gives live state for Kubernetes only | High | Treat a state backend as a Connection; ingest `show -json` state into a read-only "observed design" (Approach D). Do not store raw state by default. |
| **Plan** (`actions`, `replace_paths`, `action_reason`, `after_unknown`, `resource_drift`, `relevant_attributes`) [verified] | Dry-run against the Kubernetes API only; dry-run "does not exercise the adapter path" [verified] | High | Plan-JSON overlay on a design: per-component action badges, replace reasons, unknown-after-apply markers, drift section. |
| **Drift** | No cloud drift view | High | `plan -refresh-only -json` reports drift without proposing config changes [inferred from refresh-only mode referenced on the HCP health page]. |
| **Unknown values** ("known after apply") | Every configuration value is known | Medium | Represent as a sentinel plus an `x-iac-unknown` marker; UI shows a placeholder; relationship patches must not copy unknowns. |
| **Data sources** (read-only lookups) | No read-only component concept | Medium | Component with `metadata.iac.mode: data` and a capability that marks it non-deployable; render with a distinct style. |
| **Ephemeral resources, write-only arguments** (TF 1.10+ / 1.11+) [verified] | None | Medium | Mark with `x-iac-ephemeral` / `x-iac-write-only`; never persist values in designs. 35 AWS attributes are write-only in v6.69.1 [measured]. |
| **`count` / `for_each` / `dynamic` blocks** | A component is one object | High | One component with a `replication` descriptor (raw expression preserved); expanded instances shown as a stacked node in Kanvas when a plan or state supplies instance keys. Terraform docs state `dynamic` block expressions are not included in configuration JSON [verified], so HCL parsing is needed for fidelity. |
| **Expressions, functions, locals, provider-defined functions** | Static values only | High | Keep expressions as opaque strings in an `x-iac-expr` wrapper; evaluate only in the engine. |
| **Provisioners** (`local-exec`, `remote-exec`) | None | Low | Preserve as opaque text; flag in validation. |
| **`moved`, `import`, `removed` blocks** | None | Medium | Preserve; `import` blocks are a hook for "adopt discovered resources" (Section 4.K). |
| **Backends and locking** | None | Medium | Connection kind `terraform-state`; optional Meshery HTTP backend later (Approach E). |
| **Provider plugin protocol (gRPC)** | Adapters over gRPC (Path B) [verified] | Opportunity | A Terraform adapter fits Path B with no deployment-engine change. |

### 3.5 Underlaps: what Meshery has that Terraform lacks

| Meshery capability | Terraform today | Value to Terraform users |
| --- | --- | --- |
| **Semantic relationships**: kinds (hierarchical, edge, sibling), types, subtypes, selectors, patch actions [verified] | Only a dependency graph (`terraform graph`) with no meaning attached | Kanvas can say "this policy grants this role access to this bucket", not just "A depends on B". |
| **Policy engine** that identifies, validates, and applies side effects to relationships, in-server and in-browser via WASM [verified] | Policy runs in runners (Sentinel/OPA) on plans | Interactive policy feedback while designing, before any plan exists. |
| **Non-semantic components and annotations** (`isAnnotation`) [verified] | Comments only | Documentation lives in the same artifact. |
| **Visual layout, styles, multiplayer editing, versioning, snapshots, embedding** [verified on Designs and Kanvas pages] | None | Review and onboarding. |
| **Live operation via MeshSync and Kubernetes controllers** [verified for Kubernetes] | Point-in-time state only | Day-2 view for cluster-side resources created by Terraform's kubernetes/helm providers. |
| **Per-component fulfillment routing** (each component's model registrant decides who applies it) [verified] | One engine per root module | A single design can mix Kubernetes components (applied by Meshery Server) with Terraform components (delegated to an adapter). This is the key architectural lever. |
| **Catalog, OCI packaging of models and designs** [verified] | Registry for providers and modules | Publish curated Terraform-backed Patterns to the Meshery Catalog. |

### 3.6 Measured findings that constrain the design

From the four-provider dump (OpenTofu 1.13.1, 2026-10-16) [all verified by measurement]:

| Provider (version) | Resources | Data sources | Ephemeral | Functions | Resource attributes (incl. nested) | Attr. descriptions present | Sensitive attrs | Largest resource (attrs) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| aws (6.69.1) | 1,735 | 685 | 11 | 4 | 109,786 | 5% | 264 | `aws_wafv2_web_acl_rule` (21,265) |
| google (8.7.0) | 1,375 | 471 | 6 | 6 | 31,972 | 75% | 265 | `google_container_cluster` (577) |
| azurerm (5.10.0) | 1,106 | 396 | 2 | 2 | 23,328 | 8% | 718 | `azurerm_kubernetes_cluster` (273) |
| kubernetes (3.3.0) | 81 | 27 | 2 | 3 | 8,906 | 97% | 5 | `kubernetes_stateful_set` (548) |

Converted with the prototype (computed-only attributes excluded, descriptions kept):

- 5,876 component definitions, 32 MB of JSONL for four providers.
- Median `component.schema` size 796 bytes, p95 about 7.7 KB, but the top three are 3.8 MB (`aws_wafv2_web_acl_rule`), 1.9 MB (`aws_wafv2_web_acl`), and 1.8 MB (`aws_quicksight_dashboard`), because deeply recursive nested blocks are fully unrolled in the provider schema.

Implications:

1. The registry must support **lazy, on-demand model loading** and **curated subsets**; eager boot-time registration of all providers is not viable [inferred].
2. Forms must handle schemas measured in megabytes; need collapsible nested blocks and `$ref`-based deduplication of repeated subtrees (the WAF schemas are highly repetitive) [inferred].
3. AWS and Azure provider schemas carry almost no descriptions. Good tooltips need registry documentation (markdown) linked or ingested, not just the schema [verified gap, inferred fix].
4. The data source vs resource name collision (396 in AWS) must be solved in the component identity scheme before import (Section 6.2, S3).
5. Sensitivity propagates: in my demo, `local_file.content` was marked sensitive in plan JSON only because it interpolated `random_password.result` [verified, observed]. Redaction must use the engine's `after_sensitive` / `sensitive_values`, not just the schema's static `sensitive` flag.
6. In my OpenTofu 1.13.1 test, the plan's `configuration.root_module.resources[]` entry for a `for_each` resource did not include a `for_each_expression` key, although Terraform's JSON format docs list it [verified observation; cause not investigated, and Terraform CLI not tested]. Instance keys (`local_file.cfg["a"]`) did appear in `resource_changes`. Do not rely on plan JSON alone for meta-argument fidelity; parse HCL too.

---

## 4. Architectural approaches

Each approach lists what it is, what it reuses, and its tradeoffs. They compose; Section 6 recommends a sequence.

### 4.A Provider-schema import to generate Meshery models

**What.** A new MeshKit registrant generator `terraform` (alias `opentofu`) implementing the existing `models.PackageManager` / `models.Package` interfaces (`GenerateComponents(group) ([]component.ComponentDefinition, error)`) [verified interface]. Input: provider source address plus version constraint. Steps: run `tofu init` in a scratch dir with a generated `required_providers` block, run `providers schema -json`, convert each resource, data, and ephemeral schema into a component definition, attach model metadata (provider source, version, plugin protocol, schema `format_version`). Wire it into `mesheryctl registry generate` and the spreadsheet-driven model pipeline that already exists [verified, Registry docs].

**Reuse.** `generators/generator.go` switch (add a case), `registry/model.go` `createNewRegistrant`, existing model OCI packaging, existing Registry UI.

**Pros.** Mechanical and complete; versioned 1:1 with providers; gives Kanvas a palette for every Terraform resource; works for community providers too.

**Cons.** Scale (Section 3.6); weak descriptions for aws and azurerm; no relationships for free; computed attributes, unknowns, and nesting modes need vendor extensions; provider release churn means many model versions [inferred].

**Variants.** (a) Curated static models shipped with Meshery for top providers at pinned versions; (b) dynamic models generated when a user connects a registry or imports a config that requires an unregistered provider, mirroring how Meshery already generates dynamic models from connected clusters [verified: "Dynamic Models: Generated at run-time"].

### 4.B HCL and plan-JSON import into designs

**What.** Extend MeshKit's `files.IdentifyFile` chain (which today tries Kubernetes manifest, Helm chart, Docker Compose, Kustomize, Meshery design [verified]) with a Terraform configuration detector (directory or archive containing `*.tf`, `*.tf.json`, `*.tofu`), plus plan-JSON and state-JSON detectors keyed on `format_version` and `planned_values` / `values`. Parse HCL with `hashicorp/hcl/v2` (MPL-2.0) for full fidelity, optionally enrich with `terraform-config-inspect` (MPL-2.0) for module metadata, and with plan JSON when available for resolved provider addresses and references.

**Mapping rules.** Each `resource` / `data` block becomes a component declaration; each `module` block becomes a nested design (local source) or a Pattern-like component (registry source); `variable` / `output` become design inputs and outputs (needs S6); references and `depends_on` become relationships (Approach H); `provider` blocks become required Connections in the design's metadata.

**Reuse.** `/api/pattern/import` and `MesheryPatternImportRequestBody` [verified]; the `designType` discriminator and `sourceContent` bytes on the stored design [verified]; `DesignSourceBinding` with `commitSha` for GitHub-backed designs and `refreshPatternFromSource` [verified].

**Pros.** Fastest route to value for A1 and A2 users; reuses import UX; preserves the original source.

**Cons.** Expressions do not become editable values; registry modules need fetching (network, auth); `dynamic` and `for_each` need HCL-level handling; layout must be auto-generated, so Kanvas auto-layout quality matters.

### 4.C Design to HCL export

**What.** A MeshKit converter next to the existing Kubernetes and Helm converters (`converter/k8s.go`, `converter/helm.go` [verified]) that emits a Terraform module from a design: `required_providers` from model metadata, one block per Terraform-model component, relationships rendered as references (edge-reference with a mutator path becomes `attr = other.path`) or `depends_on` (dependency-only edges), design inputs and outputs as `variable` / `output`.

**Pros.** Lets Kanvas be an authoring tool (Brainboard-style). Exports can go to Git through the existing GitHub integration.

**Cons.** Without round-trip discipline (4.I), exports of imported designs churn formatting and lose comments. Non-Terraform components in the same design (Kubernetes) need a policy: skip, emit via the `kubernetes` provider, or emit as sibling manifests.

### 4.D Terraform state ingestion as a discovered or live view

**What.** A Connection kind `terraform-state` (backend address plus Credential). Meshery reads state on demand (via `tofu show -json` against the backend), converts `values.root_module` (resources, `child_modules`, `index`, `provider_name`, `schema_version`, `values`, `sensitive_values` [verified format]) into a read-only "observed design", and shows it in Kanvas Operator mode next to the authored design. Drift: periodic `plan -refresh-only -json`, mapping `resource_drift` [verified field] to per-component drift badges.

**Reuse.** Connection lifecycle states (Discovered, Registered, Connected, Disconnected, and so on [verified]); Environments to group state connections; Operator mode's "scope to the resources a design deployed" concept [verified].

**Pros.** Works for estates Meshery did not create; no write risk; strong A2 and A3 value; a "live-ish" view Terraform itself lacks.

**Cons.** State is point-in-time, not live like MeshSync; reading state touches secrets (mitigate: never persist raw state, redact from `sensitive_values`, keep in memory, audit every read); many backends and auth schemes; OpenTofu-encrypted state requires key access [verified feature].

### 4.E Meshery as a Terraform orchestrator (plan/apply runner, remote backend)

**What.** A Meshery Adapter on Path B of the Deployment Engine (the registrant advertises host:port; Meshery Server delegates over gRPC [verified]) that owns Terraform-model components. On Deploy, Meshery Server routes those components to the adapter, which renders HCL (4.C), runs `init` and `plan`, posts the plan back for approval in Kanvas, then runs `apply`, streaming events. Use `hashicorp/terraform-exec` (MPL-2.0) to drive the CLI and `hashicorp/terraform-json` (MPL-2.0) to parse output. Optional: implement the documented HTTP backend protocol (GET/POST/DELETE plus LOCK/UNLOCK, 423 or 409 when locked [verified]) so Meshery can be a state store.

**Reuse.** Deployment Engine routing; dependency ordering and withholding, which already work across paths [verified]; events; Environments and Credentials for provider auth.

**Pros.** True "design, review, deploy" in one place; mixed Kubernetes plus cloud designs deploy in one action with correct ordering across paths.

**Cons.** Biggest scope and liability: concurrency, locking, long-running applies, partial failures, state custody, secrets, cost. Competes head-on with HCP Terraform, Spacelift, env0, Massdriver (A7). Dry-run today does not exercise the adapter path [verified], so "plan" needs its own UX. BSL exposure if Layer5 ships or hosts the Terraform CLI in a paid offering (Section 7).

**Lighter variant E' (recommended first).** A delegating orchestrator: the adapter does not run Terraform itself; it triggers runs in the user's existing runner (HCP Terraform, Spacelift, env0, GitHub Actions) and ingests the resulting plan JSON back into Kanvas for review. Lower liability, respects A1 and A7. [Runner APIs not verified in this doc.]

### 4.F A Meshery Terraform provider

**What.** `terraform-provider-meshery`, built with the Terraform Plugin Framework, exposing Meshery's own constructs as resources: `meshery_environment`, `meshery_workspace`, `meshery_connection`, `meshery_credential` (secret fields as write-only arguments), `meshery_design` (from file or OCI), `meshery_design_deployment`, `meshery_model`. This is what issue #4051 asked for in 2021 ("The state of meshery resources should be managed in state files") [verified].

**Pros.** Small, independent, high leverage for GitOps teams; the client can be generated from the `meshery/schemas` OpenAPI, which keeps it schema-first [inferred; generator tooling not verified]. Publishable to both the Terraform and OpenTofu registries.

**Cons.** Does not help visualize users' existing Terraform; it is the reverse direction. Low risk, so it can run in parallel with anything.

### 4.G OpenTofu embedded

**What.** Ship an engine with Meshery (container image, or download on demand with `opentofu/tofudl`, MPL-2.0 [verified]) so schema generation (4.A), import enrichment (4.B), and orchestration (4.E) work without the user installing anything. Linking OpenTofu as a Go library is possible in principle, but I found no stable public Go API for that [unverified]; shelling out to a pinned binary is the safer default.

**Pros.** Zero setup; MPL-2.0 avoids BSL questions; OpenTofu-only features such as state and plan encryption with KMS key providers [verified] help A4.

**Cons.** Engine divergence: features that exist in only one engine may not parse in the other [inferred]; users must be able to supply their own Terraform binary.

### 4.H Relationship inference from references

**What.** Turn Terraform's reference graph into Meshery relationships automatically, then let Meshery's policy engine add meaning.

1. Syntactic layer (always): for each expression with `references` (plan JSON) or traversals (HCL AST), emit `edge / non-binding / reference` with `mutatorRef` = source attribute path and `mutatedRef` = destination attribute path. Explicit `depends_on` becomes a dependency edge plus `metadata.dependsOn`.
2. Semantic layer (curated per provider): relationship definitions that recognize well-known pairs and upgrade them. Examples: `aws_iam_role_policy_attachment` as `edge / binding / permission` between `aws_iam_role` and `aws_iam_policy` (the attachment is the binding component, matching Meshery's 3-party binding shape [verified]); `aws_subnet` in `aws_vpc` as `hierarchical / parent / inventory`; `aws_security_group_rule` as `edge / non-binding / firewall`.
3. Cross-model layer: Terraform AWS IAM role to Kubernetes ServiceAccount (IRSA annotation), `aws_db_instance` endpoint to Kubernetes Secret, `aws_lb_target_group` to Kubernetes Service. These are what A3 users want.

**Reuse.** Relationship schema `relationships.meshery.io/v1beta3` and the evaluate endpoint `/api/registry/relationships/evaluate` [verified]; the browser WASM evaluator for instant feedback [verified].

**Pros.** Converts a bare DAG into a meaningful diagram; the semantic layer is data (relationship definitions in models), not code.

**Cons.** Curating semantic relationships per provider is ongoing work. Heuristics on attribute names (for example `*_id`) are error-prone, so they should only *suggest*, never auto-apply. Evaluation is recursive with a max depth and filters to models present in the design [verified], so large imported designs need a performance check.

### 4.I Round-trip fidelity strategies

From weakest to strongest:

1. **Regenerate**: design to HCL from scratch each time. Simple; destroys comments, ordering, formatting, and any expression not modeled. Acceptable only for designs authored in Kanvas.
2. **Preserve source, regenerate on edit**: keep original bytes in `sourceContent` [verified field]; export returns the original if nothing changed, otherwise regenerates. Still lossy on any edit.
3. **Surgical patching (recommended)**: keep a source map from component id and attribute path to HCL file, block, and byte range, captured at import from the `hcl/v2` AST. On export, use `hclwrite` to modify only touched attributes and append new blocks; untouched blocks stay byte-identical. Expressions that were never plain values stay opaque and read-only in forms (shown as the raw expression).
4. **Git-native**: export produces a branch and pull request via the existing GitHub connection; the PR diff is the fidelity check, and `refreshPatternFromSource` after merge closes the loop using `commitSha` [verified fields].

Proposed fidelity test suite (not built): a corpus of public modules asserting that (a) import then export with no edits is byte-identical, (b) a single attribute edit changes exactly one line, (c) `tofu validate` passes, (d) `tofu plan` against the original state shows no changes.

### 4.J Crossplane / Upjet bridge (reuse Meshery's Kubernetes path)

**What.** Instead of running Terraform, fulfill cloud components through Crossplane providers generated by Upjet, which "transforms Terraform providers into Crossplane providers" and "powers the official AWS, Azure, and GCP providers along with 50+ community providers" [verified, Upjet README]. Meshery already deploys CRD-backed cloud models (ACK, Azure, Kubeform) through its in-process Kubernetes client, Path A [verified].

**Pros.** No new engine; continuous reconciliation from controllers (ACK, for example, re-checks for drift on a schedule [verified, ACK docs]); MeshSync gives a live view for free. Because Upjet resource schemas are derived from Terraform providers, a Terraform-model component could be translated to its Crossplane equivalent [inferred].

**Cons.** Requires a cluster with Crossplane; different state model (in CR status and the controller, not tfstate); teams with Terraform pipelines will not switch (A1). Best positioned as an *alternate fulfillment path* for the same Terraform-model components, selectable per Environment.

### 4.K Out-of-the-box ideas

1. **Plan as a design diff.** Designs already support comparing snapshots [verified: "Snapshots can be compared"]. Represent a plan as a snapshot pair (prior-state design vs planned design) so the existing compare UX shows the plan; highlight replace-causing fields from `replace_paths`.
2. **Relationships as plan-time guardrails.** Compile Meshery semantic relationships into checks over plan JSON ("every `aws_s3_bucket` must have an `edge/binding/permission` to a KMS key") and evaluate them in CI via `mesheryctl` with the same Go policy engine. Terraform users get Meshery's policy value without adopting Kanvas.
3. **Adopt from discovery with `import` blocks.** When MeshSync, ACK, or a cloud inventory shows a resource with no Terraform address, Kanvas offers "Bring under Terraform" and emits an `import` block plus generated config (Terraform supports `plan -generate-config-out` [unverified in this doc, and unverified for OpenTofu parity]). Firefly sells a version of this [verified: "turn every resource into deployable IaC"].
4. **Multiplayer plan review.** Kanvas real-time collaboration [verified] applied to plan approval: reviewers comment on components in the plan overlay; approval is an event recorded against the design version.
5. **Cost and security overlays from the existing ecosystem.** Feed plan JSON to Infracost or Checkov (both integrated by Brainboard [verified]) and render results as component badges. Integration, not reinvention.
6. **Blast-radius queries.** Use the semantic relationship graph to answer "what breaks if this VPC is replaced?" before apply. Blast Radius did this for the raw DAG [verified README]; Meshery can do it with meaning.
7. **Module marketplace as Patterns in the Catalog.** Publish curated modules as Patterns with forms generated from `variables`. Massdriver's pitch is that "forms, validation, and dependency resolution are generated from" its module catalog [verified].
8. **Engine-neutral IR.** MeshKit's `GenerateComponents` already abstracts the package type, so the same IR could later accept Pulumi schemas or CloudFormation resource specs. Out of scope here, but schema changes should say `iac` rather than `terraform` wherever possible.

### 4.L Tradeoff summary

| Approach | User value (per Section 2) | Effort | Main risk | Reuse of existing code | Depends on |
| --- | --- | --- | --- | --- | --- |
| A Schema import to models | Medium alone, High as enabler | Medium | Scale, churn | High (generator, registry, OCI) | S1, S3, S5, S7, S9 |
| B HCL/plan import to designs | High | Medium-High | Expression and module fidelity | High (import pipeline, source binding) | A, S1, S2, S6 |
| C Design to HCL export | Medium | Medium | Fidelity churn | Medium (converter pattern) | A, I |
| D State ingestion and drift view | High | Medium | Secrets handling | High (Connections, Operator) | A, S7 |
| E Orchestrator (full) | Medium (A7) | High | Liability, BSL | Medium (Path B) | A-D, S8 |
| E' Delegating orchestrator | Medium-High | Medium | Runner API variance | Medium | B, D |
| F Meshery TF provider | Medium (different audience) | Low-Medium | Low | High (OpenAPI) | none |
| G Embedded OpenTofu | Enabler | Low | Engine divergence | n/a | none |
| H Relationship inference | High | Medium, ongoing curation | False positives | High (relationship engine) | A, B |
| I Round-trip (surgical) | High (A6) | High | Edge cases | Low (new code) | B, C |
| J Crossplane bridge | Medium | Medium | Cluster prerequisite | High (Path A) | A |

---

## 5. Competitive comparison

All URLs below were fetched on 2026-10-16 unless marked. Claims are limited to what those pages say; I did not trial the products. Repo activity dates come from the GitHub API on the same day.

| Product | What it is (per its own materials) | Relationship to Terraform | Visual design | Live / drift | Notable for Meshery | Source |
| --- | --- | --- | --- | --- | --- | --- |
| Brainboard | "Design, deploy and manage your cloud infrastructure"; "generates Terraform code instantly as you design" | Generates HCL, imports modules, embedded CI/CD, secure remote backend | Yes, collaborative designer | "TF state drift detection" on schedules | Closest direct competitor to Kanvas plus Terraform. Integrates Infracost, Checkov, tfsec, Terrascan, OPA. AWS, Azure, GCP, OCI, Scaleway. | https://www.brainboard.co/ |
| Pluralith | "Visualise your Terraform state and automate infrastructure documentation"; `pluralith plan`; highlights plan changes, drift, cost (Infracost) | Plan/state consumer | Generated diagrams | Drift visualization | README says Alpha and requires the Pluralith UI or an API key; repo last pushed 2023-07-14, suggesting low activity [inferred] | https://github.com/Pluralith/pluralith-cli |
| HCP Terraform | Managed Terraform; health assessments with drift detection and continuous validation of checks | Native | Not a canvas [inferred] | Scheduled drift and check evaluation; Standard and Premium editions | Sets the bar for drift semantics; distinguishes configuration drift from state drift | https://developer.hashicorp.com/terraform/cloud-docs/workspaces/health |
| Spacelift | IaC orchestration; stack dependencies form a DAG with output-to-input references (`TF_VAR_` injection), cycles rejected | Runner | Dependency graph view | Not reviewed here | Cross-stack wiring maps to Meshery design outputs/inputs plus relationships | https://docs.spacelift.io/concepts/stack/stack-dependencies |
| env0 | IaC automation; drift detection via cron with statuses OK, Drifted, Error, Never Run, Disabled; auto or manual remediation | Runner | Not reviewed | Yes; minimum interval 1 day (Free) or 1 hour (Enterprise) | Drift status vocabulary worth reusing | https://docs.env0.com/docs/drift-detection |
| Pulumi | Alternative engine; `pulumi convert --from terraform`; `runtime: hcl` runs `.tf` on the Pulumi engine; Pulumi Cloud implements the Terraform remote backend API; `pulumi import --from terraform` | Converter, backend, coexistence | Not a canvas | Not reviewed | Shows that "be a backend for existing Terraform" is a viable wedge; says the converter handles 90-95% of code | https://www.pulumi.com/docs/iac/guides/migration/migrating-to-pulumi/from-terraform/ |
| Crossplane (Upjet) | Generates Crossplane providers (CRDs, controllers, examples) from Terraform providers | Reuses Terraform providers under Kubernetes controllers | No (Kubernetes-native) | Continuous reconciliation | Proves Terraform provider schemas can be lifted into another object model at scale, which is Approach A | https://github.com/crossplane/upjet |
| Rover | "Interactive Terraform visualization. State and configuration explorer"; generates a plan and renders resource overview, map, graph | Plan/config consumer | Read-only | No | MIT; last push 2025-07-30 | https://github.com/im2nguyen/rover |
| Inframap | Reads tfstate or HCL to "generate a graph specific for each provider, showing only the resources that are most important/relevant" | State/HCL consumer | Generated graph | No | Provider-specific simplification is the same problem Meshery's semantic relationships solve; MIT; last push 2026-04-23 | https://github.com/cycloidio/inframap |
| Blast Radius | "Interactive visualizations of Terraform dependency graphs using d3.js" | Graph consumer | Read-only | No | Prior art for blast-radius UX; last push 2024-08-14 | https://github.com/28mm/blast-radius |
| Cloudcraft | "Live AWS, Azure & GCP architecture diagrams", "now free in Datadog", overlays for alerts, logs, security, cost | Not Terraform-centric | Yes, live | Live from Datadog-collected data | Demand signal for *live* diagrams with operational overlays, which is the pitch of Kanvas Operator mode | https://www.cloudcraft.co/ |
| Firefly | Cloud resilience and IaC management: "Scan your cloud into a unified System of Record and turn every resource into deployable IaC"; drift remediation; IaC orchestration with guardrails | Codifies unmanaged resources, orchestrates | Not reviewed | Drift detection and remediation | Validates the "adopt from discovery" idea (4.K.3) | https://www.firefly.ai/ |
| Massdriver | IDP and "platform orchestrator for Terraform, OpenTofu and Helm"; modules published to a catalog; "forms, validation, and dependency resolution are generated from it" | Module packaging and orchestration | Not confirmed from this page [unverified] | "Every resource, deploy, and dependency is live data" | Closest analog to "module as Pattern with generated forms" | https://www.massdriver.cloud/ |
| System Initiative | Described as an "AI Native Infrastructure Automation platform" | Own model, not Terraform | Yes (historically) | Yes (historically) | **Archived**: README says "System Initiative has been archived, and is no longer being maintained"; GitHub API shows `archived: true`, last push 2026-02-06. A cautionary signal for products that replace IaC rather than integrate with it [inferred] | https://github.com/systeminit/si |
| CDKTF (context, not a competitor) | Programmatic Terraform | n/a | n/a | n/a | Deprecated as of 2025-12-10 per HashiCorp; repo archived. Do not build on CDKTF; treat CDKTF users as HCL users via `cdktf synth --hcl` | https://developer.hashicorp.com/terraform/cdktf |

Where Meshery and Kanvas can differentiate [inferred from the table]:

1. Semantic relationships and in-browser policy evaluation. None of the visualizers above publishes a relationship model beyond the dependency graph or per-provider heuristics.
2. One canvas for Kubernetes plus cloud, with live Kubernetes state from MeshSync. Brainboard and Cloudcraft are cloud-first; Rover, Inframap, and Blast Radius are Terraform-only.
3. Open source (meshery.io states Meshery "is now a CNCF Incubating project" [verified]) with an MPL engine (OpenTofu); most visual competitors are proprietary.
4. Non-competitive positioning with runners: integrate HCP Terraform, Spacelift, and env0 as fulfillment backends (Approach E') instead of displacing them.

---

## 6. Recommendation: phased, schema-first plan

### 6.1 Phases

| Phase | Deliverable | Approaches | Exit criteria |
| --- | --- | --- | --- |
| 0. Schema RFC | PR set in `meshery/schemas` for S1 to S7 and S9 (below), docs in `docs/` and docs.meshery.io, generated Go/TS types; no runtime behavior | n/a | `make validate-schemas && make consumer-audit` pass; maintainers approve the data-source identity scheme and the `iac` metadata block |
| 1. Models from provider schemas | MeshKit `terraform` generator; curated static models for `hashicorp/kubernetes`, `hashicorp/aws`, `hashicorp/google`, `hashicorp/azurerm`, `hashicorp/random` at pinned versions; lazy registration; `$ref` dedup for recursive blocks; description enrichment from registry docs | A, G | Palette search works; the 3.8 MB worst case renders; registry boot-time regression within an agreed budget |
| 2. Import to designs (read-mostly) | HCL directory/archive and plan-JSON import; references and `depends_on` to relationships (syntactic layer); `designType: Terraform`; `sourceContent` preserved; GitHub source binding and refresh; plan overlay MVP | B, H(1), K.1 | Import of a public module corpus yields correct component counts and edges |
| 3. Semantic relationships and policy | Curated relationship definitions for top AWS/GCP/Azure pairs plus cross-model Kubernetes links; plan-time guardrails via `mesheryctl` | H(2, 3), K.2 | Relationship evaluation on a 500-component imported design within an agreed latency budget |
| 4. State and drift view | `terraform-state` connection kind, read-through ingestion, `sensitive_values` redaction, refresh-only drift badges in Operator mode | D | No raw state persisted; audit events recorded; drift matches `tofu plan -refresh-only` |
| 5. Export and round-trip | Surgical HCL export with source maps; PR-based export via the GitHub connection | C, I | Fidelity suite (4.I) passes |
| 6. Orchestration | E' delegating adapter first (trigger external runner, ingest plan); then an optional full adapter running OpenTofu via `terraform-exec`; optional HTTP backend; S8 lands here | E', E | Mixed Kubernetes plus Terraform design deploys with cross-path ordering and a per-component summary |
| Parallel track | `terraform-provider-meshery` (closes #4051) | F | Published to the OpenTofu and Terraform registries |

Why this order: Phases 1 to 4 are read-mostly, serve A1 to A4 with low liability, and produce the IR that Phases 5 and 6 need. Orchestration last respects A7 and keeps the BSL and secrets questions off the critical path.

### 6.2 Schema changes, in order (meshery/schemas first)

Follow the repository's rules: the response schema lives in `<construct>.yaml` with `additionalProperties: false`; writable entities get a `*Payload` in `api.yml`; camelCase on the wire; no partial casing migrations within a published version; new enum values in lowercase; declared endpoint paths must equal served routes [verified in `AGENTS.md`]. Where a change to a published version is not purely additive, bump the version instead.

| ID | Change | Location (current tree) | Reuse / rationale |
| --- | --- | --- | --- |
| S1 | Add IaC file types for detection, for example `terraform-config`, `terraform-plan`, `terraform-state` (names to be decided) | `IaCFileTypes` enum in `schemas/constructs/v1beta2/core/api.yml` (also present in v1beta1 and v1alpha1) | Drives MeshKit `files.IdentifyFile`. Additive enum change; confirm whether additive enum values are acceptable within a published version |
| S2 | Add `Terraform` (and possibly `OpenTofu`) to `designType` | `designType` enum on the stored design in `schemas/constructs/v1beta3/design/api.yml` (existing literals such as `Helm Chart` are casing-exempt) | Reuses `sourceContent` and the source-binding fields |
| S3 | Component identity for Terraform modes: an `iac` object in component metadata with `engine`, `mode` (`managed`, `data`, `ephemeral`), `address`, `providerConfigKey`, `schemaVersion`, `instanceKey`, raw `count` / `forEach` expressions; and a decision on whether `component.kind` is mode-qualified (`data.aws_s3_bucket`) or uniqueness includes `mode` | `schemas/constructs/v1beta3/component/component.yaml` (`metadata` is currently `additionalProperties: true`) | Solves the 396-name collision; typed rather than free-form |
| S4 | Formalize `dependsOn` as a typed component metadata property (array of component names) | Same file | Server already reads it from `additionalProperties` in `planner.go` [verified]; typing it is a contract clarification with no behavior change |
| S5 | Document the JSON Schema vendor extensions used inside `component.schema`: `x-iac-computed`, `x-iac-sensitive`, `x-iac-write-only`, `x-iac-ephemeral`, `x-iac-nesting-mode`, `x-iac-expr` (opaque expression wrapper), `x-iac-unknown` | `docs/` in meshery/schemas plus a small JSON Schema describing the extension vocabulary | UI forms and exporters key off these; the vendor-neutral `iac` prefix keeps Pulumi/CloudFormation options open |
| S6 | Design-level `variables` and `outputs` (typed, with `sensitive`, `ephemeral`, validation) | `schemas/constructs/v1beta3/design/design.yaml` and the design payload schema in `api.yml` | Needed for module import, the Patterns roadmap, and cross-design wiring |
| S7 | New Connection kinds: `terraform-registry` / `opentofu-registry` (registrant), `terraform-state` (backend reader), later `terraform-runner` (HCP Terraform, Spacelift, env0), each with Credential templates | Connection templates under `schemas/constructs/v1beta3/connection/templates`; credential forms under `schemas/constructs/v1beta1/credential/forms` | Reuses the Connection lifecycle and Environment grouping |
| S8 | New construct `iacRun` (plan/apply run record: design id and version, engine and version, action, status, plan summary counts, redacted plan JSON reference, approver, timestamps) with `iac_run.yaml`, `IacRunPayload`, and endpoints under `/api/...` | `schemas/constructs/v1beta3/iac_run/` (new) | Only when Phase 6 starts; reuse the existing `event` construct for logs |
| S9 | Model metadata `iac` block: `providerSource`, `providerVersion`, `protocolVersion`, `schemaFormatVersion`, `providerLicense`, `generatedBy` | `schemas/constructs/v1beta1/model/model.yaml` (or its successor version) | Provenance, license tracking, lazy regeneration |

Relationship definitions for Terraform models (references, dependency, semantic pairs) are *data in models*, not schema changes, because relationship `type` and `subType` are open strings [verified]. If a `dependency` subType is introduced for pure ordering edges, add it to the relationships documentation table.

### 6.3 Code reuse map (do not duplicate)

| Need | Reuse |
| --- | --- |
| New registrant | `meshkit/generators/generator.go` `NewGenerator` switch; `models.PackageManager` / `models.Package` |
| Model packaging and registry | Existing model import/export, OCI packaging, Registry UI, `mesheryctl registry generate` |
| File detection and conversion | `meshkit/files/identification.go` chain and `files/conversion.go` |
| Export | `meshkit/converter` pattern (`K8sConverter`, `HelmConverter`) |
| Design import and Git binding | `/api/pattern/import`, `designType`, `sourceContent`, `DesignSourceBinding`, `refreshPatternFromSource` |
| Ordering and failure semantics | `server/models/pattern/planner` (`DeclaredDependencies`, cycle detection, withholding) |
| Delegated fulfillment | Deployment Engine Path B (adapter over gRPC) |
| Relationships and policy | `relationships.meshery.io/v1beta3`, `/api/registry/relationships/evaluate`, WASM evaluator |
| Credentials and environments | Connection, Credential, Environment constructs |
| Terraform parsing and execution | `hashicorp/hcl` (v2), `hashicorp/terraform-json`, `hashicorp/terraform-exec`, `hashicorp/terraform-config-inspect`, `hashicorp/terraform-plugin-go`, `opentofu/tofudl` (all MPL-2.0 per the GitHub API [verified]) |

---

## 7. Open questions and risks

### 7.1 Licensing (BSL vs MPL)

- **Terraform CLI 1.6.0 and later is BSL 1.1**, and the licensor in the current `LICENSE` is IBM [verified in `hashicorp/terraform` `LICENSE`]. The additional use grant permits production use unless it includes "offering the Licensed Work to third parties on a hosted or embedded basis in order to compete with" the licensor's paid versions. "Embedded" includes packaging such that the Licensed Work "must be accessed or downloaded for the competitive offering to operate", and "Products that are not provided on a paid basis are not competitive" [verified, BSL text]. HashiCorp's FAQ says Terraform providers, SDKs, and almost all libraries remain MPL 2.0 [verified via search excerpt of the FAQ].
- **OpenTofu is MPL-2.0** [verified, GitHub API].
- Open question: would a paid Layer5 Cloud or Kanvas tier that runs plan/apply be a "competitive offering" against HCP Terraform? This needs counsel, not engineering judgment. Engineering default: ship and host only OpenTofu; let self-hosted users point Meshery at a Terraform binary they install themselves.
- Open question: the terms of use for programmatically downloading providers from `registry.terraform.io` vs `registry.opentofu.org` at scale for model generation. **Not reviewed in this doc [unverified].**
- Provider licenses vary for community providers ("The maintainers of each provider are free to select their own license" [verified, FAQ excerpt]); generated models should record the provider license (S9).

### 7.2 Provider schema scale

- Measured: 5,876 component definitions and 35.6 MB of raw schema for four providers; the worst single component is 3.8 MB [verified]. Risks: registry DB size, boot time, form rendering performance, OCI model package size. Mitigations: curated subsets, lazy loading, `$ref` dedup of repeated subtrees, server-side pagination of large schemas.
- Churn: every provider release is a model version. Needs a retention policy (for example keep the latest N minor versions, generate others on demand).

### 7.3 Secrets in state and plans

- State and plan files contain sensitive values; `sensitive` only redacts display; `terraform output -json` or `-raw` prints sensitive values in plain text; ephemeral values and write-only arguments are omitted from state and plan files [verified]. Sensitivity propagates through expressions, which I observed in the demo [verified].
- Requirements: never persist raw state or plan by default; redact via `sensitive_values` / `after_sensitive`; never copy sensitive values through relationship patches; hold backend secrets as Meshery Credentials (documented as encrypted at rest [verified claim; implementation not audited]); emit an audit event on every state read.
- OpenTofu state encryption may require KMS access to read state [verified feature]; prefer reading where keys already live (the user's runner) and ingesting redacted JSON (Approach E').

### 7.4 Other risks and open questions

1. **Expression fidelity** (`for_each`, `dynamic`, functions). Configuration JSON omits `dynamic` block expressions [verified in docs], and my OpenTofu test omitted `for_each_expression` [verified observation]. HCL AST parsing is mandatory.
2. **Double modeling of Kubernetes.** Meshery's native Kubernetes model vs Terraform's 81 `kubernetes_*` resource types for the same objects. Decide whether import maps `kubernetes_deployment` onto the native `Deployment` component (better relationships and MeshSync) or keeps it as a Terraform component (better round-trip). Probably configurable [inferred].
3. **Relationship evaluation cost** on large imported designs (recursive evaluation with a configurable max depth [verified]). Benchmark before Phase 3.
4. **Engine divergence** between OpenTofu and Terraform over time [inferred]; record engine and version per design and validate with that engine.
5. **Auto-layout** for imported designs with hundreds of nodes; existing tools simplify rather than draw everything (Inframap [verified]). Group by module and by hierarchical relationships.
6. **Who curates semantic relationships** per provider; this is ongoing community work similar to existing model contributions.
7. **Hosted Kanvas limits**: validate, dry-run, deploy, connecting clusters, and Operator mode are not available on kanvas.new [verified]. Import, plan overlay from an uploaded plan JSON, and export could work on hosted Kanvas; state reading and runs require Meshery Server.
8. **Patterns dependency**: module-as-Pattern relies on Patterns (roadmap v0.9.0 [verified]); if Patterns slip, modules import as nested designs first.
9. **Naming**: use the Terraform type as `component.kind` for exact mapping and a curated `displayName` ("S3 Bucket") for the palette.
10. **Market signal**: System Initiative (archived) and CDKTF (deprecated) both tried to replace or wrap HCL; integrations that keep HCL as the source of truth appear more durable [inferred].

---

## Appendix A. Prototype converter (summary)

Full file: `/workspace/tf2meshery/tfschema_to_jsonschema.py` on the box. Core mapping:

- cty `string`, `number`, `bool` to JSON Schema primitives; `dynamic` to `{}`.
- `list(T)` and `set(T)` to arrays (`set` adds `uniqueItems: true`); `map(T)` to `additionalProperties: T`; `object({...})` to `properties`; `tuple` to positional `items`.
- Block `nesting_mode` `list` / `set` to arrays with `minItems` / `maxItems`; `map` to `additionalProperties`; `single` to object; the original mode is preserved as `x-tf-nesting-mode` (to be renamed `x-iac-nesting-mode` per S5).
- Attribute flags `sensitive`, `write_only`, `computed`, `deprecated` are preserved as extensions; computed-only attributes are excluded from the authoring schema.
- Output is wrapped as a `components.meshery.io/v1beta3` component with `model.name = terraform-<provider>`, `metadata.tfMode`, and `component.kind = <resource type>`. The data-source collision is visible in its output and motivates S3.

## Appendix B. Reproduction

```bash
# in an empty directory, with tofu on PATH
cat > main.tf <<'TF'
terraform {
  required_providers {
    aws        = { source = "hashicorp/aws" }
    google     = { source = "hashicorp/google" }
    azurerm    = { source = "hashicorp/azurerm" }
    kubernetes = { source = "hashicorp/kubernetes" }
  }
}
TF
tofu init -input=false
tofu providers schema -json > schema.json
python3 tfschema_to_jsonschema.py schema.json > components.jsonl
```

## Appendix C. Sources

Meshery and Layer5:
- https://docs.meshery.io/concepts/logical/models
- https://docs.meshery.io/concepts/logical/components
- https://docs.meshery.io/concepts/logical/relationships
- https://docs.meshery.io/concepts/logical/designs
- https://docs.meshery.io/concepts/logical/patterns
- https://docs.meshery.io/concepts/logical/policies
- https://docs.meshery.io/concepts/logical/registry
- https://docs.meshery.io/concepts/logical/connections
- https://docs.meshery.io/concepts/logical/credentials
- https://docs.meshery.io/concepts/logical/environments
- https://docs.meshery.io/concepts/logical/workspaces
- https://docs.meshery.io/concepts/architecture/deployment-engine
- https://docs.meshery.io/extensions/models/ (via search result excerpt)
- https://meshery.io/integrations
- https://docs.layer5.io/kanvas/
- https://github.com/meshery/schemas (cloned at eb7f8e7179a3705d0e3a749f6bdb7baa810ef521)
- https://github.com/meshery/meshkit (cloned at 919c7d5d43be635ed69b46ca83f8e49ca3965d2f)
- https://github.com/meshery/meshery/blob/master/server/models/pattern/planner/planner.go
- https://github.com/meshery/meshery/issues/4051

Terraform and OpenTofu:
- https://developer.hashicorp.com/terraform/cli/commands/providers/schema
- https://developer.hashicorp.com/terraform/internals/json-format
- https://developer.hashicorp.com/terraform/language/meta-arguments/depends_on
- https://developer.hashicorp.com/terraform/language/state/sensitive-data
- https://developer.hashicorp.com/terraform/language/backend/http
- https://developer.hashicorp.com/terraform/cdktf
- https://developer.hashicorp.com/terraform/cloud-docs/workspaces/health
- https://raw.githubusercontent.com/hashicorp/terraform/main/LICENSE
- https://www.hashicorp.com/bsl and https://www.hashicorp.com/license-faq (search excerpts; direct fetch hit a bot checkpoint)
- https://opentofu.org/docs/language/state/encryption/
- https://github.com/opentofu/opentofu (license and release metadata via GitHub API)
- https://github.com/hashicorp/terraform-exec, https://github.com/hashicorp/terraform-json, https://github.com/hashicorp/hcl, https://github.com/hashicorp/terraform-plugin-go, https://github.com/hashicorp/terraform-config-inspect, https://github.com/opentofu/tofudl (license metadata via GitHub API)
- https://github.com/hashicorp/terraform-cdk (archived status via GitHub API)

Competitors and adjacent:
- https://www.brainboard.co/
- https://github.com/Pluralith/pluralith-cli
- https://docs.spacelift.io/concepts/stack/stack-dependencies
- https://docs.env0.com/docs/drift-detection
- https://www.pulumi.com/docs/iac/guides/migration/migrating-to-pulumi/from-terraform/
- https://github.com/crossplane/upjet
- https://github.com/im2nguyen/rover
- https://github.com/cycloidio/inframap
- https://github.com/28mm/blast-radius
- https://www.cloudcraft.co/
- https://www.firefly.ai/
- https://www.massdriver.cloud/
- https://github.com/systeminit/si
- https://aws-controllers-k8s.github.io/community/docs/community/how-it-works/ (via search result excerpt)
