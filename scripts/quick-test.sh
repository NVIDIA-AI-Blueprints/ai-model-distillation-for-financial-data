#!/bin/bash
set -euo pipefail

curl http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"workload_id": "primary_assistant", "client_id": "aiva-1"}'
