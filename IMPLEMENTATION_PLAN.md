# Implementation Plan

## Current Focus

- [ ] **Phase 0d: Structured logging** — JSON log per session, readable by future agent iterations
- [ ] **Phase 0f: First self-task** — Send a spec email to agentx@runggp.com tasking ralph to research and write `specs/local-models.md`: ranked shortlist of Ollama-compatible models for general-purpose and coding tasks that fit within 10GB RAM (16GB VPS, ~6GB reserved for OS/Docker), including model name, size, quantization level, and a one-line rationale, covering at least one strong coding-focused and one general-purpose option. Listener dispatches it as a ralph loop and replies with results via SMTP; proves the full operator email round-trip end-to-end.
- [ ] **Phase 1: Spend tracking** — Log token estimates per iteration, session ceiling, email alert on threshold
- [ ] **Phase 2: Local models** — Install Ollama, pull Qwen3-14B, wire LiteLLM, benchmark vs Claude API
- [ ] **Phase 2.1: Model router** — Route tasks to models based on type; local for cost, API for quality
- [ ] **Phase 3: Self-monitoring** — Agent reads its own cost log and audit trail as tool inputs

## Completed

- [x] **Phase 0a: VPS baseline** — SSH, Docker, git, credentials — see `specs/vps-setup.md`
- [x] **Phase 0b: Lift and shift** — scaffold runs on VPS with Claude API (OAuth mode)
- [x] **Phase 0c: VPS compose** — `vps-compose.yml` with VPS paths, persistent workspace, Entire enabled
- [x] **Phase 0e: Email listener** — `src/listener.py` implements async IMAP polling (aioimaplib), spec extraction from body/.md attachment, Ralph dispatch via subprocess, SMTP reply (aiosmtplib), and `[stop]`/`[status]` control commands. Tests in `src/tests/test_listener.py`. Run on VPS host: `uv run --env-file /opt/agentx/secrets.env src/listener.py`

## Notes

### Running tests (requires Python and uv on the VPS host)
```bash
cd /opt/agentx
uv run --dev pytest
uv run --dev pytest --tb=short -v
```

### Linting + type-check
```bash
uv run --dev ruff check src/
uv run --dev mypy src/listener.py
```

### Known constraints
- Docker container (node:22-slim) has no Python — listener runs on VPS host, not inside Docker
- `pyproject.toml` specifies Python >=3.14; uv installs the correct version automatically
- Listener secrets come from `secrets.env` via `--env-file` flag; never baked into Docker
