"""Tests for llm.py — LLM abstraction and JSON extraction."""

import json
import subprocess

import pytest

from prflow.llm import (
    ClaudeBackend,
    LLMError,
    generate_commit_message,
    generate_pr_update,
    chunk_file_diffs,
    extract_json,
    get_backend,
)
from prflow.prompts import COMMIT_MESSAGE_SYSTEM_PROMPT


class TestExtractJson:
    def test_clean_json(self):
        raw = '{"title": "Fix bug", "body": "Details"}'
        result = extract_json(raw)
        assert result == {"title": "Fix bug", "body": "Details"}

    def test_markdown_fences(self):
        raw = 'Here is the result:\n```json\n{"title": "Add feature", "body": "Body"}\n```\n'
        result = extract_json(raw)
        assert result["title"] == "Add feature"

    def test_with_commentary(self):
        raw = 'Sure! Here\'s the PR:\n\n{"title": "Refactor", "body": "Details"}\n\nLet me know!'
        result = extract_json(raw)
        assert result["title"] == "Refactor"

    def test_invalid_raises(self):
        with pytest.raises(LLMError, match="Could not extract JSON"):
            extract_json("This is not JSON at all")

    def test_empty_raises(self):
        with pytest.raises(LLMError):
            extract_json("")


class TestClaudeBackend:
    def test_stdin_piping(self, mocker):
        mock_run = mocker.patch(
            "prflow.llm.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout='{"title": "T", "body": "B"}'
            ),
        )
        backend = ClaudeBackend()
        result = backend.generate("system", "user prompt")

        call_kwargs = mock_run.call_args
        # Verify prompt goes via input=, not in the command args
        assert call_kwargs.kwargs["input"] == "user prompt"
        assert "user prompt" not in call_kwargs.args[0]

    def test_timeout_raises(self, mocker):
        mocker.patch("prflow.llm.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120))
        backend = ClaudeBackend(timeout=120)
        with pytest.raises(LLMError, match="timed out"):
            backend.generate("sys", "user")

    def test_model_flag(self, mocker):
        mock_run = mocker.patch(
            "prflow.llm.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="ok"),
        )
        backend = ClaudeBackend(model="opus")
        backend.generate("sys", "user")
        cmd = mock_run.call_args.args[0]
        assert "--model" in cmd
        assert "opus" in cmd

    def test_no_model_flag(self, mocker):
        mock_run = mocker.patch(
            "prflow.llm.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="ok"),
        )
        backend = ClaudeBackend(model=None)
        backend.generate("sys", "user")
        cmd = mock_run.call_args.args[0]
        assert "--model" not in cmd

    def test_effort_flag(self, mocker):
        mock_run = mocker.patch(
            "prflow.llm.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="ok"),
        )
        backend = ClaudeBackend(effort="high")
        backend.generate("sys", "user")
        cmd = mock_run.call_args.args[0]
        assert "--effort" in cmd
        assert "high" in cmd

    def test_effort_default_medium(self, mocker):
        mock_run = mocker.patch(
            "prflow.llm.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="ok"),
        )
        backend = ClaudeBackend()
        backend.generate("sys", "user")
        cmd = mock_run.call_args.args[0]
        assert "--effort" in cmd
        assert "medium" in cmd

    def test_nonzero_exit_raises(self, mocker):
        mocker.patch(
            "prflow.llm.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="bad"),
        )
        backend = ClaudeBackend()
        with pytest.raises(LLMError, match="failed"):
            backend.generate("sys", "user")


class TestGetBackend:
    def test_claude(self):
        config = {"llm": {"backend": "claude", "model": "opus", "timeout": 60}}
        backend = get_backend(config)
        assert isinstance(backend, ClaudeBackend)
        assert backend.model == "opus"
        assert backend.timeout == 60

    def test_openai_stub(self):
        config = {"llm": {"backend": "openai"}}
        backend = get_backend(config)
        with pytest.raises(NotImplementedError):
            backend.generate("s", "u")

    def test_custom_requires_command(self):
        config = {"llm": {"backend": "custom", "command": None}}
        with pytest.raises(ValueError, match="command must be set"):
            get_backend(config)

    def test_unknown(self):
        config = {"llm": {"backend": "nope"}}
        with pytest.raises(ValueError, match="Unknown LLM backend"):
            get_backend(config)


class TestChunkFileDiffs:
    def test_groups_by_directory(self):
        diffs = {
            "src/a.py": "diff a",
            "src/b.py": "diff b",
            "tests/test_a.py": "diff test_a",
        }
        chunks = chunk_file_diffs(diffs, group_size=2)
        assert len(chunks) == 2
        # First chunk should have the two src/ files
        assert len(chunks[0]) == 2
        assert len(chunks[1]) == 1

    def test_respects_size_limit(self):
        diffs = {f"file{i}.py": f"diff {i}" for i in range(25)}
        chunks = chunk_file_diffs(diffs, group_size=10)
        assert all(len(c) <= 10 for c in chunks)
        total = sum(len(c) for c in chunks)
        assert total == 25

    def test_single_file(self):
        diffs = {"only.py": "diff"}
        chunks = chunk_file_diffs(diffs, group_size=10)
        assert len(chunks) == 1
        assert chunks[0] == {"only.py": "diff"}

    def test_empty(self):
        assert chunk_file_diffs({}) == []


class TestGenerateCommitMessage:
    def test_returns_stripped_plain_text(self, mocker):
        mock_backend = mocker.MagicMock()
        mock_backend.generate.return_value = "  Add interactive commit flow  \n"
        mocker.patch("prflow.llm.get_backend", return_value=mock_backend)

        result = generate_commit_message({"llm": {}}, "diff text", ["file.py"])

        assert result == "Add interactive commit flow"

    def test_uses_commit_system_prompt(self, mocker):
        mock_backend = mocker.MagicMock()
        mock_backend.generate.return_value = "Add feature"
        mocker.patch("prflow.llm.get_backend", return_value=mock_backend)

        generate_commit_message({"llm": {}}, "diff", ["file.py"])

        system_prompt = mock_backend.generate.call_args[0][0]
        assert system_prompt == COMMIT_MESSAGE_SYSTEM_PROMPT

    def test_includes_diff_in_user_prompt(self, mocker):
        mock_backend = mocker.MagicMock()
        mock_backend.generate.return_value = "Add feature"
        mocker.patch("prflow.llm.get_backend", return_value=mock_backend)

        generate_commit_message({"llm": {}}, "the actual diff", ["file.py"])

        user_prompt = mock_backend.generate.call_args[0][1]
        assert "the actual diff" in user_prompt

    def test_includes_file_list_in_user_prompt(self, mocker):
        mock_backend = mocker.MagicMock()
        mock_backend.generate.return_value = "Add feature"
        mocker.patch("prflow.llm.get_backend", return_value=mock_backend)

        generate_commit_message({"llm": {}}, "diff", ["src/a.py", "src/b.py"])

        user_prompt = mock_backend.generate.call_args[0][1]
        assert "src/a.py" in user_prompt
        assert "src/b.py" in user_prompt

    def test_falls_back_to_placeholder_when_diff_empty(self, mocker):
        mock_backend = mocker.MagicMock()
        mock_backend.generate.return_value = "Add binary asset"
        mocker.patch("prflow.llm.get_backend", return_value=mock_backend)

        generate_commit_message({"llm": {}}, "", ["image.png"])

        user_prompt = mock_backend.generate.call_args[0][1]
        assert "binary or no diff available" in user_prompt

    def test_propagates_llm_error(self, mocker):
        mock_backend = mocker.MagicMock()
        mock_backend.generate.side_effect = LLMError("timed out")
        mocker.patch("prflow.llm.get_backend", return_value=mock_backend)

        with pytest.raises(LLMError, match="timed out"):
            generate_commit_message({"llm": {}}, "diff", ["file.py"])


class TestGeneratePrUpdate:
    def test_uses_update_prompts(self, mocker):
        """Verify generate_pr_update uses UPDATE prompts and passes existing body."""
        mock_backend = mocker.MagicMock()
        mock_backend.generate.return_value = '{"title": "Updated title", "body": "Updated body"}'
        mocker.patch("prflow.llm.get_backend", return_value=mock_backend)
        mocker.patch("prflow.llm.console")

        result = generate_pr_update(
            config={"llm": {"backend": "claude"}},
            existing_title="Old title",
            existing_body="## Overview\nOld content",
            commits=[("abc123", "Add feature")],
            diff_stat=" file.py | 5 +++++",
            jira_snippet="**Jira:** PROJ-1",
        )

        assert result == {"title": "Updated title", "body": "Updated body"}

        # Verify the UPDATE system prompt was used (not DEFAULT)
        call_args = mock_backend.generate.call_args
        system_prompt = call_args[0][0]
        user_prompt = call_args[0][1]
        assert "updating an existing PR" in system_prompt.lower() or "PRESERVE" in system_prompt
        assert "Old title" in user_prompt
        assert "Old content" in user_prompt
        assert "abc123" in user_prompt

    def test_no_jira_section_when_empty(self, mocker):
        mock_backend = mocker.MagicMock()
        mock_backend.generate.return_value = '{"title": "T", "body": "B"}'
        mocker.patch("prflow.llm.get_backend", return_value=mock_backend)
        mocker.patch("prflow.llm.console")

        generate_pr_update(
            config={"llm": {"backend": "claude"}},
            existing_title="T",
            existing_body="B",
            commits=[("abc", "msg")],
            diff_stat="stat",
        )

        user_prompt = mock_backend.generate.call_args[0][1]
        assert "Jira ticket" not in user_prompt

    def test_seed_included_when_provided(self, mocker):
        mock_backend = mocker.MagicMock()
        mock_backend.generate.return_value = '{"title": "T", "body": "B"}'
        mocker.patch("prflow.llm.get_backend", return_value=mock_backend)
        mocker.patch("prflow.llm.console")

        generate_pr_update(
            config={"llm": {"backend": "claude"}},
            existing_title="T",
            existing_body="B",
            commits=[("abc", "msg")],
            diff_stat="stat",
            seed_section="Focus on performance improvements",
        )

        user_prompt = mock_backend.generate.call_args[0][1]
        assert "Focus on performance improvements" in user_prompt
        assert "Additional context" in user_prompt

    def test_seed_absent_when_empty(self, mocker):
        mock_backend = mocker.MagicMock()
        mock_backend.generate.return_value = '{"title": "T", "body": "B"}'
        mocker.patch("prflow.llm.get_backend", return_value=mock_backend)
        mocker.patch("prflow.llm.console")

        generate_pr_update(
            config={"llm": {"backend": "claude"}},
            existing_title="T",
            existing_body="B",
            commits=[("abc", "msg")],
            diff_stat="stat",
        )

        user_prompt = mock_backend.generate.call_args[0][1]
        assert "Additional context" not in user_prompt
