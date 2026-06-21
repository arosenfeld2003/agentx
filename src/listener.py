"""
agentx email listener

Polls agentx@runggp.com IMAP inbox for task emails, dispatches ralph.sh,
and replies with a work summary.

Usage:
    uv run --env-file /opt/agentx/secrets.env src/listener.py

Subject prefixes:
    [task] <description>              — run ralph with default model
    [task:local] <description>        — force local model (RALPH_LOCAL_MODEL, default ollama/qwen3:8b)
    [task:local:qwen3:14b] <desc>     — force specific local model by name
    [task:api] <description>          — force Claude API (bypasses LiteLLM)
    [task:api:claude-opus-4-8] <desc> — force specific Claude API model
    [stop]                            — write .stop sentinel; loop exits cleanly
    [status]                          — reply with current loop state and recent git commits
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import html.parser
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import aioimaplib
import aiosmtplib

log = logging.getLogger("agentx.listener")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    imap_host: str
    imap_port: int
    imap_user: str
    imap_pass: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    workspace: Path
    ralph_sh: Path
    poll_interval: int = 30
    allowed_senders: frozenset[str] = frozenset()
    ralph_timeout: int = 1800
    ralph_default_model: str = ""
    ralph_local_model: str = ""
    ralph_api_model: str = ""
    ralph_iterations: int = 2
    projects_root: Path = Path("/opt/projects")

    @classmethod
    def from_env(cls) -> "Config":
        def require(key: str) -> str:
            val = os.environ.get(key, "")
            if not val:
                raise RuntimeError(f"Required env var {key!r} is not set")
            return val

        workspace = Path(os.environ.get("WORKSPACE_PATH", "/opt/agentx"))
        ralph_sh = Path(os.environ.get("RALPH_SH", str(workspace / "ralph.sh")))

        imap_user = require("IMAP_USER")
        smtp_user = require("SMTP_USER")
        raw_senders = os.environ.get("AGENTX_ALLOWED_SENDERS", "")
        allowed_senders: frozenset[str] = frozenset(
            s.strip().lower() for s in raw_senders.split(",") if s.strip()
        ) | {smtp_user.lower()}  # self-sent tasks are always permitted

        return cls(
            imap_host=os.environ.get("IMAP_HOST", "imap.hostinger.com"),
            imap_port=int(os.environ.get("IMAP_PORT", "993")),
            imap_user=imap_user,
            imap_pass=require("IMAP_PASS"),
            smtp_host=os.environ.get("SMTP_HOST", "smtp.hostinger.com"),
            smtp_port=int(os.environ.get("SMTP_PORT", "465")),
            smtp_user=smtp_user,
            smtp_pass=require("SMTP_PASS"),
            workspace=workspace,
            ralph_sh=ralph_sh,
            poll_interval=int(os.environ.get("AGENTX_POLL_INTERVAL", "30")),
            allowed_senders=allowed_senders,
            ralph_timeout=int(os.environ.get("AGENTX_RALPH_TIMEOUT", "1800")),
            ralph_default_model=os.environ.get("RALPH_DEFAULT_MODEL", ""),
            ralph_local_model=os.environ.get("RALPH_LOCAL_MODEL", ""),
            ralph_api_model=os.environ.get("RALPH_API_MODEL", ""),
            ralph_iterations=int(os.environ.get("AGENTX_RALPH_ITERATIONS", "2")),
            projects_root=Path(os.environ.get("AGENTX_PROJECTS_ROOT", "/opt/projects")),
        )


# ---------------------------------------------------------------------------
# Email parsing
# ---------------------------------------------------------------------------

class _HTMLStripper(html.parser.HTMLParser):
    """Convert HTML to plain text, skipping script/style blocks."""
    _SKIP = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.append(data)

    def get_text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self._buf)).strip()


def _strip_quoted_reply(text: str) -> str:
    """Remove quoted reply content from a plain-text email body."""
    # Remove "On <date>, <name> wrote:" separator and everything after
    m = re.search(r"\n+On .{0,200}?wrote:\s*\n", text, flags=re.DOTALL)
    if m:
        text = text[:m.start()]
    # Remove lines starting with > (standard quote prefix)
    lines = [line for line in text.splitlines() if not line.startswith(">")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract_spec(msg: email.message.Message) -> str:
    """Return markdown spec text from an email.

    Preference order:
    1. First .md attachment
    2. text/plain body
    3. text/html body stripped to plain text (fallback)
    """
    plain_body: str | None = None
    html_body: str | None = None

    for part in msg.walk():
        content_type = part.get_content_type()
        filename = part.get_filename() or ""
        disposition = str(part.get("Content-Disposition", ""))

        if "attachment" in disposition and filename.endswith(".md"):
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                return payload.decode("utf-8", errors="replace").strip()

        if content_type == "text/plain" and "attachment" not in disposition:
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                plain_body = payload.decode("utf-8", errors="replace").strip()

        elif content_type == "text/html" and "attachment" not in disposition:
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                html_body = payload.decode("utf-8", errors="replace").strip()

    if plain_body:
        return _strip_quoted_reply(plain_body)
    if html_body:
        stripper = _HTMLStripper()
        stripper.feed(html_body)
        return _strip_quoted_reply(stripper.get_text())
    return ""


def parse_subject(raw_subject: str) -> tuple[str, str, str | None]:
    """Return (prefix, description, model_hint) from a subject line.

    Examples:
        "[task] deploy harness"        -> ("task", "deploy harness", None)
        "[task:local] fix typo"        -> ("task", "fix typo", "local")
        "[task:local:qwen3:14b] fix"   -> ("task", "fix", "local:qwen3:14b")
        "[task:api] design arch"       -> ("task", "design arch", "api")
        "[task:api:claude-opus-4-8] x" -> ("task", "x", "api:claude-opus-4-8")
        "[stop]"                       -> ("stop", "", None)
    """
    m = re.match(r"^\[(\w+)(?::([^\]]*))?\]\s*(.*)", raw_subject.strip(), re.IGNORECASE)
    if m:
        hint = m.group(2).lower() if m.group(2) else None
        return m.group(1).lower(), m.group(3).strip(), hint
    return "", raw_subject.strip(), None


def _resolve_model(hint: str | None, cfg: Config) -> tuple[str | None, bool]:
    """Return (model_name, bypass_litellm) from a routing hint.

    bypass_litellm=True means ANTHROPIC_BASE_URL should be removed from the
    subprocess env so the Anthropic SDK calls the real API instead of LiteLLM.
    """
    if hint is None:
        return (cfg.ralph_default_model or None), False
    if hint == "api":
        return cfg.ralph_api_model or "claude-sonnet-4-6", True
    if hint.startswith("api:"):
        return hint[4:], True
    if hint == "local":
        return cfg.ralph_local_model or "ollama/qwen3:8b", False
    if hint.startswith("local:"):
        return hint[6:], False
    return hint, False


def _parse_frontmatter(spec: str) -> tuple[dict[str, str], str]:
    """Parse optional YAML-style frontmatter from a spec string.

    Returns (fields, body) where fields is a dict of key: value pairs
    and body is the spec with frontmatter stripped.

    Example input:
        ---
        project: my-service
        ---
        # Task body
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", spec.strip(), re.DOTALL)
    if not m:
        return {}, spec.strip()
    raw, body = m.group(1), m.group(2).strip()
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    return fields, body


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

