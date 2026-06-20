# AgentX — Operator Guide

This is the human operator's reference for running, reviewing, and steering the ralph autonomous development loop on the VPS.

---

## Quick Reference

```bash
# On the VPS — standard workflow
cd /opt/agentx && git checkout main && git pull
./ralph.sh plan 1        # generate / update IMPLEMENTATION_PLAN.md
./ralph.sh build 5       # implement up to 5 iterations
```

```bash
# On your Mac — review a session after it completes
git fetch runggp
git diff main...runggp/ralph/<branch>
gh pr create --base main --head ralph/<branch> --repo runggp/agentx
```

---

## The Loop

Each `./ralph.sh` invocation:

1. Creates a fresh `ralph/workspace-<timestamp>` branch from `main`
2. Reads `PROMPT_build.md` (or `PROMPT_plan.md`) and runs Claude in a loop
3. Claude commits as it goes, pushing each commit to origin
4. Entire records a checkpoint on `entire/checkpoints/v1` at each commit
5. At the end, prints a session summary and exits

**Plan before build.** Always run `plan 1` after pulling new specs or making changes to `IMPLEMENTATION_PLAN.md`. The plan loop reads specs and produces a task list. The build loop consumes that task list.

---

## Reviewing a Session

### See what changed
```bash
git fetch runggp
git log runggp/ralph/<branch> --oneline        # commits this session
git diff main...runggp/ralph/<branch>           # full diff vs main
```

### Read the decision trail (Entire)
```bash
git fetch runggp entire/checkpoints/v1
git log FETCH_HEAD --oneline                    # one entry per commit
git show FETCH_HEAD                             # latest checkpoint detail
```

Checkpoints capture: the prompt sent, Claude's response, tool calls made, files touched, token usage. Use this when a commit looks wrong and you want to understand what Claude was thinking.

### Merge or discard
```bash
# Merge via PR (preferred)
gh pr create --base main --head ralph/<branch> --repo runggp/agentx

# Discard a session entirely
git push runggp --delete ralph/<branch>
```

---

## Controlling the Agent via Email

The listener runs on the VPS host and polls `agentx@runggp.com` every 30 seconds. Send emails to that address to trigger tasks, check status, or stop the loop.

### Who can send

By default only `agentx@runggp.com` itself is authorised (for self-sent tasks via `send_task.py`). To send from your personal address, add it to `secrets.env`:

```
AGENTX_ALLOWED_SENDERS=you@example.com
```

Restart the listener after changing this.

### Subject prefixes

All commands live in the subject line using `[command]` prefixes:

| Subject | Effect |
|---|---|
| `[task] <description>` | Run ralph with the default model |
| `[task:local] <description>` | Force local model (`RALPH_LOCAL_MODEL`, default `qwen3:8b`) |
| `[task:local:qwen3:14b] <description>` | Force a specific local model by name |
| `[task:api] <description>` | Force Claude API, bypassing LiteLLM |
| `[task:api:claude-opus-4-8] <description>` | Force a specific Claude API model |
| `[status]` | Reply with loop state and recent commits |
| `[stop]` | Write a `.stop` sentinel — loop exits after its current iteration |

Emails with unrecognised subjects are silently ignored.

### Writing a task email

The email body becomes the task spec that ralph works from. Write it as markdown:

```
Subject: [task] add rate limiting to the API

# Rate Limiting

Add per-IP rate limiting to the proxy. Use a token bucket algorithm.

## Acceptance Criteria
- [ ] Requests over 60/min from a single IP return 429
- [ ] Limit is configurable via env var RATE_LIMIT_RPM
```

You can also attach a `.md` file instead of writing in the body — the attachment takes priority.

### Send a task from the VPS (programmatic)

```bash
cd /opt/agentx
echo "# Spec\n\nDo the thing." | uv run --env-file /opt/agentx/secrets.env src/send_task.py "task description"
# or with a file:
uv run --env-file /opt/agentx/secrets.env src/send_task.py "task description" tasks/my-task.md
```

### What the reply looks like

After ralph finishes you'll receive a reply with:

