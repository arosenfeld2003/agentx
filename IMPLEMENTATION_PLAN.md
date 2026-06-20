# Implementation Plan

## Status Legend
- `[ ]` — not started
- `[~]` — implemented, pending real-world verification
- `[x]` — verified complete (real execution observed)

---

## Active Tasks

Each task lives in its own file under `tasks/`. To run ralph on a single task:
```bash
./ralph.sh task tasks/<filename>.md
```

| Status | Task | File |
|--------|------|------|
| `[x]` | Phase 2: Local models (Ollama + LiteLLM) | [tasks/phase-2-local-models.md](tasks/phase-2-local-models.md) |
| `[x]` | Phase 0f: First self-task (email round-trip) | [tasks/phase-0f-first-self-task.md](tasks/phase-0f-first-self-task.md) |
| `[~]` | Phase 2.1: Model router | [tasks/phase-2.1-model-router.md](tasks/phase-2.1-model-router.md) |

---

## Completed

- [x] **Phase 0a** — VPS baseline (SSH, Docker, git, credentials) — `specs/vps-setup.md`
- [x] **Phase 0b** — Lift and shift: scaffold runs on VPS with Claude API
- [x] **Phase 0c** — `vps-compose.yml` with VPS paths, persistent workspace, Entire enabled
- [x] **Phase 0d** — Structured logging: `scaffold/lib/session-logger.js` writes per-iteration JSON
- [x] **Phase 0e** — Email listener: `src/listener.py` with IMAP polling, ralph dispatch, SMTP reply
- [x] **Phase 1** — Spend tracking: `check-spend` in session-logger, ceiling env var, loop guard
- [x] **Phase 3** — Self-monitoring: session audit trail prepended to each loop prompt

---

## Notes

### Running tests
```bash
uv run --dev pytest
uv run --dev pytest --tb=short -v
```

### Lint + type-check
```bash
uv run --dev ruff check src/
uv run --dev mypy src/listener.py
```

### Phase 2 verification complete

Verified 2026-06-17. Full pipeline running on VPS:
`Claude Code (ralph) → proxy:4001 → LiteLLM:4000 → Ollama (qwen2.5-coder:7b-instruct-q4_k_m)`

All three services managed by `vps-compose.yml` and restart automatically.
See `tasks/phase-2-local-models.md` → Known Gotchas for operational lessons.

### Known constraints
- `uv` is in the Docker container — use `uv run` for Python scripts and tests
- The listener (`src/listener.py`) runs on the VPS host, not inside Docker
- `pyproject.toml` requires Python >=3.14; uv installs it automatically
- Listener secrets come from `secrets.env` via `--env-file`; never baked into Docker
- `SMTP_USER` is always implicitly allowed by the listener