async def dispatch_task(cfg: Config, spec: str, description: str, model_hint: str | None = None) -> str:
    """Write spec to TASK.md and run ralph in task mode.

    Parses optional YAML frontmatter from the spec to determine the workspace:
    - `project: agentx`        → cfg.workspace (/opt/agentx)
    - `project: <name>`        → cfg.projects_root/<name>/
    - no frontmatter / `_ephemeral` → cfg.projects_root/.inbox/<timestamp>/

    Returns a human-readable work summary string.
    """
    fields, task_body = _parse_frontmatter(spec)
    project = fields.get("project", "")

    if project == "agentx":
        workspace = cfg.workspace
    elif project and project != "_ephemeral":
        workspace = cfg.projects_root / project
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        workspace = cfg.projects_root / ".inbox" / ts

    workspace.mkdir(parents=True, exist_ok=True)

    task_file = workspace / "TASK.md"
    task_file.write_text(task_body, encoding="utf-8")
    log.info("Wrote task to %s (project=%r)", task_file, project or "_ephemeral")

    env = {**os.environ, "WORKSPACE_PATH": str(workspace)}
    model_name, bypass_litellm = _resolve_model(model_hint, cfg)
    if model_name:
        env["RALPH_MODEL"] = model_name
    if bypass_litellm:
        env.pop("ANTHROPIC_BASE_URL", None)
    env["RALPH_MAX_ITERATIONS"] = str(cfg.ralph_iterations)
    log.info(
        "Launching ralph.sh task at %s (model=%s bypass_litellm=%s iterations=%d)",
        cfg.ralph_sh, model_name, bypass_litellm, cfg.ralph_iterations,
    )

    proc = await asyncio.create_subprocess_exec(
        str(cfg.ralph_sh), "task", str(task_file),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(workspace),
    )
    communicate_task = asyncio.create_task(proc.communicate())
    done, _ = await asyncio.wait([communicate_task], timeout=cfg.ralph_timeout)
    if not done:
        proc.kill()
        communicate_task.cancel()
        try:
            await communicate_task
        except (asyncio.CancelledError, Exception):
            pass
        log.error("ralph.sh timed out after %ds", cfg.ralph_timeout)
        return f"Ralph loop timed out after {cfg.ralph_timeout // 60} minutes.\n\nTask: {description}"
    stdout, _ = communicate_task.result()

    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    exit_code = proc.returncode or 0
    status = "completed" if exit_code == 0 else f"exited with code {exit_code}"
    summary = (
        f"Ralph loop {status}.\n\n"
        f"Task: {description}\n"
        f"Model: {model_name or 'default'}\n\n"
        f"--- Output (last 50 lines) ---\n"
        + "\n".join(output.splitlines()[-50:])
    )
    log.info("Ralph finished (exit=%d)", exit_code)
    return summary


