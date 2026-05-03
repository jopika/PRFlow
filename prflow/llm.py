"""LLM backend abstraction and PR content generation."""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import cast, override

from rich.console import Console

from prflow.prompts import (
    COMMIT_MESSAGE_SYSTEM_PROMPT,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_USER_PROMPT_TEMPLATE,
    ORCHESTRATOR_SYSTEM_PROMPT,
    ORCHESTRATOR_USER_PROMPT_TEMPLATE,
    SUBAGENT_SYSTEM_PROMPT,
    SUBAGENT_USER_PROMPT_TEMPLATE,
    UPDATE_SYSTEM_PROMPT,
    UPDATE_USER_PROMPT_TEMPLATE,
)
from prflow.types import Config, JsonObject

logger = logging.getLogger(__name__)
console = Console()


class LLMError(Exception):
    """Raised when LLM operations fail."""


class LLMBackend(ABC):
    """Abstract base for LLM backends."""

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Send prompts and return raw text response."""


class ClaudeBackend(LLMBackend):
    """Calls Claude CLI via subprocess with stdin piping."""

    def __init__(self, model: str | None = None, effort: str = "medium", timeout: int = 120):
        self.model: str | None = model
        self.effort: str = effort
        self.timeout: int = timeout

    @override
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        cmd = ["claude", "-p", "--append-system-prompt", system_prompt]
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.extend(["--effort", self.effort])

        try:
            result = subprocess.run(
                cmd,
                input=user_prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            raise LLMError(f"Claude CLI timed out after {self.timeout}s")

        if result.returncode != 0:
            raise LLMError(f"Claude CLI failed (exit {result.returncode}): {result.stderr.strip()}")

        return result.stdout


class OpenAIBackend(LLMBackend):
    """OpenAI backend — stub for future implementation."""

    @override
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError("OpenAI backend not yet implemented.")


class CustomBackend(LLMBackend):
    """Calls an arbitrary command from config."""

    def __init__(self, command: str, timeout: int = 120):
        self.command: str = command
        self.timeout: int = timeout

    @override
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        try:
            result = subprocess.run(
                shlex.split(self.command),
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            raise LLMError(f"Custom command timed out after {self.timeout}s")

        if result.returncode != 0:
            raise LLMError(f"Custom command failed: {result.stderr.strip()}")

        return result.stdout


def get_backend(config: Config) -> LLMBackend:
    """Factory: return the appropriate LLM backend."""
    llm_config_raw = config.get("llm", {})
    llm_config = cast(dict[str, object], llm_config_raw) if isinstance(llm_config_raw, dict) else {}
    backend_name_raw = llm_config.get("backend", "claude")
    backend_name = backend_name_raw if isinstance(backend_name_raw, str) else "claude"
    timeout_raw = llm_config.get("timeout", 120)
    timeout = timeout_raw if isinstance(timeout_raw, int) else 120

    if backend_name == "claude":
        model_raw = llm_config.get("model")
        effort_raw = llm_config.get("effort", "medium")
        return ClaudeBackend(
            model=model_raw if isinstance(model_raw, str) else None,
            effort=effort_raw if isinstance(effort_raw, str) else "medium",
            timeout=timeout,
        )
    elif backend_name == "openai" or backend_name == "codex":
        return OpenAIBackend()
    elif backend_name == "custom":
        command_raw = llm_config.get("command")
        if not isinstance(command_raw, str) or not command_raw:
            raise ValueError("llm.command must be set for custom backend")
        return CustomBackend(command=command_raw, timeout=timeout)
    else:
        raise ValueError(f"Unknown LLM backend: {backend_name}")


def extract_json(raw: str) -> JsonObject:
    """Extract a JSON object from LLM output, handling fences and commentary."""
    text = raw.strip()

    # 1. Try direct parse
    try:
        parsed: object = json.loads(text)
        if isinstance(parsed, dict):
            return cast(JsonObject, parsed)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
            if isinstance(parsed, dict):
                return cast(JsonObject, parsed)
        except json.JSONDecodeError:
            pass

    # 3. Find first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            parsed = json.loads(text[first_brace : last_brace + 1])
            if isinstance(parsed, dict):
                return cast(JsonObject, parsed)
        except json.JSONDecodeError:
            pass

    raise LLMError(f"Could not extract JSON from LLM output:\n{text[:500]}")


def _format_commits(commits: list[tuple[str, str]]) -> str:
    return "\n".join(f"{h} {m}" for h, m in commits)


def _prompt_section(header: str, content: str, fallback: str = "") -> str:
    """Return a formatted ## section, or fallback if content is empty."""
    return f"\n## {header}\n{content}\n" if content else fallback


