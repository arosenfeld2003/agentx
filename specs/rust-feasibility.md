# Rust Feasibility: Full Harness Rewrite

## Summary

Rewriting the agentx harness in Rust is technically feasible for most components. The main friction points are the absent official Claude API SDK and Rust's compile step conflicting with the agent's ability to self-modify and re-run. Recommended split: **loop engine + email stack in Rust, LiteLLM proxy stays Python**.

---

## Component-by-Component Assessment

| Component | Current | Rust equivalent | Feasibility |
|-----------|---------|-----------------|-------------|
| Loop engine | Bash (`loop.sh`) | `tokio` async runtime | High |
| Claude API client | `claude` CLI (Node) | `reqwest` + `serde_json` | Medium |
| IMAP listener | Python `aioimaplib` | `async-imap` | High |
| SMTP responder | Python `aiosmtplib` | `lettre` | High |
| Spec/markdown parser | Python `mistletoe` | `pulldown-cmark` | High |
| Tool dispatch (subprocess) | Bash | `tokio::process::Command` | High |
| Git operations | `git` subprocess | `git2` crate or subprocess | High |
| Docker management | `docker compose up` subprocess | `bollard` (Docker API) or subprocess | High |
| Structured logging | Python `structlog` | `tracing` + `tracing-subscriber` | High |
| LiteLLM proxy | Python service | No direct equivalent | Low — keep Python |

---

## Claude API

There is no official Anthropic Rust SDK. Options:

1. **Hand-roll HTTP calls** via `reqwest` + `serde_json`. The API is simple REST; this works fine for non-streaming use. ~200 lines of boilerplate.
2. **Streaming responses** require SSE parsing — doable with `reqwest` + `eventsource-stream` crate, but more work.
3. **Community crates**: `anthropic-rs` exists but is not officially maintained. Usable as a reference, not a dependency.

**Verdict:** Medium effort. REST-only (no streaming) is straightforward; streaming adds ~1 day of work. Not a blocker.

---

## Self-Modification / Self-Improvement

The harness is designed to eventually improve itself. This is where Rust creates friction:

- **Bash/Python**: agent edits a script, it runs immediately on next iteration.
- **Rust**: agent edits source, must `cargo build` before changes take effect. Build time on VPS (4 vCPU, 16 GB RAM): ~30–90 seconds for incremental, ~3–5 min clean.

This makes the self-improvement loop slower but not impossible. The agent could:
- Trigger `cargo build --release` as a tool call
- Validate the binary compiles before committing
- Fall back to the previous binary on build failure

**Verdict:** Workable, but adds friction to Phase 3 (self-monitoring / self-improvement). Acceptable if the performance and reliability wins are worth it.

---

## Deployment

A Rust binary is a single static executable (with musl target). Advantages:

- No runtime dependency on Python, Node, or their package managers
- `COPY ./target/x86_64-unknown-linux-musl/release/agentx /usr/local/bin/` — trivial Dockerfile
- Smaller container image: ~15 MB vs ~200 MB for a Python image
- No virtualenv management on VPS

Cross-compile from Mac → Linux x86_64:
```bash
cargo build --release --target x86_64-unknown-linux-musl
```

---

## Recommendation

**Hybrid approach:**

| Layer | Language | Rationale |
|-------|----------|-----------|
| Loop engine binary | Rust | Reliability, single binary, structured logging via `tracing` |
| Email listener + SMTP | Rust (same binary) | `async-imap` + `lettre` are mature; unified deployment |
| Claude API client | Rust (hand-rolled) | Acceptable effort for the REST-only path |
| LiteLLM proxy | Python | No Rust equivalent worth maintaining |
| Docker management | Subprocess calls | `bollard` adds complexity without much gain at this scale |

**Implementation order if going Rust:**

1. Scaffold `agentx` binary crate in `crates/agentx/`
2. Port email listener (`async-imap` + `lettre`) — most isolated, easiest to test
3. Port loop engine (subprocess dispatch, file I/O, git commit via subprocess)
4. Hand-roll Claude API client (`reqwest`, non-streaming first)
5. Wire together; remove Python email components
6. Benchmark compile time on VPS before committing to self-modification flow

**If not going Rust now:** keep Python for Phase 0–1 (faster to iterate), revisit after the harness is stable and email loop is proven.

---

## Open Questions

- Is streaming required in Phase 1? (Affects Claude API implementation complexity.)
- Does the self-modification loop need to happen within a single Ralph session, or across sessions? (Affects how bad the compile step is in practice.)
- musl target acceptable for VPS deployment, or is glibc preferred?
