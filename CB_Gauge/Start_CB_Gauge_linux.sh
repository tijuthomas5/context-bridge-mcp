#!/usr/bin/env bash
# CB Gauge — Start (Linux)

echo "===================================================="
echo "Starting CB Gauge..."
echo "===================================================="

cd "$(dirname "$0")"

# Open browser after server starts
(sleep 2 && xdg-open "http://127.0.0.1:9856") &

# Run server in foreground — closing this terminal stops the server
python3 cb_gauge_ui.py
