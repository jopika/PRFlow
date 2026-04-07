"""Tests for template.py — PR template discovery and parsing."""

from pathlib import Path

from prflow.template import discover_template, format_sections_for_prompt, parse_sections


class TestDiscoverTemplate:
    def test_github_template(self, tmp_path):
        tmpl = tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md"
        tmpl.parent.mkdir(parents=True)
        tmpl.write_text("## Summary\n")
        assert discover_template(tmp_path) == "## Summary\n"

    def test_lowercase_variant(self, tmp_path):
        tmpl = tmp_path / ".github" / "pull_request_template.md"
        tmpl.parent.mkdir(parents=True)
        tmpl.write_text("## Changes\n")
        assert discover_template(tmp_path) == "## Changes\n"

    def test_root_template(self, tmp_path):
        tmpl = tmp_path / "pull_request_template.md"
        tmpl.write_text("## Root\n")
        assert discover_template(tmp_path) == "## Root\n"

    def test_directory_template(self, tmp_path):
        tmpl_dir = tmp_path / ".github" / "PULL_REQUEST_TEMPLATE"
        tmpl_dir.mkdir(parents=True)
        (tmpl_dir / "default.md").write_text("## Dir\n")
        assert discover_template(tmp_path) == "## Dir\n"

    def test_no_template(self, tmp_path):
        assert discover_template(tmp_path) is None

    def test_priority_order(self, tmp_path):
        """Upper-case .github template wins over root."""
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text("github")
        (tmp_path / "pull_request_template.md").write_text("root")
        assert discover_template(tmp_path) == "github"


class TestParseSections:
    def test_basic(self, sample_template):
        sections = parse_sections(sample_template)
        headers = [s["header"] for s in sections]
        assert headers == ["Summary", "Test Plan", "Jira"]

    def test_preamble(self):
        template = "Preamble text\n\n## Summary\nDetails\n"
        sections = parse_sections(template)
        assert sections[0]["header"] == ""
        assert sections[0]["body"] == "Preamble text"
        assert sections[1]["header"] == "Summary"

    def test_empty_body(self):
        template = "## Section A\n## Section B\nContent B\n"
        sections = parse_sections(template)
        assert sections[0]["header"] == "Section A"
        assert sections[0]["body"] == ""
        assert sections[1]["header"] == "Section B"
        assert sections[1]["body"] == "Content B"

    def test_single_section(self):
        template = "## Only\nSome content here\n"
        sections = parse_sections(template)
        assert len(sections) == 1
        assert sections[0]["header"] == "Only"


class TestFormatSectionsForPrompt:
    def test_format(self, sample_template):
        sections = parse_sections(sample_template)
        result = format_sections_for_prompt(sections)
        assert '"Summary"' in result
        assert '"Test Plan"' in result
        assert "Fill each section" in result

    def test_skips_preamble(self):
        sections = [{"header": "", "body": "preamble"}, {"header": "Summary", "body": "desc"}]
        result = format_sections_for_prompt(sections)
        assert "preamble" not in result
        assert '"Summary"' in result
