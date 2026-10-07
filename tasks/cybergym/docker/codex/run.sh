#!/bin/bash
set -e

# Fix docker socket permissions (host GID won't match container's docker group)
if [ -S /var/run/docker.sock ]; then
    sudo chmod 666 /var/run/docker.sock
fi

# Environment variables expected:
#   PROMPT         — the task prompt
#   MODEL          — model name (e.g. gpt-5.4-mini)
#   REASONING      — reasoning effort (low/medium/high/none)
#   MODEL_PROVIDER — (optional) model provider from config.toml (e.g. myollama)

CMD=(codex exec
    --dangerously-bypass-approvals-and-sandbox
    --model "${MODEL}"
    -c 'web_search="disabled"'
    -c "model_reasoning_effort=${REASONING}"
    --json
)

if [ -n "${MODEL_PROVIDER}" ]; then
    CMD+=(-c "model_provider=\"${MODEL_PROVIDER}\"")
fi

exec stdbuf -oL -eL "${CMD[@]}" "${PROMPT}" 2>&1
