"""Credential masking must wrap dry-run, so previewed request bodies are masked too."""

from __future__ import annotations

import re

import httpx
import pytest
import respx
from fastmcp import Client

from unifi_fabric import server
from unifi_fabric._dry_run import DryRunMiddleware
from unifi_fabric._redaction import CredentialMaskingMiddleware
from unifi_fabric.config import Settings

BASE = "https://api.ui.com"


def test_masking_is_registered_outside_dry_run() -> None:
    kinds = [type(m) for m in server.mcp.middleware]
    assert kinds.index(CredentialMaskingMiddleware) < kinds.index(DryRunMiddleware)


async def test_dry_run_preview_masks_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_settings", Settings(api_key="synthetic-key", dry_run=True))
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/hosts").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": "host-1", "reportedState": {"hostname": "example-console"}}]},
            )
        )
        router.get(url__regex=re.escape(BASE) + r".*/integration/v1/sites.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "c3d4e5f6-a7b8-4901-8def-123456789012",
                            "name": "Default",
                            "internalReference": "default",
                        }
                    ],
                    "totalCount": 1,
                    "offset": 0,
                    "limit": 200,
                },
            )
        )
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "update_wlan_config",
                {
                    "host": "example-console",
                    "site": "Default",
                    "wlan_id": "000000000000000000000001",
                    "payload": {"name": "Example", "x_passphrase": "synthetic-new-pass"},
                },
                raise_on_error=False,
            )
    text = result.content[0].text
    assert '"dryRun": true' in text
    assert "synthetic-new-pass" not in text
    assert "x_passphrase" in text  # the field is shown, only its value is masked
