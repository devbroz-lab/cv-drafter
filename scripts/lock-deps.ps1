# Regenerate locked requirements files from requirements.in / requirements-dev.in.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

pip install -q pip-tools
python -m piptools compile requirements.in --output-file requirements.txt --resolver=backtracking
python -m piptools compile requirements-dev.in --output-file requirements-dev.txt --resolver=backtracking

Write-Host "Updated requirements.txt and requirements-dev.txt"
