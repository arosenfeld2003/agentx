"""Tests for src/listener.py — parsing and dispatch logic."""

from __future__ import annotations

import email
import email.policy
import textwrap
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from listener import (
    Config,
    _parse_frontmatter,
    _resolve_model,
    _strip_quoted_reply,
    dispatch_task,
    extract_spec,
    get_status,
    parse_subject,
    process_message,
    write_stop_sentinel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(tmp_path: Path) -> Config:
    ralph_sh = tmp_path / "ralph.sh"
    ralph_sh.write_text("#!/bin/bash\necho done\n")
    ralph_sh.chmod(0o755)

    return Config(
        imap_host="imap.example.com",
        imap_port=993,
        imap_user="agent@example.com",
        imap_pass="secret",
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_user="agent@example.com",
        smtp_pass="secret",
        workspace=tmp_path,
        ralph_sh=ralph_sh,
        poll_interval=5,
        projects_root=tmp_path / "projects",
    )


def make_config_with_projects(tmp_path: Path, projects_root: Path) -> Config:
    ralph_sh = tmp_path / "ralph.sh"
    ralph_sh.write_text("#!/bin/bash\necho done\n")
    ralph_sh.chmod(0o755)

    return Config(
        imap_host="imap.example.com",
        imap_port=993,
        imap_user="agent@example.com",
        imap_pass="secret",
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_user="agent@example.com",
        smtp_pass="secret",
        workspace=tmp_path,
        ralph_sh=ralph_sh,
        poll_interval=5,
        projects_root=projects_root,
    )


def make_email(
    subject: str,
    body: str,
    from_addr: str = "user@example.com",
    md_attachment: str | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "agent@example.com"
    msg["Subject"] = subject
    msg.set_content(body)
    if md_attachment is not None:
        msg.add_attachment(
            md_attachment.encode(),
            maintype="text",
            subtype="markdown",
            filename="spec.md",
        )
    return msg.as_bytes()


# ---------------------------------------------------------------------------
# parse_subject
# ---------------------------------------------------------------------------

class TestParseSubject:
    def test_task_with_description(self) -> None:
        prefix, desc, hint = parse_subject("[task] deploy the harness")
        assert prefix == "task"
        assert desc == "deploy the harness"
        assert hint is None

    def test_stop(self) -> None:
        prefix, desc, hint = parse_subject("[stop]")
        assert prefix == "stop"
        assert desc == ""
        assert hint is None

    def test_status(self) -> None:
        prefix, desc, hint = parse_subject("[status]")
        assert prefix == "status"
        assert desc == ""
        assert hint is None

    def test_case_insensitive(self) -> None:
        prefix, _, _ = parse_subject("[TASK] something")
        assert prefix == "task"

    def test_unrecognized(self) -> None:
        prefix, raw, hint = parse_subject("Hello world")
        assert prefix == ""
        assert raw == "Hello world"
        assert hint is None

    def test_task_no_description(self) -> None:
        prefix, desc, hint = parse_subject("[task]")
        assert prefix == "task"
        assert desc == ""
        assert hint is None

    def test_task_local_hint(self) -> None:
        prefix, desc, hint = parse_subject("[task:local] fix typo")
        assert prefix == "task"
        assert desc == "fix typo"
        assert hint == "local"

    def test_task_local_explicit_model(self) -> None:
        prefix, desc, hint = parse_subject("[task:local:qwen3:14b] refactor")
        assert prefix == "task"
        assert desc == "refactor"
        assert hint == "local:qwen3:14b"

    def test_task_api_hint(self) -> None:
        prefix, desc, hint = parse_subject("[task:api] design architecture")
        assert prefix == "task"
        assert desc == "design architecture"
        assert hint == "api"

    def test_task_api_explicit_model(self) -> None:
        prefix, desc, hint = parse_subject("[task:api:claude-opus-4-8] security review")
        assert prefix == "task"
        assert desc == "security review"
        assert hint == "api:claude-opus-4-8"


# ---------------------------------------------------------------------------
# _resolve_model
# ---------------------------------------------------------------------------

class TestResolveModel:
    def _cfg(self, **kwargs) -> Config:
        from pathlib import Path
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        base = dict(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp, ralph_sh=tmp / "ralph.sh",
        )
        return Config(**{**base, **kwargs})

    def test_no_hint_no_default(self) -> None:
        cfg = self._cfg()
        model, bypass = _resolve_model(None, cfg)
        assert model is None
        assert bypass is False

    def test_no_hint_with_default(self) -> None:
        cfg = self._cfg(ralph_default_model="claude-haiku-4-5-20251001")
        model, bypass = _resolve_model(None, cfg)
        assert model == "claude-haiku-4-5-20251001"
        assert bypass is False

    def test_local_hint_default_model(self) -> None:
        cfg = self._cfg()
        model, bypass = _resolve_model("local", cfg)
        assert model == "ollama/qwen3:8b"
        assert bypass is False

    def test_local_hint_custom_model(self) -> None:
        cfg = self._cfg(ralph_local_model="qwen3:14b")
        model, bypass = _resolve_model("local", cfg)
        assert model == "qwen3:14b"
        assert bypass is False

    def test_local_explicit_model(self) -> None:
        cfg = self._cfg()
        model, bypass = _resolve_model("local:qwen3:32b", cfg)
        assert model == "qwen3:32b"
        assert bypass is False

    def test_api_hint_default_model(self) -> None:
        cfg = self._cfg()
        model, bypass = _resolve_model("api", cfg)
        assert model == "claude-sonnet-4-6"
        assert bypass is True

    def test_api_hint_custom_model(self) -> None:
        cfg = self._cfg(ralph_api_model="claude-opus-4-8")
        model, bypass = _resolve_model("api", cfg)
        assert model == "claude-opus-4-8"
        assert bypass is True

    def test_api_explicit_model(self) -> None:
        cfg = self._cfg()
        model, bypass = _resolve_model("api:claude-opus-4-8", cfg)
        assert model == "claude-opus-4-8"
        assert bypass is True


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_no_frontmatter_returns_empty_fields(self) -> None:
        spec = "# Task\n\nDo the thing."
        fields, body = _parse_frontmatter(spec)
        assert fields == {}
        assert body == spec

    def test_parses_project_field(self) -> None:
        spec = "---\nproject: my-service\n---\n\n# Task\n\nDo the thing."
        fields, body = _parse_frontmatter(spec)
        assert fields == {"project": "my-service"}
        assert body == "# Task\n\nDo the thing."

    def test_parses_multiple_fields(self) -> None:
        spec = "---\nproject: api\nenv: staging\n---\n# Spec"
        fields, body = _parse_frontmatter(spec)
        assert fields["project"] == "api"
        assert fields["env"] == "staging"
        assert body == "# Spec"

    def test_strips_frontmatter_whitespace(self) -> None:
        spec = "---\n  project:  my-svc  \n---\n# Body"
        fields, body = _parse_frontmatter(spec)
        assert fields["project"] == "my-svc"

    def test_empty_frontmatter_returns_empty_fields(self) -> None:
        spec = "---\n\n---\n# Body"
        fields, body = _parse_frontmatter(spec)
        assert fields == {}
        assert body == "# Body"


# ---------------------------------------------------------------------------
# _strip_quoted_reply
# ---------------------------------------------------------------------------

class TestStripQuotedReply:
    def test_strips_gt_lines(self) -> None:
        text = "My spec.\n\n> On Mon wrote:\n> prior content"
        result = _strip_quoted_reply(text)
        assert "My spec" in result
        assert "prior content" not in result

    def test_strips_on_wrote_separator(self) -> None:
        text = "Do the thing.\n\nOn Mon, Jun 17, 2026 at 10:00 AM Alex <a@b.com> wrote:\n> Old content"
        result = _strip_quoted_reply(text)
        assert "Do the thing" in result
        assert "Old content" not in result
        assert "wrote" not in result

    def test_plain_text_unchanged(self) -> None:
        text = "# Spec\n\nImplement feature X."
        assert _strip_quoted_reply(text) == text


# ---------------------------------------------------------------------------
# extract_spec
# ---------------------------------------------------------------------------

class TestExtractSpec:
    def test_plain_body(self) -> None:
        raw = make_email("[task] test", "# My Spec\n\nDo the thing.")
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        spec = extract_spec(msg)
        assert "My Spec" in spec
        assert "Do the thing" in spec

    def test_md_attachment_preferred_over_body(self) -> None:
        raw = make_email(
            "[task] test",
            "Ignore this body.",
            md_attachment="# Attachment Spec\n\nUse this.",
        )
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        spec = extract_spec(msg)
        assert "Attachment Spec" in spec
        assert "Ignore this body" not in spec

    def test_empty_email(self) -> None:
        msg = EmailMessage()
        msg["From"] = "x@example.com"
        msg["Subject"] = "[task] empty"
        spec = extract_spec(msg)
        assert spec == ""

    def test_multipart_extracts_plain(self) -> None:
        raw = make_email("[task] multi", "Plain text spec here.")
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        spec = extract_spec(msg)
        assert "Plain text spec here" in spec


# ---------------------------------------------------------------------------
# write_stop_sentinel
# ---------------------------------------------------------------------------

class TestWriteStopSentinel:
    def test_creates_file(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        write_stop_sentinel(cfg)
        stop_file = tmp_path / ".stop"
        assert stop_file.exists()
        assert "stop" in stop_file.read_text()


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

class TestGetStatus:
    def test_no_stop_sentinel(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        status = get_status(cfg)
        assert "No stop sentinel" in status

    def test_with_stop_sentinel(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        (tmp_path / ".stop").write_text("stop\n")
        status = get_status(cfg)
        assert "Stop sentinel is present" in status

    def test_includes_git_section(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        status = get_status(cfg)
        assert "Recent commits" in status or "Could not read git log" in status


# ---------------------------------------------------------------------------
# dispatch_task
# ---------------------------------------------------------------------------

class TestDispatchTask:
    @pytest.mark.asyncio
    async def test_writes_task_file_and_runs_ralph(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        spec = "# Deploy\n\nRun the thing."
        summary = await dispatch_task(cfg, spec, "deploy the thing")

        inbox_dirs = list((tmp_path / "projects" / ".inbox").iterdir())
        assert len(inbox_dirs) == 1
        task_file = inbox_dirs[0] / "TASK.md"
        assert task_file.exists()
        assert "Deploy" in task_file.read_text()
        assert "deploy the thing" in summary
        assert "Ralph loop" in summary

    @pytest.mark.asyncio
    async def test_non_zero_exit_noted_in_summary(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text("#!/bin/bash\nexit 1\n")
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x",
            imap_port=993,
            imap_user="u",
            imap_pass="p",
            smtp_host="x",
            smtp_port=465,
            smtp_user="u",
            smtp_pass="p",
            workspace=tmp_path,
            ralph_sh=ralph_sh,
            projects_root=tmp_path / "projects",
        )
        summary = await dispatch_task(cfg, "spec", "desc")
        assert "exited with code 1" in summary

    @pytest.mark.asyncio
    async def test_does_not_modify_implementation_plan(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        plan = tmp_path / "IMPLEMENTATION_PLAN.md"
        original = "# Implementation Plan\n\n## Current Focus\n\nexisting task\n"
        plan.write_text(original)
        await dispatch_task(cfg, "# Spec\n\nDo it.", "email task desc")
        assert plan.read_text() == original

    @pytest.mark.asyncio
    async def test_invokes_ralph_in_task_mode(self, tmp_path: Path) -> None:
        captured_args: list = []
        original_exec = __import__("asyncio").create_subprocess_exec

        async def capturing_exec(*args, **kwargs):
            captured_args.extend(args)
            return await original_exec(*args, **kwargs)

        cfg = make_config(tmp_path)
        with patch("asyncio.create_subprocess_exec", side_effect=capturing_exec):
            await dispatch_task(cfg, "# Spec\n\nDo it.", "desc")

        assert "task" in captured_args
        assert any("TASK.md" in arg for arg in captured_args)

    @pytest.mark.asyncio
    async def test_sets_ralph_max_iterations_env(self, tmp_path: Path) -> None:
        captured_env: dict = {}
        original_exec = __import__("asyncio").create_subprocess_exec

        async def capturing_exec(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return await original_exec(*args, **kwargs)

        cfg = make_config(tmp_path)
        with patch("asyncio.create_subprocess_exec", side_effect=capturing_exec):
            await dispatch_task(cfg, "spec", "desc")

        assert captured_env.get("RALPH_MAX_ITERATIONS") == str(cfg.ralph_iterations)

    @pytest.mark.asyncio
    async def test_timeout_kills_process_and_returns_message(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text("#!/bin/bash\nsleep 999\n")
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp_path, ralph_sh=ralph_sh, ralph_timeout=1,
            projects_root=tmp_path / "projects",
        )
        summary = await dispatch_task(cfg, "spec", "slow task")
        assert "timed out" in summary

    @pytest.mark.asyncio
    async def test_local_hint_sets_ralph_model_env(self, tmp_path: Path) -> None:
        captured_env: dict = {}
        original_exec = __import__("asyncio").create_subprocess_exec

        async def capturing_exec(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return await original_exec(*args, **kwargs)

        cfg = make_config(tmp_path)
        with patch("asyncio.create_subprocess_exec", side_effect=capturing_exec):
            await dispatch_task(cfg, "spec", "desc", model_hint="local")

        assert captured_env.get("RALPH_MODEL") == "ollama/qwen3:8b"

    @pytest.mark.asyncio
    async def test_api_hint_sets_model_and_removes_base_url(self, tmp_path: Path) -> None:
        captured_env: dict = {}
        original_exec = __import__("asyncio").create_subprocess_exec

        async def capturing_exec(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return await original_exec(*args, **kwargs)

        import os
        env_with_base_url = {**os.environ, "ANTHROPIC_BASE_URL": "http://localhost:4000"}
        cfg = make_config(tmp_path)
        with (
            patch("asyncio.create_subprocess_exec", side_effect=capturing_exec),
            patch.dict("os.environ", {"ANTHROPIC_BASE_URL": "http://localhost:4000"}),
        ):
            await dispatch_task(cfg, "spec", "desc", model_hint="api")

        assert captured_env.get("RALPH_MODEL") == "claude-sonnet-4-6"
        assert "ANTHROPIC_BASE_URL" not in captured_env

    @pytest.mark.asyncio
    async def test_reply_includes_model_name(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        summary = await dispatch_task(cfg, "# Spec\n\nDo it.", "desc", model_hint="local")
        assert "Model:" in summary
        assert "ollama/qwen3:8b" in summary

    @pytest.mark.asyncio
    async def test_no_frontmatter_uses_inbox_workspace(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "projects"
        cfg = make_config_with_projects(tmp_path, projects_root)
        await dispatch_task(cfg, "# Spec\n\nDo it.", "desc")
        inbox_dirs = list((projects_root / ".inbox").iterdir())
        assert len(inbox_dirs) == 1
        assert (inbox_dirs[0] / "TASK.md").exists()

    @pytest.mark.asyncio
    async def test_named_project_uses_projects_root(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "projects"
        cfg = make_config_with_projects(tmp_path, projects_root)
        spec = "---\nproject: my-api\n---\n\n# Task\n\nDo it."
        await dispatch_task(cfg, spec, "desc")
        assert (projects_root / "my-api" / "TASK.md").exists()

    @pytest.mark.asyncio
    async def test_task_body_stripped_of_frontmatter(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "projects"
        cfg = make_config_with_projects(tmp_path, projects_root)
        spec = "---\nproject: my-api\n---\n\n# Task\n\nDo it."
        await dispatch_task(cfg, spec, "desc")
        task_md = (projects_root / "my-api" / "TASK.md").read_text()
        assert "---" not in task_md
        assert "project:" not in task_md
        assert "# Task" in task_md

    @pytest.mark.asyncio
    async def test_agentx_project_uses_cfg_workspace(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "projects"
        cfg = make_config_with_projects(tmp_path, projects_root)
        spec = "---\nproject: agentx\n---\n\n# Task\n\nDo it."
        await dispatch_task(cfg, spec, "desc")
        assert (tmp_path / "TASK.md").exists()
        assert not projects_root.exists()

    @pytest.mark.asyncio
    async def test_ephemeral_project_uses_inbox(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "projects"
        cfg = make_config_with_projects(tmp_path, projects_root)
        spec = "---\nproject: _ephemeral\n---\n\n# Task\n\nDo it."
        await dispatch_task(cfg, spec, "desc")
        inbox_dirs = list((projects_root / ".inbox").iterdir())
        assert len(inbox_dirs) == 1


# ---------------------------------------------------------------------------
# process_message (integration-style with mocks)
# ---------------------------------------------------------------------------

class TestProcessMessage:
    @pytest.mark.asyncio
    async def test_task_prefix_triggers_dispatch_and_reply(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("[task] build listener", "# Spec\n\nDo it.", "user@example.com")

        with (
            patch("listener.dispatch_task", new_callable=AsyncMock, return_value="Work done.") as mock_dispatch,
            patch("listener.send_reply", new_callable=AsyncMock) as mock_reply,
        ):
            await process_message(cfg, raw)

        mock_dispatch.assert_awaited_once()
        mock_reply.assert_awaited_once()
        _, reply_to, _, body = mock_reply.call_args[0]
        assert "Work done" in body

    @pytest.mark.asyncio
    async def test_stop_prefix_writes_sentinel_and_replies(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("[stop]", "halt please", "user@example.com")

        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await process_message(cfg, raw)

        assert (tmp_path / ".stop").exists()
        mock_reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_status_prefix_sends_status_reply(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("[status]", "", "user@example.com")

        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await process_message(cfg, raw)

        mock_reply.assert_awaited_once()
        _, _, _, body = mock_reply.call_args[0]
        assert "agentx status" in body

    @pytest.mark.asyncio
    async def test_unrecognized_prefix_ignored(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("Hello there", "random email", "user@example.com")

        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await process_message(cfg, raw)

        mock_reply.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allowed_sender_passes(self, tmp_path: Path) -> None:
        cfg = Config(
            **{**make_config(tmp_path).__dict__,
               "allowed_senders": frozenset(["user@example.com"])},
        )
        raw = make_email("[status]", "", "user@example.com")
        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await process_message(cfg, raw)
        mock_reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unauthorised_sender_rejected(self, tmp_path: Path) -> None:
        cfg = Config(
            **{**make_config(tmp_path).__dict__,
               "allowed_senders": frozenset(["allowed@example.com"])},
        )
        raw = make_email("[task] do something", "spec", "evil@example.com")
        with patch("listener.dispatch_task", new_callable=AsyncMock) as mock_dispatch:
            await process_message(cfg, raw)
        mock_dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_name_bracket_addr_format_parsed(self, tmp_path: Path) -> None:
        cfg = Config(
            **{**make_config(tmp_path).__dict__,
               "allowed_senders": frozenset(["user@example.com"])},
        )
        raw = make_email("[status]", "", "User Name <user@example.com>")
        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await process_message(cfg, raw)
        mock_reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_task_local_passes_hint_to_dispatch(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("[task:local] fix a bug", "# Spec\n\nFix it.", "user@example.com")

        with (
            patch("listener.dispatch_task", new_callable=AsyncMock, return_value="done") as mock_dispatch,
            patch("listener.send_reply", new_callable=AsyncMock),
        ):
            await process_message(cfg, raw)

        _, kwargs = mock_dispatch.call_args
        assert kwargs.get("model_hint") == "local"

    @pytest.mark.asyncio
    async def test_task_api_passes_hint_to_dispatch(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("[task:api] design system", "# Spec\n\nArchitect it.", "user@example.com")

        with (
            patch("listener.dispatch_task", new_callable=AsyncMock, return_value="done") as mock_dispatch,
            patch("listener.send_reply", new_callable=AsyncMock),
        ):
            await process_message(cfg, raw)

        _, kwargs = mock_dispatch.call_args
        assert kwargs.get("model_hint") == "api"

    @pytest.mark.asyncio
    async def test_task_no_hint_passes_none(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("[task] plain task", "# Spec\n\nDo it.", "user@example.com")

        with (
            patch("listener.dispatch_task", new_callable=AsyncMock, return_value="done") as mock_dispatch,
            patch("listener.send_reply", new_callable=AsyncMock),
        ):
            await process_message(cfg, raw)

        _, kwargs = mock_dispatch.call_args
        assert kwargs.get("model_hint") is None

    @pytest.mark.asyncio
    async def test_task_with_empty_spec_sends_error_reply(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        msg = EmailMessage()
        msg["From"] = "user@example.com"
        msg["Subject"] = "[task] oops"
        raw = msg.as_bytes()

        with (
            patch("listener.dispatch_task", new_callable=AsyncMock) as mock_dispatch,
            patch("listener.send_reply", new_callable=AsyncMock) as mock_reply,
        ):
            await process_message(cfg, raw)

        mock_dispatch.assert_not_awaited()
        mock_reply.assert_awaited_once()
        _, _, _, body = mock_reply.call_args[0]
        assert "Could not extract" in body


# ---------------------------------------------------------------------------
# Config.from_env
# ---------------------------------------------------------------------------

class TestConfigFromEnv:
    def test_requires_imap_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IMAP_USER", raising=False)
        monkeypatch.delenv("IMAP_PASS", raising=False)
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_PASS", raising=False)
        with pytest.raises(RuntimeError, match="IMAP_USER"):
            Config.from_env()

    def test_loads_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IMAP_USER", "u@example.com")
        monkeypatch.setenv("IMAP_PASS", "pass1")
        monkeypatch.setenv("SMTP_USER", "u@example.com")
        monkeypatch.setenv("SMTP_PASS", "pass2")
        monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
        cfg = Config.from_env()
        assert cfg.imap_user == "u@example.com"
        assert cfg.workspace == tmp_path

    def test_allowed_senders_parsed_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IMAP_USER", "u@example.com")
        monkeypatch.setenv("IMAP_PASS", "pass1")
        monkeypatch.setenv("SMTP_USER", "u@example.com")
        monkeypatch.setenv("SMTP_PASS", "pass2")
        monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
        monkeypatch.setenv("AGENTX_ALLOWED_SENDERS", "a@example.com, B@EXAMPLE.COM")
        cfg = Config.from_env()
        assert cfg.allowed_senders == frozenset(["a@example.com", "b@example.com", "u@example.com"])

    def test_projects_root_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IMAP_USER", "u@example.com")
        monkeypatch.setenv("IMAP_PASS", "pass1")
        monkeypatch.setenv("SMTP_USER", "u@example.com")
        monkeypatch.setenv("SMTP_PASS", "pass2")
        monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
        monkeypatch.setenv("AGENTX_PROJECTS_ROOT", "/custom/projects")
        cfg = Config.from_env()
        assert cfg.projects_root == Path("/custom/projects")

    def test_projects_root_default(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IMAP_USER", "u@example.com")
        monkeypatch.setenv("IMAP_PASS", "pass1")
        monkeypatch.setenv("SMTP_USER", "u@example.com")
        monkeypatch.setenv("SMTP_PASS", "pass2")
        monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
        monkeypatch.delenv("AGENTX_PROJECTS_ROOT", raising=False)
        cfg = Config.from_env()
        assert cfg.projects_root == Path("/opt/projects")
