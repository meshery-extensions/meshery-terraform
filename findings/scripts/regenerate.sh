#!/usr/bin/env bash
# Regenerate the provider schema dump and converted components measured in findings/README.md.
# Outputs go to findings/out/ (gitignored; about 35 MB schema and 32 MB JSONL).
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"
TOFU="${TOFU:-tofu}"
command -v "$TOFU" >/dev/null || { echo "OpenTofu not found. Install from https://opentofu.org/docs/intro/install/ or set TOFU=/path/to/tofu (or terraform)." >&2; exit 1; }
mkdir -p out
"$TOFU" init -input=false >out/init.log
"$TOFU" providers schema -json >out/schema.json
python3 ../prototype/tf2meshery/tfschema_to_jsonschema.py out/schema.json >out/components.jsonl
python3 scripts/stats.py out/schema.json out/components.jsonl | tee out/stats.md
