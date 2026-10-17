# tf2meshery (prototype)

Converts `tofu providers schema -json` (or `terraform providers schema -json`) output into Meshery-style component definitions (`components.meshery.io/v1beta3`, JSON Schema draft-07 in `component.schema`), one JSON object per line.

This is sizing code for the architecture proposal, not production code. The production path proposed in [docs/architecture.md](../../docs/architecture.md) is a MeshKit `terraform` registrant generator.

## Requirements

- Python 3.8+ (standard library only)
- OpenTofu (recommended, MPL-2.0) or Terraform on `PATH`

## Run

```bash
# 1. Produce a provider schema dump (example: the four providers measured in findings/)
cd ../../findings
tofu init -input=false
tofu providers schema -json > out/schema.json   # about 35 MB, gitignored

# 2. Convert every resource and data source
python3 ../prototype/tf2meshery/tfschema_to_jsonschema.py out/schema.json > out/components.jsonl

# 3. Or convert only selected types
python3 ../prototype/tf2meshery/tfschema_to_jsonschema.py out/schema.json aws_s3_bucket kubernetes_deployment
```

Or just run `findings/scripts/regenerate.sh`, which does all of the above.

## What it does

- Maps cty types to JSON Schema (`list`/`set` to arrays, `set` adds `uniqueItems`, `map` to `additionalProperties`, `object`, `tuple`).
- Drops computed-only attributes; keeps descriptions.
- Marks Terraform semantics with vendor extensions: `x-tf-sensitive`, `x-tf-write-only`, `x-tf-computed`, `x-tf-nesting-mode`, plus `deprecated`. (The proposal renames these to a vendor-neutral `x-iac-*` prefix; see ADR 0003 discussion in the architecture doc, section 6.2 S5.)
- Records `metadata.tfMode` (`managed` or `data`), which exposes the resource/data source name collision (ADR 0002).

## Known limitations

- Provider version is emitted as `unknown`.
- Recursive nested blocks are fully unrolled, so a few schemas reach megabytes (`aws_wafv2_web_acl_rule` is 3.8 MB). No `$ref` dedup yet.
- No ephemeral resources, functions, or relationships.

## demo/

A tiny config (`random`, `local`, `terraform_data`) exercising variables, `for_each`, `depends_on`, outputs, and sensitivity propagation. `plan.json` is the `tofu show -json` output of its plan (no real secrets: the password is unknown at plan time). Regenerate:

```bash
cd demo && tofu init && tofu plan -out=p.bin && tofu show -json p.bin > plan.json
```
