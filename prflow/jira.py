"""Jira integration with extensible backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import cast

from prflow.types import Config, TicketData


class JiraBackend(ABC):
    """Abstract base for Jira backends."""

    @abstractmethod
    def get_ticket(self, key: str) -> TicketData:
        """Return ticket data dict. At minimum: {"url": ..., "key": ...}."""


class UrlOnlyBackend(JiraBackend):
    """Constructs a Jira URL from the ticket key — no API calls."""

    def __init__(self, base_url: str):
        self.base_url: str = base_url.rstrip("/")

    def get_ticket(self, key: str) -> TicketData:
        return {"url": f"{self.base_url}/{key}", "key": key}


class RestApiBackend(JiraBackend):
    """REST API backend — stub for future implementation."""

    def get_ticket(self, key: str) -> TicketData:
        raise NotImplementedError(
            "REST API backend not yet implemented. "
            "Configure jira.token and jira.email, then implement GET /rest/api/3/issue/{key}."
        )


class McpBackend(JiraBackend):
    """MCP backend — stub for use inside Claude Code with a Jira MCP server."""

    def get_ticket(self, key: str) -> TicketData:
        raise NotImplementedError(
            "MCP backend not yet implemented. "
            "Intended for use when prflow runs inside Claude Code with a Jira MCP server. "
            "Set jira.mcp_tool_name in config."
        )


def normalize_ticket_input(raw: str) -> str:
    """Extract a ticket key from a full Jira URL, or return the input unchanged.

    Handles both full URLs (https://company.atlassian.net/browse/PROJ-123)
    and bare keys (PROJ-123).
    """
    raw = raw.strip()
    if raw.startswith(("http://", "https://")):
        return raw.rstrip("/").split("/")[-1]
    return raw


def is_configured(config: Config) -> bool:
    """Return True if Jira is configured (base_url is set)."""
    jira_config = config.get("jira", {})
    if not isinstance(jira_config, dict):
        return False
    return jira_config.get("base_url") is not None


def get_backend(config: Config) -> JiraBackend:
    """Factory: return the appropriate Jira backend based on config."""
    jira_config_raw = config.get("jira", {})
    jira_config = cast(dict[str, object], jira_config_raw) if isinstance(jira_config_raw, dict) else {}
    backend_name_raw = jira_config.get("backend", "url_only")
    backend_name = backend_name_raw if isinstance(backend_name_raw, str) else "url_only"

    if backend_name == "url_only":
        base_url_raw = jira_config.get("base_url")
        if not isinstance(base_url_raw, str) or not base_url_raw:
            raise ValueError("jira.base_url must be set for url_only backend")
        return UrlOnlyBackend(base_url_raw)
    elif backend_name == "rest_api":
        return RestApiBackend()
    elif backend_name == "mcp":
        return McpBackend()
    else:
        raise ValueError(f"Unknown Jira backend: {backend_name}")


def format_for_pr(ticket_data: TicketData) -> str:
    """Format ticket data as a markdown snippet for PR body."""
    key = ticket_data.get("key", "")
    url = ticket_data.get("url", "")
    if url and key:
        return f"**Jira:** [{key}]({url})"
    elif url:
        return f"**Jira:** {url}"
    return ""
