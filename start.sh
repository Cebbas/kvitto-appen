#!/bin/bash
# Starta Kvitto-appen
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d "venv" ]; then
    echo "Kör install.sh först!"
    exit 1
fi

source venv/bin/activate
python3 main.py
