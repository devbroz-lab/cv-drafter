#!/usr/bin/env bash
# Regenerate locked requirements files from requirements.in / requirements-dev.in.
set -euo pipefail
cd "$(dirname "$0")/.."

pip install -q pip-tools
python -m piptools compile requirements.in --output-file requirements.txt --resolver=backtracking
python -m piptools compile requirements-dev.in --output-file requirements-dev.txt --resolver=backtracking

echo "Updated requirements.txt and requirements-dev.txt"
