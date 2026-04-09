"""Tests for jira.py — Jira integration."""

import pytest

from prflow.jira import (
    UrlOnlyBackend,
    format_for_pr,
    get_backend,
    is_configured,
    normalize_ticket_input,
)


class TestNormalizeTicketInput:
    def test_bare_key_returned_unchanged(self):
        assert normalize_ticket_input("AML-4419") == "AML-4419"

    def test_full_url_extracts_key(self):
        assert normalize_ticket_input("https://redfin.atlassian.net/browse/AML-4419") == "AML-4419"

    def test_full_url_with_trailing_slash(self):
        assert normalize_ticket_input("https://redfin.atlassian.net/browse/AML-4419/") == "AML-4419"

    def test_strips_whitespace(self):
        assert normalize_ticket_input("  PROJ-123  ") == "PROJ-123"

    def test_http_url(self):
        assert normalize_ticket_input("http://jira.internal/browse/FOO-1") == "FOO-1"


class TestIsConfigured:
    def test_configured(self):
        assert is_configured({"jira": {"base_url": "https://example.com"}}) is True

    def test_not_configured(self):
        assert is_configured({"jira": {"base_url": None}}) is False

    def test_missing_jira_key(self):
        assert is_configured({}) is False


class TestUrlOnlyBackend:
    def test_get_ticket(self):
        backend = UrlOnlyBackend("https://example.atlassian.net/browse")
        ticket = backend.get_ticket("PROJ-123")
        assert ticket == {
            "url": "https://example.atlassian.net/browse/PROJ-123",
            "key": "PROJ-123",
        }

    def test_trailing_slash_stripped(self):
        backend = UrlOnlyBackend("https://example.com/browse/")
        ticket = backend.get_ticket("X-1")
        assert ticket["url"] == "https://example.com/browse/X-1"


class TestGetBackend:
    def test_url_only(self):
        config = {"jira": {"backend": "url_only", "base_url": "https://example.com"}}
        backend = get_backend(config)
        assert isinstance(backend, UrlOnlyBackend)

    def test_url_only_missing_base_url(self):
        config = {"jira": {"backend": "url_only", "base_url": None}}
        with pytest.raises(ValueError, match="base_url must be set"):
            get_backend(config)

    def test_rest_api_stub(self):
        config = {"jira": {"backend": "rest_api"}}
        backend = get_backend(config)
        with pytest.raises(NotImplementedError):
            backend.get_ticket("X-1")

    def test_unknown_backend(self):
        config = {"jira": {"backend": "nope"}}
        with pytest.raises(ValueError, match="Unknown Jira backend"):
            get_backend(config)


class TestFormatForPr:
    def test_with_key_and_url(self):
        result = format_for_pr({"key": "PROJ-123", "url": "https://example.com/PROJ-123"})
        assert result == "**Jira:** [PROJ-123](https://example.com/PROJ-123)"

    def test_url_only(self):
        result = format_for_pr({"url": "https://example.com/X-1"})
        assert result == "**Jira:** https://example.com/X-1"

    def test_empty(self):
        assert format_for_pr({}) == ""
