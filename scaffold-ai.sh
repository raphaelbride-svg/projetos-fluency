#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-.}"

dirs=(ai-core prompts agents knowledge skills data experiments configs playbooks tools examples tests docs scripts logs security)

for d in "${dirs[@]}"; do
  mkdir -p "$ROOT_DIR/$d"
  if [ ! -f "$ROOT_DIR/$d/README.md" ]; then
    cat > "$ROOT_DIR/$d/README.md" <<MDEOF
# $d
Purpose: Describe the intent and contract (inputs/outputs) for the $d folder.
Contract:
- inputs: []
- outputs: []
MDEOF
  fi
done

cat > "$ROOT_DIR/ai-manifest.json" <<'JSON'
{
  "name": "ai-project",
  "version": "0.1.0",
  "agents": [],
  "prompts": []
}
JSON

GITIGNORE="$ROOT_DIR/.gitignore"
touch "$GITIGNORE"
grep -qxF "data/" "$GITIGNORE" || printf "\n# AI scaffolding ignore\ndata/\nlogs/\nsecrets.env\n" >> "$GITIGNORE"

echo "Scaffold created at $ROOT_DIR"
