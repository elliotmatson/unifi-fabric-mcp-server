"""Dry-run mode (``UNIFI_DRY_RUN``): show the write a tool would make without making it.

With dry-run on, :meth:`UniFiClient.request` raises :class:`DryRunIntercepted` instead of
sending any mutating request. A write tool therefore runs its validation, gates and reads
as usual, then stops at its first write. This middleware turns that signal into the tool's
result, so the caller sees exactly which request would have been sent.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult

from .client import DryRunIntercepted

DRY_RUN_NOTE = (
    "Dry run (UNIFI_DRY_RUN=true): this request was NOT sent and nothing was changed. "
    "Reads before it ran normally. A tool that makes several writes stops at the first one."
)


def _find_dry_run(exc: BaseException) -> DryRunIntercepted | None:
    """Return the DryRunIntercepted in ``exc``'s cause/context chain, if any."""
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        if isinstance(node, DryRunIntercepted):
            return node
        seen.add(id(node))
        node = node.__cause__ or node.__context__
    return None


def _shape_for_schema(payload: dict[str, Any], text: str, schema: dict[str, Any] | None) -> Any:
    """Fit the preview to the tool's declared output schema, so clients that validate
    structured output accept it. ``None`` means the tool declares no structured output."""
    if not schema:
        return None
    if schema.get("x-fastmcp-wrap-result"):
        result_type = (schema.get("properties", {}).get("result") or {}).get("type")
        if result_type == "string":
            return {"result": text}
        if result_type == "array":
            return {"result": [payload]}
        return {"result": payload}
    return payload


class _QuietDryRunErrors(logging.Filter):
    """Drop FastMCP's "Error calling tool" traceback for a dry-run interception.

    The interception is expected (``DryRunMiddleware`` turns it into the tool's result),
    so logging it as an error with a traceback would be misleading noise. Other errors
    are untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        return exc is None or _find_dry_run(exc) is None


logging.getLogger("fastmcp.server.server").addFilter(_QuietDryRunErrors())
_logger = logging.getLogger(__name__)


def dry_run_result(
    tool: str, preview: dict[str, Any], output_schema: dict[str, Any] | None = None
) -> ToolResult:
    """Build the tool result reported for an intercepted write.

    The text content always carries the full preview as JSON; the structured content is
    shaped to the tool's output schema (see :func:`_shape_for_schema`).
    """
    payload = {
        "dryRun": True,
        "sent": False,
        "tool": tool,
        "request": preview,
        "note": DRY_RUN_NOTE,
    }
    text = json.dumps(payload, ensure_ascii=False)
    return ToolResult(
        content=[mt.TextContent(type="text", text=text)],
        structured_content=_shape_for_schema(payload, text, output_schema),
    )


class DryRunMiddleware(Middleware):
    """Convert a dry-run interception raised during a tool call into a preview result.

    ``get_tool`` is the server's tool lookup, used to read the tool's output schema.
    """

    def __init__(self, get_tool: Callable[[str], Awaitable[Any]]) -> None:
        self._get_tool = get_tool

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            return await call_next(context)
        except Exception as exc:
            intercepted = _find_dry_run(exc)
            if intercepted is None:
                raise
            name = context.message.name
            preview = intercepted.preview
            _logger.info(
                "dry run: %s %s not sent (tool %s)", preview["method"], preview["path"], name
            )
            tool = await self._get_tool(name)
            schema = getattr(tool, "output_schema", None)
            return dry_run_result(name, intercepted.preview, schema)
