"""Shared type aliases for prflow."""

from __future__ import annotations

from typing import TypeAlias

Config: TypeAlias = dict[str, object]
DirtyFiles: TypeAlias = dict[str, list[str]]
ExistingPR: TypeAlias = dict[str, object]
JsonObject: TypeAlias = dict[str, object]
State: TypeAlias = dict[str, object]
TemplateSection: TypeAlias = dict[str, str]
TicketData: TypeAlias = dict[str, str]
