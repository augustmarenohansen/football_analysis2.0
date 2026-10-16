#!/bin/sh
set -eu
cd "$(dirname "$0")/Footballanalyzer-master"
if [ ! -x .venv/bin/python ]; then
    echo "Opprett Python-miljøet først. Se README.md."
    exit 1
fi
exec .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