def chunk_file_diffs(file_diffs: dict[str, str], group_size: int = 10) -> list[dict[str, str]]:
    """Split file diffs into chunks, grouping by top-level directory."""
    # Group files by top-level dir
    groups: dict[str, list[str]] = {}
    for filepath in file_diffs:
        top_dir = filepath.split("/")[0] if "/" in filepath else ""
        groups.setdefault(top_dir, []).append(filepath)

    chunks: list[dict[str, str]] = []
    current_chunk: dict[str, str] = {}

    for _dir, files in groups.items():
        for filepath in files:
            if len(current_chunk) >= group_size:
                chunks.append(current_chunk)
                current_chunk = {}
            current_chunk[filepath] = file_diffs[filepath]

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def generate_pr_content(
    config: Config,
    commits: list[tuple[str, str]],
    diff_stat: str,
    jira_snippet: str = "",
    template_section: str = "",
    seed_section: str = "",
) -> JsonObject:
    """Generate PR title and body using default (stat-only) mode."""
    backend = get_backend(config)

    user_prompt = DEFAULT_USER_PROMPT_TEMPLATE.format(
        commits=_format_commits(commits),
        diff_stat=diff_stat,
        seed_section=_prompt_section("Additional context", seed_section),
        jira_section=_prompt_section("Jira ticket", jira_snippet, fallback="\n"),
        template_section=_prompt_section("PR Template", template_section, fallback="\n"),
    )

    with console.status("[bold blue]Generating PR content..."):
        raw = backend.generate(DEFAULT_SYSTEM_PROMPT, user_prompt)

    return extract_json(raw)


def generate_pr_content_full_diff(
    config: Config,
    commits: list[tuple[str, str]],
    file_diffs: dict[str, str],
    jira_snippet: str = "",
    template_section: str = "",
    seed_section: str = "",
) -> JsonObject:
    """Generate PR content using full-diff multi-agent pipeline."""
    llm_config_raw = config.get("llm", {})
    llm_config = cast(dict[str, object], llm_config_raw) if isinstance(llm_config_raw, dict) else {}
    group_size_raw = llm_config.get("full_diff_group_size", 10)
    group_size = group_size_raw if isinstance(group_size_raw, int) else 10
    backend = get_backend(config)

    chunks = chunk_file_diffs(file_diffs, group_size)
    summaries = [""] * len(chunks)

    def analyze_chunk(index: int, chunk: dict[str, str]) -> tuple[int, str]:
        diff_text = "\n".join(f"### {fp}\n{diff}" for fp, diff in chunk.items())
        user_prompt = SUBAGENT_USER_PROMPT_TEMPLATE.format(diff_chunk=diff_text)
        return index, backend.generate(SUBAGENT_SYSTEM_PROMPT, user_prompt)

    # Parallel sub-agent calls
    with console.status("[bold blue]Analyzing diff chunks...") as status:
        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as executor:
            futures = {
                executor.submit(analyze_chunk, i, chunk): i
                for i, chunk in enumerate(chunks)
            }
            completed = 0
            for future in as_completed(futures):
                completed += 1
                status.update(f"[bold blue]Analyzing diff chunks ({completed}/{len(chunks)})...")
                try:
                    idx, summary = future.result()
                    summaries[idx] = summary
                except LLMError as e:
                    logger.warning(f"Sub-agent chunk {futures[future]} failed: {e}")
                    summaries[futures[future]] = "(analysis unavailable)"

    # Orchestrator synthesis
    chunk_summaries = "\n\n---\n\n".join(
        f"### Chunk {i + 1}\n{s}" for i, s in enumerate(summaries) if s
    )
    user_prompt = ORCHESTRATOR_USER_PROMPT_TEMPLATE.format(
        commits=_format_commits(commits),
        chunk_summaries=chunk_summaries,
        seed_section=_prompt_section("Additional context", seed_section),
        jira_section=_prompt_section("Jira ticket", jira_snippet, fallback="\n"),
        template_section=_prompt_section("PR Template", template_section, fallback="\n"),
    )

    with console.status("[bold blue]Synthesizing PR content..."):
        raw = backend.generate(ORCHESTRATOR_SYSTEM_PROMPT, user_prompt)

    return extract_json(raw)


def generate_commit_message(config: Config, diff: str, file_list: list[str]) -> str:
    """Generate a single-line commit message from staged diff.

    Returns a plain string (no JSON parsing). Raises LLMError on failure.
    """
    backend = get_backend(config)
    user_content = "## Files changed\n" + "\n".join(file_list)
    user_content += "\n\n## Diff\n" + (diff if diff else "(binary or no diff available)")
    raw = backend.generate(COMMIT_MESSAGE_SYSTEM_PROMPT, user_content)
    return raw.strip()


def generate_pr_update(
    config: Config,
    existing_title: str,
    existing_body: str,
    commits: list[tuple[str, str]],
    diff_stat: str,
    jira_snippet: str = "",
    seed_section: str = "",
) -> JsonObject:
    """Generate updated PR content based on existing body + all commits."""
    backend = get_backend(config)

    user_prompt = UPDATE_USER_PROMPT_TEMPLATE.format(
        existing_title=existing_title,
        existing_body=existing_body,
        commits=_format_commits(commits),
        diff_stat=diff_stat,
        seed_section=_prompt_section("Additional context", seed_section),
        jira_section=_prompt_section("Jira ticket", jira_snippet, fallback="\n"),
    )

    with console.status("[bold blue]Updating PR content based on existing body..."):
        raw = backend.generate(UPDATE_SYSTEM_PROMPT, user_prompt)

    return extract_json(raw)
