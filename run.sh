#!/usr/bin/env bash
# Quick start without a service: bash run.sh [port]   (default 8501; needs streamlit on PATH — see install.sh)
cd "$(dirname "$0")"
PORT=${1:-8501}
exec streamlit run app.py --server.port "$PORT" --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false
