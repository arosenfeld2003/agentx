# Phase 2.1: Model Router

**Status:** `[ ]` — not started; depends on Phase 2

## Description

Route tasks to models based on task type: local Qwen3 for routine/cheap work, Claude
API for tasks requiring higher reasoning quality.

## Design

Routing signal lives in the task spec or subject line. Suggested convention:

```
[task:local] <description>   — force local model
[task:api]   <description>   — force Claude API
[task]       <description>   — use default (configurable via RALPH_DEFAULT_MODEL)
```

The listener reads the routing hint from the subject prefix and sets `RALPH_MODEL`
before invoking `ralph.sh`.

Alternatively: a simple keyword heuristic in the listener (e.g. tasks mentioning
"refactor", "rename", "fix typo" → local; "architect", "design", "security" → API).

## Implementation Steps

1. Extend `parse_subject` in `src/listener.py` to extract an optional model hint
2. Pass hint as env var when calling `ralph.sh` (e.g. `RALPH_MODEL=qwen3:8b`)
3. Add `RALPH_DEFAULT_MODEL` to `secrets.env.example` (defaults to local once Phase 2 verified)
4. Tests in `src/tests/test_listener.py` for new subject formats
5. Document routing logic in `AGENTS.md`

## Acceptance Criteria

- [ ] `[task:local]` email routes to Qwen3, session log confirms
- [ ] `[task:api]` email routes to Claude, session log confirms
- [ ] `[task]` email uses `RALPH_DEFAULT_MODEL`
- [ ] Tests cover all three routing paths (mocked subprocess env check)

## Dependencies

- Phase 2 (local models) must be verified before this can be tested end-to-end
