"""Opt-in credential masking (UNIFI_REDACT_SECRETS) on tool results.

Default is pass-through: these tests pin both that nothing is masked unless the setting is
on, and exactly which fields are masked when it is.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from unifi_fabric import server
from unifi_fabric._redaction import (
    REDACTED_VALUE,
    CredentialMaskingMiddleware,
    is_credential_field,
    mask_credentials,
)
from unifi_fabric.config import Settings

# Synthetic values only.
WLAN = {
    "_id": "000000000000000000000001",
    "name": "Example Guest",
    "x_passphrase": "synthetic-passphrase",
    "x_ssh_auth_password_enabled": True,
    "securityConfiguration": {"type": "WPA2_PERSONAL", "passphrase": "synthetic-pass-2"},
}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("x_passphrase", "s"),
        ("x_password", "s"),
        ("x_ssh_password", "s"),
        ("x_wireguard_private_key", "s"),
        ("x_ca_crts", ["-----BEGIN CERTIFICATE-----"]),
        ("passphrase", "s"),
        ("password", "s"),
        ("psk", "s"),
        ("preSharedKey", "s"),
        ("sharedSecret", "s"),
        ("authServerSecret", "s"),
        ("acctServerSecret", "s"),
        ("wanPassword", "s"),
        ("privateKey", "s"),
        ("wireguardPrivateKey", "s"),
        ("api_key", "s"),
        ("apiToken", "s"),
        ("token", "s"),
        ("refresh_token", "s"),
        ("client_secret", "s"),
    ],
)
def test_credential_fields_are_masked(key: str, value: Any) -> None:
    assert is_credential_field(key, value)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("x_ssh_auth_password_enabled", True),  # bool flag, not a secret
        ("passwordRequired", False),
        ("secretCount", 3),
        ("x_password", None),
        ("x_password", ""),  # empty: nothing to hide
        ("nextToken", "cursor-abc"),  # pagination cursor
        ("page_token", "cursor-abc"),
        ("tokenExpiry", "2026-01-01T00:00:00Z"),
        ("name", "Example Guest"),
        ("macAddress", "02:00:00:00:00:01"),
        ("x_ssh_keys", [{"name": "laptop", "key": "ssh-ed25519 AAAA"}]),  # recursed, not whole
    ],
)
def test_non_credential_fields_are_kept(key: str, value: Any) -> None:
    assert not is_credential_field(key, value)


def test_mask_credentials_nested_paths_and_input_untouched() -> None:
    data = {"data": [dict(WLAN)], "totalCount": 1, "nextToken": "cursor-abc"}
    original = json.loads(json.dumps(data))
    masked, paths = mask_credentials(data)

    assert data == original  # input not modified
    row = masked["data"][0]
    assert row["x_passphrase"] == REDACTED_VALUE
    assert row["securityConfiguration"]["passphrase"] == REDACTED_VALUE
    assert row["securityConfiguration"]["type"] == "WPA2_PERSONAL"
    assert row["x_ssh_auth_password_enabled"] is True
    assert row["name"] == "Example Guest"
    assert masked["nextToken"] == "cursor-abc"
    assert sorted(paths) == [
        "data[0].securityConfiguration.passphrase",
        "data[0].x_passphrase",
    ]


def test_mask_credentials_without_secrets_is_identity() -> None:
    data = {"data": [{"id": "x", "enabled": True}]}
    masked, paths = mask_credentials(data)
    assert masked == data
    assert paths == []


def _app(enabled: bool) -> FastMCP:
    app = FastMCP("redaction-test")
    app.add_middleware(CredentialMaskingMiddleware(lambda: enabled))

    @app.tool()
    def get_wlan() -> dict[str, Any]:
        return {"data": [dict(WLAN)]}

    @app.tool()
    def list_wlans() -> list[dict[str, Any]]:
        return [dict(WLAN)]

    return app


async def test_middleware_masks_structured_and_text_content() -> None:
    async with Client(_app(enabled=True)) as client:
        result = await client.call_tool("get_wlan", {})
    row = result.structured_content["data"][0]
    assert row["x_passphrase"] == REDACTED_VALUE
    assert row["securityConfiguration"]["passphrase"] == REDACTED_VALUE
    text = json.loads(result.content[0].text)
    assert text["data"][0]["x_passphrase"] == REDACTED_VALUE
    assert "synthetic-passphrase" not in result.content[0].text
    assert result.meta["redactedFields"] == [
        "data[0].securityConfiguration.passphrase",
        "data[0].x_passphrase",
    ]


async def test_middleware_masks_list_results() -> None:
    async with Client(_app(enabled=True)) as client:
        result = await client.call_tool("list_wlans", {})
    assert "synthetic-passphrase" not in result.content[0].text
    assert "synthetic-pass-2" not in json.dumps(result.structured_content)


async def test_middleware_disabled_is_pass_through() -> None:
    async with Client(_app(enabled=False)) as client:
        result = await client.call_tool("get_wlan", {})
    assert result.structured_content == {"data": [WLAN]}
    assert json.loads(result.content[0].text) == {"data": [WLAN]}
    assert not (result.meta or {}).get("redactedFields")


def test_setting_defaults_on_in_this_fork(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_API_KEY", "synthetic-key")
    assert Settings().redact_secrets is True
    monkeypatch.setenv("UNIFI_REDACT_SECRETS", "false")
    assert Settings().redact_secrets is False


def test_server_registers_masking_middleware() -> None:
    assert any(isinstance(m, CredentialMaskingMiddleware) for m in server.mcp.middleware)
