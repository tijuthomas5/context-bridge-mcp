#!/usr/bin/env bash
# CB Gauge — Stop (Linux)

echo "===================================================="
echo "Shutting down CB Gauge servers..."
echo "===================================================="

for PORT in 8080 9856; do
    PIDS=$(lsof -ti tcp:$PORT 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "Killing server on port $PORT..."
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
    fi
done

echo ""
echo "----------------------------------------------------"
echo "Successfully closed CB Gauge servers."
echo "----------------------------------------------------"
