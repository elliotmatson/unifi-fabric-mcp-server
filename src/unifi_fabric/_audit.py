"""Write audit log: one structured log line per write-tool call (``UNIFI_AUDIT_WRITES``).

Every call to a tool that is not marked ``readOnlyHint=true`` produces one INFO line on the
``unifi_fabric.audit`` logger, after the call finishes::

    tool-write-audit {"tool": "delete_network", "outcome": "ok", "durationMs": 412,
                      "host": "MyConsole", "site": "Default", "args": {...}}

``outcome`` is ``ok``, ``error`` (with ``error`` naming the exception type) or ``dry_run``.
Arguments are logged with credential values masked (same field rules as
``UNIFI_REDACT_SECRETS``, but always on: logs never carry secrets) and capped in size.
Response bodies and API keys are never logged. The line goes to the server's normal log
stream (stderr), so the server stays stateless; keep the record with your log collector.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult

from ._redaction import mask_credentials

audit_logger = logging.getLogger("unifi_fabric.audit")

#: Serialized-args cap per line; a longer payload is cut and flagged ``argsTruncated``.
MAX_ARGS_CHARS = 2000


def _is_dry_run(exc: BaseException) -> bool:
    """Whether ``exc`` (or its cause chain) is a dry-run interception, not a failure."""
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        if type(node).__name__ == "DryRunIntercepted":
            return True
        seen.add(id(node))
        node = node.__cause__ or node.__context__
    return False


def audit_record(
    tool: str, args: dict[str, Any] | None, outcome: str, duration_ms: int, error: str | None
) -> dict[str, Any]:
    """Build the audit record for one write-tool call."""
    masked, _ = mask_credentials(args or {})
    record: dict[str, Any] = {"tool": tool, "outcome": outcome, "durationMs": duration_ms}
    if error:
        record["error"] = error
    for field in ("host", "site"):
        value = masked.get(field) if isinstance(masked, dict) else None
        if isinstance(value, str):
            record[field] = value
    text = json.dumps(masked, ensure_ascii=False, default=str)
    if len(text) > MAX_ARGS_CHARS:
        record["args"] = text[:MAX_ARGS_CHARS]
        record["argsTruncated"] = True
    else:
        record["args"] = masked
    return record


class WriteAuditMiddleware(Middleware):
    """Log one structured line per call to a tool not marked ``readOnlyHint=true``."""

    def __init__(
        self, enabled: Callable[[], bool], get_tool: Callable[[str], Awaitable[Any]]
    ) -> None:
        self._enabled = enabled
        self._get_tool = get_tool

    async def _is_write(self, name: str) -> bool:
        try:
            tool = await self._get_tool(name)
        except Exception:
            return True  # unknown tool: err on the side of recording the attempt
        hints = getattr(tool, "annotations", None)
        return not (hints is not None and hints.readOnlyHint is True)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        if not self._enabled() or not await self._is_write(name):
            return await call_next(context)
        start = time.monotonic()
        outcome, error = "ok", None
        try:
            result = await call_next(context)
            if result.is_error:
                outcome = "error"
            elif isinstance(result.structured_content, dict) and (
                result.structured_content.get("dryRun") is True
            ):
                outcome = "dry_run"
            return result
        except Exception as exc:
            if _is_dry_run(exc):
                outcome = "dry_run"
            else:
                outcome, error = "error", type(exc).__name__
            raise
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            record = audit_record(name, context.message.arguments, outcome, duration_ms, error)
            audit_logger.info("tool-write-audit %s", json.dumps(record, ensure_ascii=False))