def get_status(cfg: Config) -> str:
    """Return current loop state and recent git commits."""
    lines: list[str] = ["agentx status\n"]

    stop_file = cfg.workspace / ".stop"
    if stop_file.exists():
        lines.append("Stop sentinel is present — loop will exit after current iteration.\n")
    else:
        lines.append("No stop sentinel.\n")

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            cwd=str(cfg.workspace),
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines.append("\nRecent commits:\n")
        lines.append(result.stdout or "(none)")
    except Exception as exc:
        lines.append(f"\nCould not read git log: {exc}")

    return "\n".join(lines)


def write_stop_sentinel(cfg: Config) -> None:
    stop_file = cfg.workspace / ".stop"
    stop_file.write_text("stop\n", encoding="utf-8")
    log.info("Wrote stop sentinel to %s", stop_file)


# ---------------------------------------------------------------------------
# SMTP reply
# ---------------------------------------------------------------------------

async def send_reply(cfg: Config, to_addr: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = cfg.smtp_user
    msg["To"] = to_addr
    msg["Subject"] = f"Re: {subject}"
    msg.set_content(body)

    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_user,
            password=cfg.smtp_pass,
            use_tls=True,
        )
        log.info("Replied to %s", to_addr)
    except Exception as exc:
        log.error("Failed to send reply to %s: %s", to_addr, exc)


# ---------------------------------------------------------------------------
# IMAP polling
# ---------------------------------------------------------------------------

