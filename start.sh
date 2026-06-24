#!/bin/bash
# Kvitto-appen – startskript för Mac
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "  ✗  Virtuell miljö saknas. Kör ./install.sh först."
    exit 1
fi

source venv/bin/activate
python3 main.py
