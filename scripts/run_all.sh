#!/usr/bin/env bash
# Roda todos os cenarios adversos (Etapa 2) e gera graficos.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
for s in banda atraso perda concorrente; do
    python3 scripts/run_experiment.py --scenario "$s" 2>&1 \
        | grep -E '^(===|pingAll|pre:|during:|c[123]:)' || true
done
python3 scripts/plot_results.py
