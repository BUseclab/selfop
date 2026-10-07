#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# echo "Pulling ubuntu/squid:latest (firewall proxy) ..."
# docker pull ubuntu/squid:latest

echo "Building cybergym/codex:latest ..."
docker build --no-cache -t cybergym/codex:latest -f "$SCRIPT_DIR/codex/Dockerfile" "$SCRIPT_DIR/codex/"

echo "Done. Images:"
docker images --format "  {{.Repository}}:{{.Tag}}  {{.Size}}" | grep cybergym/
