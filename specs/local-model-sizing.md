# Local Model Sizing — Qwen2.5-Coder, DeepSeek, CodeLlama

## Goal

Provide a documented exploration path for selecting quantized GGUF models that fit within
the VPS memory constraints (16 GB RAM) while maintaining coding task quality. Include
realistic RAM estimates, pull commands, and KV-cache sizing guidance.

## Model Comparison

| Model | Ollama Tag | Quantization | File Size | RAM Est. (load) | Context | Specialty | Notes |
|---|---|---|---|---|---|---|---|
| **Qwen2.5-Coder 7B Instruct** | `qwen2.5-coder:7b-instruct-q4_K_M` | Q4_K_M | ~4.4 GB | ~5–6 GB | 32K | **Coding** | Recommended first choice—coding-optimized, good instruction follow |
| Qwen2.5-Coder 7B Instruct | `qwen2.5-coder:7b-instruct-q5_K_M` | Q5_K_M | ~5.1 GB | ~6–7 GB | 32K | Coding | Higher perplexity than Q4; reserve for if Q4 quality is insufficient |
| DeepSeek-Coder-V2 Lite | `deepseek-coder-v2:16b-lite-instruct-q4_0` | Q4_0 | ~9 GB | ~10–11 GB | 128K | Coding | MoE architecture; excellent code generation; tight on 16 GB—*requires swap* |
| CodeLlama 13B Python | `codellama:13b-python` | Q4_0 | ~7.4 GB | ~8–9 GB | 16K | Python | Strong Python-specific performance; less instruct-tuned for exploration tasks |

## Installation & Setup

### 1. Pull a candidate model

```bash
# Recommended start (5–6 GB RAM, ~4.4 GB disk)
ollama pull qwen2.5-coder:7b-instruct-q4_K_M

# Alternative: higher quality (6–7 GB RAM)
# ollama pull qwen2.5-coder:7b-instruct-q5_K_M

# Advanced (requires swap; 10–11 GB RAM, strongest performance)
# ollama pull deepseek-coder-v2:16b-lite-instruct-q4_0

# Python-specific (8–9 GB RAM)
# ollama pull codellama:13b-python
```

### 2. Verify model is loaded

```bash
ollama list
curl http://localhost:11434/api/tags
```

Output should include your chosen model.

### 3. Check current memory usage (with no models loaded)

```bash
free -h
```

Record the available memory. After loading a model, re-check to confirm KV-cache overhead.

## KV-Cache and num_ctx Sizing

**Why this matters:** Ollama models without a `num_ctx` limit default to 128K context,
which allocates ~2–4 GB for the KV cache alone on a 7B model. A single iteration with
a large context can trigger OOM kills on 16 GB.

**Solution:** Set `num_ctx: 4096` in `litellm-config.yaml` for all local models.

### Math

For a 7B model with Q4 quantization:
- KV-cache per token ≈ 2 × (num_layers × hidden_dim) ÷ 32  (uint4)
- 4096 tokens × ~8 KB per token ≈ 32–50 MB per query
- Over 4 queries in a batch → ~200 MB typical peak
- Safe default: 4096 tokens keeps peak KV under 0.5 GB

For comparison:
- `num_ctx=128K` (Ollama default) → 2–4 GB KV-cache alone → **avoid**
- `num_ctx=8192` → ~1 GB peak → only if swap is active
- `num_ctx=4096` → ~0.5 GB peak → safe default

## LiteLLM Configuration

Update both `/opt/agentx/litellm-config.yaml` (VPS production) and the scaffold's
`agent_git/agentx/scaffold/litellm-config.yaml` with:

