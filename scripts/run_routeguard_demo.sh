#!/usr/bin/env bash
set -euo pipefail

python -m routeguard_med.cli route \
  --query "What public evidence exists for UNiD Spine Analyzer software anomalies?" \
  --router utility

python -m routeguard_med.evaluation.evaluate \
  --benchmark routeguard_med/benchmarks/routeguard_med_300.csv \
  --corpus routeguard_med/data/sample_evidence.jsonl \
  --routers heuristic,utility,learned \
  --out-dir routeguard_reports
