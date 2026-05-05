#!/bin/bash
while pgrep -f "npm install" > /dev/null; do
    echo "Wait for npm install to finish..."
    sleep 5
done
echo "Starting Vite..."
npm run dev -- --host 0.0.0.0