```yaml
model_list:
  - model_name: ollama/qwen2.5-coder:7b-instruct-q4_K_M
    litellm_params:
      model: ollama/qwen2.5-coder:7b-instruct-q4_K_M
      api_base: http://127.0.0.1:11434
      timeout: 3600
      num_ctx: 4096
    model_info:
      supports_thinking: false
      supports_extended_thinking: false

  - model_name: ollama/qwen2.5-coder:7b-instruct-q5_K_M
    litellm_params:
      model: ollama/qwen2.5-coder:7b-instruct-q5_K_M
      api_base: http://127.0.0.1:11434
      timeout: 3600
      num_ctx: 4096
    model_info:
      supports_thinking: false
      supports_extended_thinking: false

  - model_name: ollama/deepseek-coder-v2:16b-lite-instruct-q4_0
    litellm_params:
      model: ollama/deepseek-coder-v2:16b-lite-instruct-q4_0
      api_base: http://127.0.0.1:11434
      timeout: 3600
      num_ctx: 4096
    model_info:
      supports_thinking: false
      supports_extended_thinking: false

  - model_name: ollama/codellama:13b-python
    litellm_params:
      model: ollama/codellama:13b-python
      api_base: http://127.0.0.1:11434
      timeout: 3600
      num_ctx: 4096
    model_info:
      supports_thinking: false
      supports_extended_thinking: false

litellm_settings:
  drop_params: true
  request_timeout: 600
  set_verbose: true
  disable_thinking: true
```

### Key settings

- **`api_base: http://127.0.0.1:11434`** — avoids IPv6 fallback latency; use `127.0.0.1` not `localhost`
- **`timeout: 3600`** — per-model timeout (1 hour), prevents stalled requests
- **`num_ctx: 4096`** — **critical** — caps KV-cache allocation to fit safely in 16 GB RAM
- **`request_timeout: 600`** (global setting) — 10-minute global timeout; works around an aiohttp connection-reuse bug that causes 500s after ~48 min

## Swap Memory (Critical for Larger Models)

If you intend to try DeepSeek-Coder-V2 Lite (16B) or CodeLlama 13B, you **must** have
swap configured. See `specs/vps-setup.md` for swap setup instructions (6 GB swap file).

With swap + `num_ctx=4096`:
- Initial model load may touch swap during startup (normal)
- During iteration, peak memory should stay within RAM
- If peak memory exceeds RAM, swap provides a safety net (slower, but no OOM kill)

## Benchmark Template

After wiring a new model, run one iteration of Ralph and observe:

```bash
# Before: record baseline
$ free -h                   # note available memory
$ ollama ps                 # confirm model is loaded

# During: monitor in another terminal
$ watch -n 1 'free -h && echo "---" && ollama ps'

# After: record peak and residual
$ free -h                   # should recover to near-baseline if no model left in memory
$ docker stats --no-stream  # confirm Docker container memory usage
```

Record:
- Time to first token
- Tokens/second
- Peak RAM used (reported by `docker stats`)
- Task completion quality (did it finish the task like Claude would?)

Acceptable metrics:
- Time to first token: < 5 seconds
- Tokens/second: > 10 (7B Q4 typical: 15–20 t/s)
- Task quality: equivalent to Sonnet for the task at hand

## Acceptance Criteria

- [ ] Chosen model appears in `ollama list`
- [ ] LiteLLM proxy starts: `curl http://localhost:4000/health` returns `{"status":"healthy"}`
- [ ] Ralph completes at least 1 iteration with `RALPH_MODEL=ollama/qwen2.5-coder:7b-instruct-q4_K_M`
- [ ] No OOM kill in `dmesg` or Docker logs
- [ ] `free -h` shows ≥ 2 GB available after iteration completes
- [ ] Session log (`logs/sessions/*.json`) records the correct model name

## Troubleshooting

### Model not found in Ollama

```bash
# List all pulled models
ollama list

# If empty, pull it
ollama pull qwen2.5-coder:7b-instruct-q4_K_M
```

### LiteLLM health check fails

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Check LiteLLM logs
docker logs agentx-litellm-1

# Restart LiteLLM
docker restart agentx-litellm-1
```

### OOM kill during iteration

```bash
# Check system logs
dmesg | tail -20

# Check swap status
free -h
swapon --show

# If no swap, enable it (requires sudo) or switch to a smaller model
```

### Model runs but output quality is poor

Try a higher quantization (Q5_K_M instead of Q4_K_M) or a larger model (13B instead of 7B),
but verify RAM headroom first.

## References

- [Ollama Models](https://ollama.com/library)
- [LiteLLM Docs](https://docs.litellm.ai)
- [Qwen2.5-Coder Hugging Face](https://huggingface.co/Qwen/Qwen2.5-Coder)
- [DeepSeek-Coder-V2 Hugging Face](https://huggingface.co/deepseek-ai/DeepSeek-Coder-V2)
