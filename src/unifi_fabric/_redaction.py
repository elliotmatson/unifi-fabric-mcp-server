"""Opt-in credential masking for tool results (``UNIFI_REDACT_SECRETS``).

By default this server is a faithful pass-through: tool results carry the complete upstream
payload, credential fields included (see the pass-through invariant in CONTRIBUTING.md).
A deployment that must not hand credentials to its MCP clients can set
``UNIFI_REDACT_SECRETS=true``; this module then masks the *values* of credential fields in
every tool result, at the point the result leaves the server.

Design points:

* **Result layer only.** Masking runs in FastMCP middleware on the finished tool result.
  Tool logic (read-before/after comparisons, registry caches, payload builders) always
  works on raw upstream data, so behaviour does not change with the setting.
* **Explicit, documented field rules, not a broad pattern.** A value is masked when its key
  is a known credential name (``CREDENTIAL_KEYS``), ends in a credential suffix
  (``CREDENTIAL_SUFFIXES``), or is a Classic-API ``x_`` field (UniFi's convention for
  secret-bearing fields). Keys are compared case-insensitively with ``_``/``-`` removed.
* **Only strings are masked.** Booleans, numbers and nulls are never credentials, so flags
  such as ``x_ssh_auth_password_enabled`` and counts survive; pagination cursors such as
  ``nextToken`` do not match any rule.
* **Self-describing.** Masked values read ``REDACTED_VALUE`` and the result's ``_meta``
  lists the masked field paths under ``redactedFields``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult

REDACTED_VALUE = "[REDACTED: set UNIFI_REDACT_SECRETS=false to return credentials]"

#: Exact credential field names, normalised (lowercase, ``_``/``-`` removed).
CREDENTIAL_KEYS: frozenset[str] = frozenset(
    {
        "passphrase",
        "password",
        "passwd",
        "secret",
        "psk",
        "presharedkey",
        "sharedsecret",
        "privatekey",
        "apikey",
        "apitoken",
        "token",
        "accesstoken",
        "refreshtoken",
        "bearertoken",
        "authtoken",
        "clientsecret",
        "authkey",
    }
)

#: Credential suffixes, normalised. ``authServerSecret``, ``wanPassword`` and
#: ``wireguardPrivateKey`` match; ``nextToken`` and ``passwordEnabled`` do not.
CREDENTIAL_SUFFIXES: tuple[str, ...] = (
    "password",
    "passphrase",
    "secret",
    "privatekey",
    "presharedkey",
)


def _normalise(key: str) -> str:
    return key.lower().replace("_", "").replace("-", "")


def is_credential_field(key: str, value: Any) -> bool:
    """Whether ``value`` stored under ``key`` is a credential that should be masked."""
    if isinstance(value, str):
        if not value:
            return False
    elif isinstance(value, list):
        if not value or not all(isinstance(item, str) for item in value):
            return False
    else:
        return False
    if key.lower().startswith("x_"):
        return True
    norm = _normalise(key)
    return norm in CREDENTIAL_KEYS or norm.endswith(CREDENTIAL_SUFFIXES)


def mask_credentials(value: Any, path: str = "") -> tuple[Any, list[str]]:
    """Return ``value`` with credential field values masked, plus the masked paths.

    The input is not modified. Paths use ``.`` for keys and ``[i]`` for list indexes.
    """
    masked_paths: list[str] = []

    def walk(node: Any, here: str) -> Any:
        if isinstance(node, dict):
            out: dict[Any, Any] = {}
            for key, item in node.items():
                child = f"{here}.{key}" if here else str(key)
                if isinstance(key, str) and is_credential_field(key, item):
                    out[key] = REDACTED_VALUE
                    masked_paths.append(child)
                else:
                    out[key] = walk(item, child)
            return out
        if isinstance(node, list):
            return [walk(item, f"{here}[{i}]") for i, item in enumerate(node)]
        return node

    return walk(value, path), masked_paths


def mask_tool_result(result: ToolResult) -> ToolResult:
    """Mask credentials in a tool result's structured content and JSON text content."""
    paths: list[str] = []
    structured = result.structured_content
    if structured is not None:
        structured, paths = mask_credentials(structured)

    content: list[mt.ContentBlock] = []
    for block in result.content:
        if isinstance(block, mt.TextContent):
            try:
                parsed = json.loads(block.text)
            except ValueError:
                content.append(block)
                continue
            masked, text_paths = mask_credentials(parsed)
            if text_paths:
                if not paths:
                    paths = text_paths
                block = block.model_copy(update={"text": json.dumps(masked, ensure_ascii=False)})
        content.append(block)

    if not paths:
        return result
    meta = dict(result.meta or {})
    meta["redactedFields"] = sorted(set(paths))
    return ToolResult(
        content=content, structured_content=structured, meta=meta, is_error=result.is_error
    )


class CredentialMaskingMiddleware(Middleware):
    """Mask credential values in every tool result while ``enabled()`` returns True.

    ``enabled`` is read on each call, so the setting is resolved lazily from the server's
    settings rather than at import time.
    """

    def __init__(self, enabled: Callable[[], bool]) -> None:
        self._enabled = enabled

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)
        if not self._enabled():
            return result
        return mask_tool_result(result)
