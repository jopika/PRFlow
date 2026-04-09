"""Jira integration with extensible backends."""

from __future__ import annotations

from abc import ABC, abstractmethod


class JiraBackend(ABC):
    """Abstract base for Jira backends."""

    @abstractmethod
    def get_ticket(self, key: str) -> dict:
        """Return ticket data dict. At minimum: {"url": ..., "key": ...}."""


class UrlOnlyBackend(JiraBackend):
    """Constructs a Jira URL from the ticket key — no API calls."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def get_ticket(self, key: str) -> dict:
        return {"url": f"{self.base_url}/{key}", "key": key}


class RestApiBackend(JiraBackend):
    """REST API backend — stub for future implementation."""

    def get_ticket(self, key: str) -> dict:
        raise NotImplementedError(
            "REST API backend not yet implemented. "
            "Configure jira.token and jira.email, then implement GET /rest/api/3/issue/{key}."
        )


class McpBackend(JiraBackend):
    """MCP backend — stub for use inside Claude Code with a Jira MCP server."""

    def get_ticket(self, key: str) -> dict:
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


def is_configured(config: dict) -> bool:
    """Return True if Jira is configured (base_url is set)."""
    return config.get("jira", {}).get("base_url") is not None


def get_backend(config: dict) -> JiraBackend:
    """Factory: return the appropriate Jira backend based on config."""
    jira_config = config.get("jira", {})
    backend_name = jira_config.get("backend", "url_only")

    if backend_name == "url_only":
        base_url = jira_config.get("base_url")
        if not base_url:
            raise ValueError("jira.base_url must be set for url_only backend")
        return UrlOnlyBackend(base_url)
    elif backend_name == "rest_api":
        return RestApiBackend()
    elif backend_name == "mcp":
        return McpBackend()
    else:
        raise ValueError(f"Unknown Jira backend: {backend_name}")


def format_for_pr(ticket_data: dict) -> str:
    """Format ticket data as a markdown snippet for PR body."""
    key = ticket_data.get("key", "")
    url = ticket_data.get("url", "")
    if url and key:
        return f"**Jira:** [{key}]({url})"
    elif url:
        return f"**Jira:** {url}"
    return ""
