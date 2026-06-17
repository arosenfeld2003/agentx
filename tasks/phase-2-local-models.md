# Phase 2: Local Models

**Status:** `[ ]` — not started

## Description

Install Ollama on the VPS host, pull Qwen3 8B, wire LiteLLM as an Anthropic-compatible
proxy, and verify ralph completes a full iteration using the local model.

Full details: `specs/local-models.md`

## Implementation Steps

1. **Manual prerequisite** (operator, on VPS host):
   - Install Ollama: `curl -fsSL https://ollama.com/install.sh | sh && systemctl enable --now ollama`
   - Pull model: `ollama pull qwen3:8b`
   - Confirm: `ollama list` shows `qwen3:8b`

2. **Ralph can proceed after step 1:**
   - Create `/opt/agentx/litellm-config.yaml` per `specs/local-models.md`
   - Uncomment and update `litellm` service in `vps-compose.yml`
   - Add `LITELLM_MASTER_KEY`, `ANTHROPIC_BASE_URL` to `secrets.env.example`
   - Update `AGENTS.md` with new startup instructions for LiteLLM

3. **Verification** (operator):
   - Start LiteLLM: `docker compose -f vps-compose.yml up -d litellm`
   - `curl http://localhost:4000/health`
   - Run: `RALPH_MODEL=qwen3:8b ./ralph.sh 1`
   - Confirm session log shows model `qwen3:8b`

## Acceptance Criteria

See `specs/local-models.md` → Acceptance Criteria section.

## Blocker

Step 2 cannot begin until the operator has completed step 1 on the VPS host.
Ralph should implement step 2 (config files, compose changes), then stop and
document that operator must run step 1 + verification.

## Known Gotchas

- **`api_base` in `litellm-config.yaml` must use `172.17.0.1:11434`**, not `127.0.0.1` or `host.docker.internal`.
  LiteLLM runs inside Docker; `127.0.0.1` resolves to the container's own loopback and `host.docker.internal`
  is a Mac/Windows-only DNS alias. On Linux, `172.17.0.1` is the Docker bridge gateway that routes to the host.
  Verify with: `docker network inspect bridge | grep Gateway`

- **LiteLLM lowercases model names** when routing. `model_name` entries in `litellm-config.yaml` must use
  lowercase quantization suffixes (e.g. `q4_k_m`, not `q4_K_M`), otherwise LiteLLM fails to match the route
  and falls back to Anthropic, returning a 400 error.

- **`/health` hangs** because it pings all configured models. Use `/health/liveliness` to confirm the proxy
  process is up without waiting on Ollama.
