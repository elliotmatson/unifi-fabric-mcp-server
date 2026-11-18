"""get_camera_snapshot(as_image=true) must reach an MCP client as an image content block.

Runs the real server (middleware stack included, credential masking on by default) against
a mocked api.ui.com, so the image block is checked end to end rather than only at the
wrapper.
"""

from __future__ import annotations

import base64
import re

import httpx
import pytest
import respx
from fastmcp import Client
from mcp import types as mt

from unifi_fabric import server
from unifi_fabric.config import Settings

BASE = "https://api.ui.com"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


async def test_as_image_reaches_client_as_image_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_settings", Settings(api_key="synthetic-key"))
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/hosts").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": "host-1", "reportedState": {"hostname": "example-nvr"}}]},
            )
        )
        snap = router.get(url__regex=re.escape(BASE) + r".*/cameras/cam-1/snapshot.*").mock(
            return_value=httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
        )
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "get_camera_snapshot",
                {"host": "example-nvr", "camera_id": "cam-1", "as_image": True},
            )
    assert snap.called
    image = result.content[0]
    assert isinstance(image, mt.ImageContent)
    assert base64.b64decode(image.data) == JPEG
    assert image.mimeType == "image/jpeg"


async def test_default_still_returns_base64_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_settings", Settings(api_key="synthetic-key"))
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/v1/hosts").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": "host-1", "reportedState": {"hostname": "example-nvr"}}]},
            )
        )
        router.get(url__regex=re.escape(BASE) + r".*/cameras/cam-1/snapshot.*").mock(
            return_value=httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
        )
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "get_camera_snapshot", {"host": "example-nvr", "camera_id": "cam-1"}
            )
    assert result.structured_content["image_base64"] == base64.b64encode(JPEG).decode()
    assert result.structured_content["size_bytes"] == len(JPEG)
