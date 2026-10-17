# Meshery Terraform

Terraform and OpenTofu integration for [Meshery](https://meshery.io) and Kanvas.

## Purpose

Decide how Meshery (and Kanvas) should support Terraform and OpenTofu. This repository holds the architecture deep dive, one proposed decision record (ADR) per decision, a prototype provider-schema converter, and measured scale findings. Nothing here is a supported product yet.

**Short version:** Meshery and Terraform line up well on *describing* infrastructure (provider = model, resource type = component, resource block = component in a design, module = design, references and `depends_on` = relationships) but not on *running* it (state, plan, unknowns, `count`/`for_each`, secrets in state). The proposal is read-mostly first: schema RFC, generated models, import, relationships, drift view, round-trip export, and only then plan/apply.

## Layout

| Path | Contents |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Full deep dive: assumptions, construct mapping (congruent, incongruent, underlaps), approaches, 12-competitor comparison, phased plan, risks |
| [docs/decisions/](docs/decisions/) | ADRs, all `Status: Proposed` |
| [prototype/tf2meshery/](prototype/tf2meshery/) | Prototype converter from provider schemas to Meshery component definitions, plus a demo config and plan |
| [findings/](findings/) | Scale statistics and scripts to regenerate the (gitignored) raw dumps |

## Decisions needed

- [ ] [ADR 0001: OpenTofu by default; Terraform CLI only as a user-supplied binary](docs/decisions/0001-opentofu-by-default.md)
- [ ] [ADR 0002: Include Terraform mode in component identity](docs/decisions/0002-component-identity-mode.md)
- [ ] [ADR 0003: Typed design-level variables and outputs](docs/decisions/0003-design-variables-outputs.md)
- [ ] [ADR 0004: Curated provider model subsets with lazy loading](docs/decisions/0004-curated-models-lazy-loading.md)
- [ ] [ADR 0005: Phased, schema-first roadmap order](docs/decisions/0005-phased-roadmap.md)
- [ ] [ADR 0006: Hand off runs to the user's existing runner before native plan/apply](docs/decisions/0006-run-handoff-before-native.md)

Each ADR has a matching issue labeled `decision-needed`. Accepting an ADR means changing its status to `Accepted` and closing its issue.

## Community

See [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [GOVERNANCE.md](GOVERNANCE.md). Join the [Meshery Slack](https://slack.meshery.io).

## License

Apache License 2.0. See [LICENSE](LICENSE).