```
Ralph loop completed.

Task: <description>
Model: <model used>

--- Output (last 50 lines) ---
<ralph stdout>
```

If the loop times out (default 30 min) or exits non-zero, the reply will say so.

### Quoted replies and HTML

If you reply to an agentx email (e.g. to follow up with a new `[task]`), the listener strips quoted lines (`>`) and `On ... wrote:` blocks before extracting the spec. The spec is whatever is in the **new** content above the quote. HTML emails are also supported — the listener converts them to plain text.

### Starting and stopping the listener

```bash
# Start
cd /opt/agentx && uv run --env-file /opt/agentx/secrets.env src/listener.py

# Stop (Ctrl-C, or send a [stop] email to stop the ralph loop first)
```

The listener reconnects automatically if the IMAP connection drops.

---

## Steering the Agent

### Update the task list
Edit `IMPLEMENTATION_PLAN.md` directly on `main`, then run `./ralph.sh plan 1` to let Ralph re-analyse and update it. Ralph reads this file at the start of every iteration.

### Change the prompt
Edit `PROMPT_build.md` or `PROMPT_plan.md` on `main`. These are the top-level instructions Claude receives each iteration. Keep changes focused — the prompts are already tuned.

### Limit scope
```bash
RALPH_MAX_ITERATIONS=2 ./ralph.sh build   # cap at 2 iterations
./ralph.sh plan 1                          # plan only, no code changes
```

### Disable Entire for a run (e.g. debugging)
```bash
RALPH_ENTIRE_ENABLED=false ./ralph.sh build 2
```

---

## When Things Go Wrong

### VPS is on a stale ralph branch
Ralph auto-recovers now, but if you're running git commands manually:
```bash
git checkout main && git pull origin main
```

### Git permission errors (`.git/objects`)
The scaffold runs as uid 1001 (`ralph`). If you cloned as root:
```bash
chown -R 1001:1001 /opt/agentx
```

### Ralph exits with `error: insufficient permission` on stash
Same ownership issue — fix with `chown` above, then retry.

### Push fails (SSH)
```bash
ssh -i /opt/agentx/.agent-ssh/hostinger -T git@github.com   # test key
```

### `entire: not found` errors on host-side git operations
`entire` only exists inside the Docker container. If `entire enable` ran inside the container, it installs git hooks into `.git/hooks/` that call `entire` — these break any git commands run directly on the VPS host. Remove them:
```bash
rm /opt/agentx/.git/hooks/commit-msg /opt/agentx/.git/hooks/pre-push /opt/agentx/.git/hooks/post-commit 2>/dev/null
```
This is safe — the hooks only serve Entire observability inside the container, where `entire` is available.

### Behind origin warning at startup
Ralph warns if `main` has unpulled commits. Pull before running:
```bash
cd /opt/agentx && git pull origin main
```

---

## Secrets

Secrets live in `/opt/agentx/secrets.env` on the VPS. Never commit this file.

```bash
nano /opt/agentx/secrets.env   # edit
chmod 600 /opt/agentx/secrets.env
```

See `secrets.env.example` for the required keys.

---

## Scaffold Updates

The scaffold (Dockerfile + loop scripts) lives in `/opt/agentx/scaffold`, a separate git repo (`runggp/scaffold`):

```bash
cd /opt/agentx/scaffold && git pull
```

Pull this when scaffold changes are pushed (e.g. loop logic fixes, Entire integration updates). The next `./ralph.sh` run will rebuild the Docker image automatically.

---

## Key Files

| File | Purpose |
|---|---|
| `IMPLEMENTATION_PLAN.md` | Live task list — Ralph reads and updates this |
| `PROMPT_build.md` | Top-level build instructions for Claude |
| `PROMPT_plan.md` | Top-level planning instructions for Claude |
| `vps-compose.yml` | Docker config for VPS runs |
| `secrets.env.example` | Template for `/opt/agentx/secrets.env` |
| `specs/` | Feature specs Ralph implements against |
| `specs/entire-observability.md` | How to use Entire audit logs |
| `specs/vps-setup.md` | One-time VPS setup reference |
