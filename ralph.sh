#!/bin/bash
# Ralph - Autonomous development loop via Docker
# Usage: ./ralph.sh [plan] [max_iterations]
#
# Auth (Claude API): Set ANTHROPIC_API_KEY in /opt/agentx/secrets.env (VPS)
#   or run: docker compose -f "$RALPH_DOCKER/docker-compose.yml" run --rm ralph login
#
# VPS usage:
#   RALPH_DOCKER=/opt/agentx/ralph-docker ./ralph.sh
#   RALPH_DOCKER=/opt/agentx/ralph-docker ./ralph.sh plan 3
#
# Email listener (Python):
#   uv run --env-file /opt/agentx/secrets.env src/listener.py

RALPH_DOCKER="${RALPH_DOCKER:-$HOME/repos/claude/claudecode/ralph-docker}"

if [ ! -d "$RALPH_DOCKER" ]; then
    echo "Error: ralph-docker not found at $RALPH_DOCKER"
    echo "Set RALPH_DOCKER=/path/to/ralph-docker"
    exit 1
fi

export WORKSPACE_PATH="$(pwd)"
export RALPH_MAX_ITERATIONS="${RALPH_MAX_ITERATIONS:-5}"

if [ "$1" = "plan" ]; then
    export RALPH_MODE=plan
    [ -n "$2" ] && export RALPH_MAX_ITERATIONS="$2"
elif [[ "$1" =~ ^[0-9]+$ ]]; then
    export RALPH_MODE=build
    export RALPH_MAX_ITERATIONS="$1"
else
    export RALPH_MODE=build
fi

cd "$RALPH_DOCKER" && exec docker compose up ralph
