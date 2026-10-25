"""Write audit log (UNIFI_AUDIT_WRITES): one structured line per write-tool call."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from unifi_fabric import server
from unifi_fabric._audit import MAX_ARGS_CHARS, WriteAuditMiddleware
from unifi_fabric._redaction import REDACTED_VALUE
from unifi_fabric.config import Settings

READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)


class DryRunIntercepted(Exception):  # noqa: N818 - matched by name, like the real signal
    pass


def _app(enabled: bool = True) -> FastMCP:
    app = FastMCP("audit-test")
    app.add_middleware(WriteAuditMiddleware(lambda: enabled, app.get_tool))

    @app.tool(annotations=READ)
    def list_things(host: str) -> dict[str, Any]:
        return {"data": []}

    @app.tool(annotations=WRITE)
    def update_wlan(host: str, site: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    @app.tool(annotations=WRITE)
    def failing_write(host: str) -> dict[str, Any]:
        raise RuntimeError("upstream said no")

    @app.tool(annotations=WRITE)
    def dry_write(host: str) -> dict[str, Any]:
        raise DryRunIntercepted("not sent")

    return app


def _records(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    out = []
    for rec in caplog.records:
        if rec.name == "unifi_fabric.audit":
            msg = rec.getMessage()
            assert msg.startswith("tool-write-audit ")
            out.append(json.loads(msg.removeprefix("tool-write-audit ")))
    return out


async def test_write_logs_one_masked_line_and_reads_log_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="unifi_fabric.audit")
    async with Client(_app()) as client:
        await client.call_tool("list_things", {"host": "Example Console"})
        await client.call_tool(
            "update_wlan",
            {
                "host": "Example Console",
                "site": "Default",
                "payload": {"name": "Example Guest", "x_passphrase": "synthetic-pass"},
            },
        )
    records = _records(caplog)
    assert len(records) == 1
    rec = records[0]
    assert rec["tool"] == "update_wlan"
    assert rec["outcome"] == "ok"
    assert rec["host"] == "Example Console" and rec["site"] == "Default"
    assert rec["args"]["payload"]["name"] == "Example Guest"
    assert rec["args"]["payload"]["x_passphrase"] == REDACTED_VALUE
    assert "synthetic-pass" not in caplog.text
    assert isinstance(rec["durationMs"], int)


async def test_failed_write_is_logged_as_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="unifi_fabric.audit")
    async with Client(_app()) as client:
        result = await client.call_tool("failing_write", {"host": "h"}, raise_on_error=False)
    assert result.is_error
    (rec,) = _records(caplog)
    assert rec["outcome"] == "error"
    assert rec["error"] == "ToolError"


async def test_dry_run_interception_is_logged_as_dry_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="unifi_fabric.audit")
    async with Client(_app()) as client:
        await client.call_tool("dry_write", {"host": "h"}, raise_on_error=False)
    (rec,) = _records(caplog)
    assert rec["outcome"] == "dry_run"
    assert "error" not in rec


async def test_large_args_are_truncated_and_flagged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="unifi_fabric.audit")
    big = {"rules": ["r" * 100] * 100}
    async with Client(_app()) as client:
        await client.call_tool("update_wlan", {"host": "h", "site": "s", "payload": big})
    (rec,) = _records(caplog)
    assert rec["argsTruncated"] is True
    assert len(rec["args"]) == MAX_ARGS_CHARS


async def test_disabled_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="unifi_fabric.audit")
    async with Client(_app(enabled=False)) as client:
        await client.call_tool("update_wlan", {"host": "h", "site": "s", "payload": {}})
    assert _records(caplog) == []


def test_setting_defaults_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_API_KEY", "synthetic-key")
    assert Settings().audit_writes is True
    monkeypatch.setenv("UNIFI_AUDIT_WRITES", "false")
    assert Settings().audit_writes is False


def test_server_registers_audit_middleware() -> None:
    assert any(isinstance(m, WriteAuditMiddleware) for m in server.mcp.middleware)