async def process_message(cfg: Config, raw: bytes) -> None:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    from_addr = str(msg.get("From", ""))
    subject = str(msg.get("Subject", ""))

    log.info("Processing message from=%r subject=%r", from_addr, subject)

    if cfg.allowed_senders:
        # Extract bare address from "Name <addr>" format
        m = re.search(r"<([^>]+)>", from_addr)
        bare = (m.group(1) if m else from_addr).lower().strip()
        if bare not in cfg.allowed_senders:
            log.warning("Rejected message from unauthorised sender %r", from_addr)
            return

    prefix, description, model_hint = parse_subject(subject)

    if prefix == "task":
        spec = extract_spec(msg)
        if not spec:
            reply_body = "Could not extract a spec from your email. Please include a markdown spec in the body or attach a .md file."
        else:
            reply_body = await dispatch_task(cfg, spec, description, model_hint=model_hint)
        await send_reply(cfg, from_addr, subject, reply_body)

    elif prefix == "stop":
        write_stop_sentinel(cfg)
        await send_reply(cfg, from_addr, subject, "Stop sentinel written. The loop will exit cleanly after its current iteration.")

    elif prefix == "status":
        status_body = get_status(cfg)
        await send_reply(cfg, from_addr, subject, status_body)

    else:
        log.debug("Ignoring message with unrecognized prefix %r", prefix)


async def poll_once(cfg: Config, imap: aioimaplib.IMAP4_SSL) -> None:
    """Search for UNSEEN messages and process each one."""
    # NOOP flushes pending untagged server responses (e.g. EXISTS updates from
    # newly arrived messages) so FETCH sequence numbers are always valid.
    await imap.noop()
    # SEARCH without CHARSET for broadest server compatibility.
    # UID SEARCH is not supported by all servers (e.g. Hostinger rejects it).
    status, data = await imap.search("UNSEEN", charset=None)
    if status != "OK":
        log.warning("IMAP SEARCH failed: %s %s", status, data)
        return

    seq_list_raw = data[0].decode() if isinstance(data[0], bytes) else str(data[0])
    seqs = [s for s in seq_list_raw.split() if s]
    if not seqs:
        return

    log.info("Found %d unseen message(s)", len(seqs))

    for seq in seqs:
        try:
            # BODY.PEEK[] is RFC 3501 and widely supported; RFC822 is legacy.
            fetch_status, fetch_data = await imap.fetch(seq, "(BODY.PEEK[])")
            log.debug("FETCH seq=%s status=%s data=%r", seq, fetch_status, fetch_data)
            if fetch_status != "OK":
                log.warning("FETCH failed for seq %s: %s", seq, fetch_status)
                continue

            # aioimaplib returns [metadata_line, message_bytes, b')']
            # The actual message body is the largest bytes item in the response.
            raw: bytes | None = None
            # aioimaplib returns the message literal as bytearray, not bytes.
            candidates = [bytes(item) for item in fetch_data
                          if isinstance(item, (bytes, bytearray)) and bytes(item) != b")"]
            log.debug("FETCH candidates lengths: %s", [len(c) for c in candidates])
            if candidates:
                raw = max(candidates, key=len)

            if not raw:
                log.warning("No body data for seq %s", seq)
                continue

            await process_message(cfg, raw)

            await imap.store(seq, "+FLAGS", r"(\Seen)")

        except Exception as exc:
            log.exception("Error processing seq %s: %s", seq, exc)


async def run_listener(cfg: Config) -> None:
    log.info("Connecting to IMAP %s:%d as %s", cfg.imap_host, cfg.imap_port, cfg.imap_user)

    while True:
        try:
            imap = aioimaplib.IMAP4_SSL(host=cfg.imap_host, port=cfg.imap_port)
            await imap.wait_hello_from_server()
            await imap.login(cfg.imap_user, cfg.imap_pass)
            await imap.select("INBOX")
            log.info("IMAP connected; polling every %ds", cfg.poll_interval)

            while True:
                await poll_once(cfg, imap)
                await asyncio.sleep(cfg.poll_interval)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("IMAP error: %s — reconnecting in 60s", exc)
            await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    try:
        cfg = Config.from_env()
    except RuntimeError as exc:
        log.error("Configuration error: %s", exc)
        sys.exit(1)

    log.info("agentx listener starting (workspace=%s)", cfg.workspace)

    try:
        asyncio.run(run_listener(cfg))
    except KeyboardInterrupt:
        log.info("Shutting down")


if __name__ == "__main__":
    main()
