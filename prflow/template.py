"""PR template discovery and section parsing."""

from __future__ import annotations

import re
from pathlib import Path

from prflow.types import TemplateSection


def discover_template(repo_root: Path) -> str | None:
    """Find and read the PR template, returning its content or None."""
    candidates = [
        repo_root / ".github" / "PULL_REQUEST_TEMPLATE.md",
        repo_root / ".github" / "pull_request_template.md",
        repo_root / "docs" / "pull_request_template.md",
        repo_root / "pull_request_template.md",
    ]

    for path in candidates:
        if path.is_file():
            return path.read_text()

    # Check template directory — pick first .md alphabetically
    template_dir = repo_root / ".github" / "PULL_REQUEST_TEMPLATE"
    if template_dir.is_dir():
        md_files = sorted(template_dir.glob("*.md"))
        if md_files:
            return md_files[0].read_text()

    return None


def parse_sections(template: str) -> list[TemplateSection]:
    """Split a PR template by ## headers into sections.

    Returns a list of dicts: [{"header": "Summary", "body": "..."}]
    Content before the first ## header is captured with header="".
    """
    sections: list[TemplateSection] = []
    current_header = ""
    current_body_lines: list[str] = []

    for line in template.splitlines():
        match = re.match(r"^## (.+)$", line)
        if match:
            # Save previous section
            body = "\n".join(current_body_lines).strip()
            if current_header or body:
                sections.append({"header": current_header, "body": body})
            current_header = match.group(1)
            current_body_lines = []
        else:
            current_body_lines.append(line)

    # Save last section
    body = "\n".join(current_body_lines).strip()
    if current_header or body:
        sections.append({"header": current_header, "body": body})

    return sections


def format_sections_for_prompt(sections: list[TemplateSection]) -> str:
    """Format parsed sections into a string for the LLM prompt."""
    lines = ["The PR template has these sections to fill:"]
    for section in sections:
        if not section["header"]:
            continue
        body_preview = section["body"][:100] if section["body"] else "(empty)"
        lines.append(f'- "{section["header"]}": {body_preview}')
    lines.append("")
    lines.append("Fill each section appropriately. Preserve section headers as ## headers in your output.")
    return "\n".join(lines)
