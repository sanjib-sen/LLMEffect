#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "== LLMEffect prototype demo =="
echo
for f in examples/*.py; do
  echo "---- $f ----"
  uv run llmeffect "$f" || true
  echo
done

echo "== summary =="
uv run llmeffect examples/ --summary || true
