# AGENTS.md

## Project Goal

A VPS-hosted autonomous agent that receives task specs via email (agentx@runggp.com), runs Claude-powered Ralph loops, and replies with results — bootstrapped with Claude API, evolving toward local Qwen3 models.

## Tech Stack

- **Python 3.14** — IMAP email listener, spec parser, SMTP responder
- **Bash** — Ralph loop (adapted from scaffold: https://github.com/runggp/scaffold)
- **Docker / Docker Compose** — containerized execution on Ubuntu 24.04 VPS
- **Claude API** — model backend (Phase 1); Ollama/Qwen3 added in Phase 2
- **Hostinger KVM 4** — 4 vCPU, 16 GB RAM, 200 GB NVMe

## Build & Run

```bash
# Local dev
docker compose up

# On VPS
./ralph.sh        # build mode
./ralph.sh plan   # plan mode
```

## Validation

- Tests: `pytest src/tests/`
- Lint: `ruff check src/`
- Types: `mypy src/`
- Session logs: `logs/sessions/<session-id>.json` after each iteration

## Operational Notes

### LiteLLM (Phase 2 — local models)

After operator completes VPS prerequisites (Ollama installed, `qwen3:8b` pulled):

```bash
# Start LiteLLM proxy
docker compose -f vps-compose.yml up -d litellm

# Verify proxy is healthy
curl http://localhost:4000/health

# Run ralph with local model
RALPH_MODEL=ollama/qwen3:8b ./ralph.sh
```

Add to `secrets.env` on VPS before starting LiteLLM:
```
LITELLM_MASTER_KEY=<random-string>
ANTHROPIC_BASE_URL=http://localhost:4000
```

To revert to Claude API: remove `ANTHROPIC_BASE_URL` from `secrets.env` and restore `RALPH_MODEL=claude-sonnet-4-6`.

### Model Routing (Phase 2.1)

Route tasks to different models by using a hint in the email subject:

| Subject format | Model used | LiteLLM bypassed? |
|---|---|---|
| `[task] desc` | `RALPH_DEFAULT_MODEL` or inherited `RALPH_MODEL` | No |
| `[task:local] desc` | `RALPH_LOCAL_MODEL` (default: `ollama/qwen3:8b`) | No |
| `[task:local:qwen3:14b] desc` | `qwen3:14b` | No |
| `[task:api] desc` | `RALPH_API_MODEL` (default: `claude-sonnet-4-6`) | Yes — `ANTHROPIC_BASE_URL` removed |
| `[task:api:claude-opus-4-8] desc` | `claude-opus-4-8` | Yes |

**Why bypass matters:** When `ANTHROPIC_BASE_URL=http://localhost:4000` is set (Phase 2 LiteLLM mode), all SDK calls route through the proxy. `[task:api]` removes `ANTHROPIC_BASE_URL` from the subprocess env so the Anthropic SDK talks directly to the real API.

Configure defaults in `secrets.env`:
```
RALPH_DEFAULT_MODEL=   # empty = use whatever RALPH_MODEL is set to in compose
RALPH_LOCAL_MODEL=     # empty = ollama/qwen3:8b
RALPH_API_MODEL=       # empty = claude-sonnet-4-6
```

### Codebase Patterns

_Document patterns as they emerge._
