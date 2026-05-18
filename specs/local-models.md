# Local Models — Ollama + LiteLLM

## Goal

Replace the Claude API backend with locally-hosted Qwen3 via Ollama, proxied through
LiteLLM so the scaffold's existing Anthropic SDK calls require no code changes — only
env var swaps.

## Architecture

```
ralph container
  └── Anthropic SDK  ──►  LiteLLM proxy (host:4000, Anthropic-compat API)
                               └──► Ollama (host:11434)
                                       └──► qwen3:8b (or qwen3:14b)
```

`network_mode: host` on the ralph container means it can reach both LiteLLM and Ollama
on localhost. No additional networking required.

## Prerequisites (manual, on VPS host)

1. **Install Ollama**
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   systemctl enable --now ollama
   ```

2. **Pull the model**
   ```bash
   ollama pull qwen3:8b          # ~5 GB, fits in 16 GB RAM
   # ollama pull qwen3:14b       # ~9 GB — try if 8b quality is insufficient
   ```

3. **Verify**
   ```bash
   ollama list
   curl http://localhost:11434/api/tags
   ```

## LiteLLM Proxy

LiteLLM provides an Anthropic-compatible REST API on port 4000 that the scaffold's
Anthropic SDK will hit transparently when `ANTHROPIC_BASE_URL` is overridden.

### `litellm-config.yaml` (create at `/opt/agentx/litellm-config.yaml`)

```yaml
model_list:
  - model_name: qwen3:8b
    litellm_params:
      model: ollama/qwen3:8b
      api_base: http://localhost:11434

  - model_name: claude-sonnet-4-6          # passthrough — keep Claude available
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY  # set in secrets.env; any random string works
```

### `vps-compose.yml` changes

Uncomment the `litellm` service block and fill in:
```yaml
litellm:
  image: ghcr.io/berriai/litellm:main-latest
  env_file: ${WORKSPACE_PATH:-/opt/agentx}/secrets.env
  volumes:
    - ${WORKSPACE_PATH:-/opt/agentx}/litellm-config.yaml:/app/config.yaml:ro
  command: ["--config", "/app/config.yaml", "--port", "4000"]
  network_mode: host
  restart: unless-stopped
```

## Environment variables

Add to `secrets.env` on VPS:

```bash
# LiteLLM proxy
LITELLM_MASTER_KEY=some-random-secret      # any string; LiteLLM needs it
ANTHROPIC_BASE_URL=http://localhost:4000   # redirect SDK to LiteLLM
ANTHROPIC_API_KEY=sk-...                   # still needed for Claude passthrough
```

Switch model in `vps-compose.yml` ralph service:
```bash
RALPH_MODEL: qwen3:8b    # was: claude-sonnet-4-6
```

To revert to Claude API: remove `ANTHROPIC_BASE_URL` and restore `RALPH_MODEL`.

## Benchmarking

After wiring, run a representative task and compare:
- Wall-clock time per loop iteration
- Token throughput (tokens/sec from Ollama logs)
- Task completion quality (does the output match Claude's?)
- Cost: $0 local vs. Claude API spend from session logs

Ollama metrics endpoint: `http://localhost:11434/api/ps`

## Acceptance Criteria

- [ ] `ollama list` shows `qwen3:8b` on VPS host
- [ ] LiteLLM proxy container starts and responds to `curl http://localhost:4000/health`
- [ ] `ralph.sh` completes at least one full iteration with `RALPH_MODEL=qwen3:8b` and `ANTHROPIC_BASE_URL=http://localhost:4000`
- [ ] Session log shows model `qwen3:8b` (not `claude-sonnet-4-6`)
- [ ] At least one commit produced by the local-model run
