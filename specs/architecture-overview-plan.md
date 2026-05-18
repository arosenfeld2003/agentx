# Plan: Architecture Clarity Spec

## Context

The agentx repo has grown organically across several phases and now has overlapping artifacts that create confusion: `specs/` vs `IMPLEMENTATION_PLAN.md`, a `scaffold/src/` stub vs the real `src/`, an `AGENTS.md` with a placeholder section, and a stale `agent_git/` mirror sitting untracked. The goal is a single reference document that resolves this ambiguity, plus targeted cleanup of the most confusing artifacts.

---

## Confusions to Resolve

### 1. `specs/` vs `IMPLEMENTATION_PLAN.md`

These serve completely different purposes:

| File | Role | Who writes it | Who reads it |
|---|---|---|---|
| `specs/*.md` | *What* to build and *why* — feature design, architecture decisions, feasibility studies | Humans (you) | Ralph as reference material during planning |
| `IMPLEMENTATION_PLAN.md` | *What's next* — a live task checklist with `[ ]`/`[~]`/`[x]` state | Humans + Ralph (updates checkbox state) | Ralph every iteration to find its next task; `loop.sh` to detect completion |

Specs are permanent design records. The plan is a mutable task queue.

### 2. `scaffold/src/` vs root `src/`

Non-issue: `scaffold/` is excluded from the agentx repo entirely via `.gitignore`. It lives on the VPS at `/opt/agentx/scaffold` and is never visible when working in the agentx directory. The only `src/` that matters is the root `src/` — the Python listener and send_task tool.

### 3. `AGENTS.md` "Ralph will update this section"

This is a convention from the Ralph Wiggum scaffold template. The intent: Ralph accumulates codebase knowledge over time and writes it back to `AGENTS.md`. In practice this section is an empty stub. It should either be explicitly removed/replaced with a static description, or noted as aspirational. It is not currently used by any script.

### 4. Two git accounts, two checkouts, one canonical remote

**The intended model:**

- **Canonical remote:** `git@github.com:runggp/agentx.git` — the agent owns this repo; it is the source of truth
- **Human's checkout** (`/repos/agentx/`): two remotes — `origin = arosenfeld2003/agentx` (personal), `runggp = runggp/agentx`. Human reviews PRs on runggp/agentx via GitHub; direct pushes to the runggp remote from the human's checkout blur the line and should be avoided
- **Agent's checkout** (`agent_git/agentx/` locally, `/opt/agentx/` on VPS): single remote — `origin = runggp/agentx`. This is where the agent works, commits, and pushes

`agent_git/` exists on the Mac to mirror the VPS structure locally — it has the correct remote (`runggp/agentx` as origin) and the correct git identity. On the VPS, this role is played by `/opt/agentx/` directly.

**The confusion** is that the human made direct pushes from `/repos/agentx/` using the `runggp` remote, bypassing the PR flow. The intended workflow is:
1. Human sends task email → agent works in its checkout → agent pushes branch to `runggp/agentx` → agent merges its own PR
2. Human pulls updates from `runggp` remote to review

**For app repos:** agent creates repositories under the `runggp` GitHub account as needed (when a task warrants it), clones them to the VPS workspace, works, and merges its own PRs. Multiple agents can work on separate branches of the same repo simultaneously. The harness never owns application repos — GitHub does.

---

## Approach

### Primary deliverable: `specs/architecture-overview.md`

A canonical reference document covering:

1. **System tiers** — VPS host daemon vs Docker container, what runs where
2. **Git identity model** — two accounts (human: arosenfeld2003, agent: runggp), two checkouts, one canonical remote (`runggp/agentx`); agent always commits as runggp; human interacts via PRs only
3. **Task lifecycle** — the canonical path: email → listener → IMPLEMENTATION_PLAN.md → ralph.sh → loop → agent merges PR → reply
4. **Where tasks live** — `IMPLEMENTATION_PLAN.md` is the live task queue; `specs/` is design documentation; these are not interchangeable
5. **Ralph execution model** — what `./ralph.sh` actually does, the full chain to `loop.sh`, how iterations work, when it stops
6. **Progress tracking** — checkbox states `[ ]`/`[~]`/`[x]`, what each means, how `loop.sh` uses them to detect completion
7. **Viewing logs** — session logs at `logs/sessions/<session-id>.json`, Entire checkpoints, notification email after each run
8. **App repo model** — agent creates repos under `runggp` as needed; multiple agents can work in parallel on separate branches; harness ≠ application
9. **Artifact map** — table of every key file: role, who reads it, who writes it

### Secondary changes: targeted cleanup

1. **`AGENTS.md`** — Update the "Codebase Patterns" stub section: either remove it or replace it with a static note explaining it is not currently active
2. **`IMPLEMENTATION_PLAN.md` header** — Add a 2-line comment at top clarifying its role vs `specs/`

---

## Critical Files

- **Create:** `specs/architecture-overview.md` (new)
- **Edit:** `AGENTS.md` — update the Codebase Patterns stub
- **Edit:** `IMPLEMENTATION_PLAN.md` — add brief header comment

---

## Verification

- Read all four changed artifacts and confirm they're internally consistent
- Confirm `specs/architecture-overview.md` answers all four confusions explicitly
- Confirm `IMPLEMENTATION_PLAN.md` still parses correctly for `loop.sh` (grep pattern `^\s*- \[ \]` still matches tasks)
- No code changes; no tests to run
