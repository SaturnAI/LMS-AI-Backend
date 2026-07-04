#!/bin/bash

# Navigate to the working directory
cd /root/LMS-AI-Backend || exit 1

# Activate the virtual environment
source lms_ai_venv/bin/activate

PORT=5015

# Default number of workers for UAT
WORKERS=2

# Parse command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -w|--workers) WORKERS="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

echo "Starting Uvicorn with $WORKERS worker(s) on port $PORT..."
gunicorn app:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:$PORT \
    --workers "$WORKERS" \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --timeout 60 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile -
