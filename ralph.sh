#!/bin/bash
# Ralph - Autonomous development loop via Docker
# Usage: ./ralph.sh [plan] [max_iterations]
#
# Auth (Claude API): Set ANTHROPIC_API_KEY in /opt/agentx/secrets.env (VPS)
#   or run: docker compose -f "$SCAFFOLD/docker-compose.yml" run --rm ralph login
#
# VPS usage:
#   ./ralph.sh
#   ./ralph.sh plan 3
#
# Email listener (Python):
#   uv run --env-file /opt/agentx/secrets.env src/listener.py

SCAFFOLD="${SCAFFOLD:-$(cd "$(dirname "$0")" && pwd)/scaffold}"
export SCAFFOLD

if [ ! -d "$SCAFFOLD" ]; then
    echo "Error: scaffold not found at $SCAFFOLD"
    echo "Set SCAFFOLD=/path/to/scaffold"
    exit 1
fi

export WORKSPACE_PATH="$(pwd)"
export RALPH_MAX_ITERATIONS="${RALPH_MAX_ITERATIONS:-5}"

if [ "$1" = "plan" ]; then
    export RALPH_MODE=plan
    [ -n "$2" ] && export RALPH_MAX_ITERATIONS="$2"
elif [ "$1" = "task" ]; then
    # Focus ralph on a single task file: ./ralph.sh task tasks/<name>.md
    # Copies the file to TASK.md so the build prompt works on it exclusively.
    if [ -z "$2" ]; then
        echo "Usage: ./ralph.sh task <path-to-task-file>"
        exit 1
    fi
    if [ ! -f "$2" ]; then
        echo "Error: task file not found: $2"
        exit 1
    fi
    cp "$2" "$(pwd)/TASK.md"
    echo "Task loaded: $2 → TASK.md"
    export RALPH_MODE=build
    [ -n "$3" ] && export RALPH_MAX_ITERATIONS="$3"
elif [[ "$1" =~ ^[0-9]+$ ]]; then
    export RALPH_MODE=build
    export RALPH_MAX_ITERATIONS="$1"
else
    export RALPH_MODE=build
    [ -n "$2" ] && export RALPH_MAX_ITERATIONS="$2"
fi

# Pre-warm Ollama when using a local model so LiteLLM health checks succeed immediately.
# Without this, the first /health call blocks while Ollama loads the model (~30-60s on CPU),
# and the scaffold's poller times out before getting a response.
if [[ "${RALPH_MODEL:-}" == ollama/* ]]; then
    OLLAMA_MODEL="${RALPH_MODEL#ollama/}"
    OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
    echo "[ralph] Pre-warming Ollama model: $OLLAMA_MODEL"
    curl -sf "$OLLAMA_HOST/api/generate" \
        -d "{\"model\":\"$OLLAMA_MODEL\",\"prompt\":\"hi\",\"stream\":false}" \
        --max-time 120 > /dev/null \
        && echo "[ralph] Ollama ready" \
        || echo "[ralph] Warning: Ollama pre-warm failed — proxy health check may be slow"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCAFFOLD" && exec docker compose -f "$SCRIPT_DIR/vps-compose.yml" up --build ralph
