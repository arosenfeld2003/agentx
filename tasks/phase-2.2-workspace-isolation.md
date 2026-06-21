# Phase 2.2: Workspace Isolation

## Status: `[~]` — implemented, pending real-world verification

## Goal

Route each email task to an independent workspace so ralph works on external projects (APIs, MCPs, new services) without touching the agentx codebase.

## Acceptance Criteria

- [x] Email body with `project: my-service` frontmatter creates `/opt/projects/my-service/` and runs ralph there
- [x] Email with no frontmatter (or `project: _ephemeral`) runs in `/opt/projects/.inbox/<timestamp>/`
- [x] Email with `project: agentx` runs in `/opt/agentx/` (existing behavior)
- [x] Frontmatter is stripped from TASK.md — only the body is written
- [x] `WORKSPACE_PATH` env var passed to ralph reflects the routed workspace (not always `/opt/agentx`)
- [x] `vps-compose.yml` binds `/opt/projects` into Docker so ralph can read/write project files
- [x] `AGENTX_PROJECTS_ROOT` env var configures the projects root (default `/opt/projects`)
- [x] All tests pass (64/64)

## Files Changed

- `src/listener.py` — `_parse_frontmatter`, `Config.projects_root`, updated `dispatch_task`
- `src/tests/test_listener.py` — `TestParseFrontmatter` (5 tests), 5 new `TestDispatchTask` workspace routing tests, 2 new `TestConfigFromEnv` tests
- `vps-compose.yml` — `/opt/projects` volume mount + `AGENTX_PROJECTS_ROOT` env var in ralph service
- `secrets.env.example` — `AGENTX_PROJECTS_ROOT`, `GITHUB_PERSONAL_ACCESS_TOKEN`
- `AGENTS.md` — Project Workspaces section, External Tools section
- `README.md` — Frontmatter format in email user guide

## VPS Setup (one-time)

```bash
mkdir -p /opt/projects
# Add to secrets.env if using non-default path:
# AGENTX_PROJECTS_ROOT=/opt/projects
# Restart listener after secrets change
```

## Email Format

```
Subject: [task] build a REST API

---
project: my-service
---

# Rate Limiting

Add per-IP rate limiting using a token bucket. Configurable via RATE_LIMIT_RPM.
```
