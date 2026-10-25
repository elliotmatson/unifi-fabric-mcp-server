"""Dry-run mode (UNIFI_DRY_RUN): write tools report the request instead of sending it."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client

from unifi_fabric import server
from unifi_fabric._dry_run import DRY_RUN_NOTE, dry_run_result
from unifi_fabric.client import DryRunIntercepted, UniFiClient
from unifi_fabric.config import APIKeyConfig, Settings

BASE = "https://api.ui.com"
ALPHA_HOST = {"id": "host-alpha-1", "reportedState": {"hostname": "alpha-console"}}
BETA_HOST = {"id": "host-beta-1", "reportedState": {"hostname": "beta-console"}}
SITE = {
    "id": "c3d4e5f6-a7b8-4901-8def-123456789012",
    "name": "Default",
    "internalReference": "default",
}


def _settings(dry_run: bool, *, two_keys: bool = False) -> Settings:
    if two_keys:
        return Settings(
            api_keys=[
                APIKeyConfig(key="synthetic-alpha-key", label="alpha"),
                APIKeyConfig(key="synthetic-beta-key", label="beta"),
            ],
            dry_run=dry_run,
        )
    return Settings(api_key="synthetic-alpha-key", dry_run=dry_run)


# --------------------------------------------------------------------------- #
# Client level
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post"])
async def test_mutating_request_is_intercepted_not_sent(method: str) -> None:
    client = UniFiClient(_settings(dry_run=True))
    with respx.mock(assert_all_called=False) as router:
        route = router.route(url__startswith=BASE).mock(return_value=httpx.Response(200))
        with pytest.raises(DryRunIntercepted) as excinfo:
            await client.request(method, "/v1/example", json={"name": "x"}, params={"a": "1"})
        assert not route.called
    assert excinfo.value.preview == {
        "method": method.upper(),
        "path": "/v1/example",
        "keyLabel": "default",
        "params": {"a": "1"},
        "json": {"name": "x"},
        "files": None,
    }
    await client.close()


async def test_reads_and_read_only_posts_still_run() -> None:
    client = UniFiClient(_settings(dry_run=True))
    with respx.mock() as router:
        router.get(f"{BASE}/v1/hosts").mock(return_value=httpx.Response(200, json={"data": []}))
        router.post(f"{BASE}/v1/isp-metrics/5m/query").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        assert await client.get("/v1/hosts") == {"data": []}
        assert await client.post("/v1/isp-metrics/5m/query", json={}, read_only=True) == {
            "data": []
        }
    await client.close()


async def test_multipart_preview_lists_file_names_only() -> None:
    client = UniFiClient(_settings(dry_run=True))
    with pytest.raises(DryRunIntercepted) as excinfo:
        await client.post_multipart("/v1/files/sounds", files={"file": ("a.mp3", b"\x00")})
    assert excinfo.value.preview["files"] == ["file"]
    await client.close()


async def test_dry_run_off_sends_the_request() -> None:
    client = UniFiClient(_settings(dry_run=False))
    with respx.mock() as router:
        route = router.delete(f"{BASE}/v1/example").mock(return_value=httpx.Response(204))
        await client.delete("/v1/example")
        assert route.called
    await client.close()


def test_setting_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_API_KEY", "synthetic-key")
    assert Settings().dry_run is False
    monkeypatch.setenv("UNIFI_DRY_RUN", "true")
    assert Settings().dry_run is True


# --------------------------------------------------------------------------- #
# End to end through the real server and middleware
# --------------------------------------------------------------------------- #


def _mock_console_reads(router: respx.MockRouter) -> None:
    def hosts(request: httpx.Request) -> httpx.Response:
        owned = BETA_HOST if request.headers["X-API-KEY"] == "synthetic-beta-key" else ALPHA_HOST
        return httpx.Response(200, json={"data": [owned]})

    router.get(f"{BASE}/v1/hosts").mock(side_effect=hosts)
    router.get(
        url__regex=re.escape(BASE)
        + r"/v1/connector/consoles/[^/]+/proxy/network/integration/v1/sites.*"
    ).mock(
        return_value=httpx.Response(
            200, json={"data": [SITE], "totalCount": 1, "offset": 0, "limit": 200}
        )
    )


async def _call(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tool: str, args: dict[str, Any]
) -> Any:
    monkeypatch.setattr(server, "_settings", settings)
    async with Client(server.mcp) as client:
        return await client.call_tool(tool, args, raise_on_error=False)


async def test_write_tool_returns_preview_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_console_reads(router)
        write = router.delete(url__regex=r".*/portforward/.*").mock(
            return_value=httpx.Response(200)
        )
        result = await _call(
            monkeypatch,
            _settings(dry_run=True),
            "delete_port_forward",
            {"host": "alpha-console", "site": "Default", "forward_id": "000000000000000000000abc"},
        )
        assert not write.called
    assert not result.is_error
    payload = json.loads(result.content[0].text)  # full preview is always in the text
    assert payload["dryRun"] is True and payload["sent"] is False
    assert payload["tool"] == "delete_port_forward"
    assert payload["note"] == DRY_RUN_NOTE
    req = payload["request"]
    assert req["method"] == "DELETE"
    assert req["path"] == (
        "/v1/connector/consoles/host-alpha-1/proxy/network/api/s/default/rest/portforward/"
        "000000000000000000000abc"
    )
    assert "deleted" not in result.content[0].text  # the tool's success text never appears
    # This tool returns a string, so the structured output keeps its {"result": str} shape.
    assert result.structured_content == {"result": result.content[0].text}


async def test_preview_names_the_owning_key_for_a_beta_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_console_reads(router)
        result = await _call(
            monkeypatch,
            _settings(dry_run=True, two_keys=True),
            "delete_port_forward",
            {"host": "beta-console", "site": "Default", "forward_id": "000000000000000000000abc"},
        )
    req = json.loads(result.content[0].text)["request"]
    assert req["keyLabel"] == "beta"
    assert "/consoles/host-beta-1/" in req["path"]


async def test_validation_errors_still_surface_in_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_console_reads(router)
        result = await _call(
            monkeypatch,
            _settings(dry_run=True),
            "delete_port_forward",
            {"host": "alpha-console", "site": "Default", "forward_id": "../etc"},
        )
    assert result.is_error  # the tool's own input validation runs before any write


async def test_dry_run_off_performs_the_write(monkeypatch: pytest.MonkeyPatch) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_console_reads(router)
        write = router.delete(url__regex=r".*/portforward/.*").mock(
            return_value=httpx.Response(200, json={})
        )
        result = await _call(
            monkeypatch,
            _settings(dry_run=False),
            "delete_port_forward",
            {"host": "alpha-console", "site": "Default", "forward_id": "000000000000000000000abc"},
        )
        assert write.called
    assert "deleted" in result.content[0].text


PREVIEW = {"method": "POST", "path": "/v1/x", "keyLabel": "default"}


@pytest.mark.parametrize(
    ("schema", "check"),
    [
        (None, lambda sc, text: sc is None),
        (
            {"type": "object", "additionalProperties": True},
            lambda sc, text: sc["dryRun"] is True and sc["request"] == PREVIEW,
        ),
        (
            {
                "type": "object",
                "properties": {"result": {"type": "string"}},
                "x-fastmcp-wrap-result": True,
            },
            lambda sc, text: sc == {"result": text},
        ),
        (
            {
                "type": "object",
                "properties": {"result": {"type": "array"}},
                "x-fastmcp-wrap-result": True,
            },
            lambda sc, text: sc["result"][0]["request"] == PREVIEW,
        ),
    ],
)
def test_preview_matches_each_output_schema_shape(schema: Any, check: Any) -> None:
    result = dry_run_result("some_tool", PREVIEW, schema)
    text = result.content[0].text
    assert json.loads(text)["request"] == PREVIEW
    assert check(result.structured_content, text)


async def test_dry_run_is_not_logged_as_a_tool_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # The server's lifespan calls logging.basicConfig(force=True), which would remove
    # pytest's capture handler; keep it so the assertions below see every record.
    monkeypatch.setattr(server.logging, "basicConfig", lambda **_: None)
    caplog.set_level(logging.INFO)
    with respx.mock(assert_all_called=False) as router:
        _mock_console_reads(router)
        await _call(
            monkeypatch,
            _settings(dry_run=True),
            "delete_port_forward",
            {"host": "alpha-console", "site": "Default", "forward_id": "000000000000000000000abc"},
        )
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == []
    assert any("dry run: DELETE" in r.getMessage() for r in caplog.records)
