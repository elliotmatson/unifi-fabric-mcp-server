"""Server-side tool selection: read-only mode and tool-family selectors.

* ``UNIFI_READ_ONLY=true`` exposes only read tools (``readOnlyHint=true`` in
  ``tools/_annotations.py``).
* ``UNIFI_TOOL_FAMILIES=network,protect`` exposes only the listed families.
* ``UNIFI_DISABLED_TOOL_FAMILIES=connector`` hides the listed families.

The settings combine: a tool is available when its family is enabled, not disabled, and
(in read-only mode) it is a read tool. Unavailable tools are left out of ``tools/list`` and
refused if called by name, so hiding is enforced rather than cosmetic. By default every tool
is available, as before. Unknown family names fail at startup (``validate_selection``) so a
typo cannot silently expose or hide everything.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

import mcp.types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult

from .config import Settings
from .tools._annotations import READ_ONLY, TOOL_CLASS
from .tools._families import FAMILY_TOOLS, TOOL_FAMILY


def parse_families(raw: str, setting: str) -> set[str]:
    """Parse a comma/space separated family list, rejecting unknown names."""
    names = {part.strip().lower() for part in re.split(r"[,\s]+", raw or "") if part.strip()}
    unknown = sorted(names - FAMILY_TOOLS.keys())
    if unknown:
        raise ValueError(
            f"{setting} has unknown tool families {unknown}; valid families are "
            f"{sorted(FAMILY_TOOLS)}"
        )
    return names


def validate_selection(settings: Settings) -> None:
    """Fail fast on invalid family names (called at server startup)."""
    parse_families(settings.tool_families, "UNIFI_TOOL_FAMILIES")
    parse_families(settings.disabled_tool_families, "UNIFI_DISABLED_TOOL_FAMILIES")


def unavailable_reason(name: str, settings: Settings) -> str | None:
    """Why tool ``name`` is unavailable under ``settings``, or None if it is available."""
    family = TOOL_FAMILY.get(name)
    enabled = parse_families(settings.tool_families, "UNIFI_TOOL_FAMILIES")
    disabled = parse_families(settings.disabled_tool_families, "UNIFI_DISABLED_TOOL_FAMILIES")
    if enabled and family not in enabled:
        return f"its family {family!r} is not in UNIFI_TOOL_FAMILIES"
    if family in disabled:
        return f"its family {family!r} is in UNIFI_DISABLED_TOOL_FAMILIES"
    if settings.read_only and TOOL_CLASS.get(name) is not READ_ONLY:
        return "the server runs in read-only mode (UNIFI_READ_ONLY=true)"
    return None


class ToolSelectionMiddleware(Middleware):
    """Hide unavailable tools from tools/list and refuse calls to them."""

    def __init__(self, get_settings: Callable[[], Settings]) -> None:
        self._get_settings = get_settings

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Any]],
    ) -> Sequence[Any]:
        tools = await call_next(context)
        settings = self._get_settings()
        return [t for t in tools if unavailable_reason(t.name, settings) is None]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        reason = unavailable_reason(name, self._get_settings())
        if reason is not None:
            raise ToolError(f"Tool {name!r} is not available on this server: {reason}.")
        return await call_next(context)
