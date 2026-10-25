"""MCP tool annotations: every tool declares whether it reads, adds, or destroys.

``tools/_annotations.py`` holds the explicit classification (``TOOL_CLASS``). These tests
pin it to the registered tools in both directions, check the hints each class carries,
sanity-check name prefixes against the class, and confirm the hints reach MCP clients.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp.types import ToolAnnotations

from unifi_fabric import server
from unifi_fabric.tools._annotations import (
    ADDITIVE,
    DESTRUCTIVE,
    DESTRUCTIVE_IDEMPOTENT,
    READ_ONLY,
    TOOL_CLASS,
)


@pytest.fixture(scope="module")
async def tools() -> dict[str, Any]:
    return {t.name: t for t in await server.mcp.list_tools()}


async def test_every_tool_has_annotations_with_read_only_hint(tools: dict[str, Any]) -> None:
    missing = sorted(
        name
        for name, tool in tools.items()
        if tool.annotations is None or tool.annotations.readOnlyHint is None
    )
    assert not missing, f"tools without readOnlyHint: {missing}"


async def test_tool_class_matches_registered_tools_exactly(tools: dict[str, Any]) -> None:
    registered = set(tools)
    classified = set(TOOL_CLASS)
    assert not registered - classified, f"registered but unclassified: {registered - classified}"
    assert not classified - registered, f"classified but not registered: {classified - registered}"


async def test_registered_annotations_are_the_tool_class_entries(tools: dict[str, Any]) -> None:
    wrong = sorted(n for n, t in tools.items() if t.annotations != TOOL_CLASS[n])
    assert not wrong, f"annotations differ from TOOL_CLASS: {wrong}"


def test_class_constants_carry_the_expected_hints() -> None:
    assert READ_ONLY == ToolAnnotations(readOnlyHint=True)
    assert ADDITIVE == ToolAnnotations(readOnlyHint=False, destructiveHint=False)
    assert DESTRUCTIVE == ToolAnnotations(readOnlyHint=False, destructiveHint=True)
    assert DESTRUCTIVE_IDEMPOTENT == ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True
    )
    for hints in (READ_ONLY, ADDITIVE, DESTRUCTIVE, DESTRUCTIVE_IDEMPOTENT):
        assert hints.openWorldHint is None


@pytest.mark.parametrize("prefix", ["list_", "get_", "search_"])
def test_read_prefixes_are_read_only(prefix: str) -> None:
    names = [n for n in TOOL_CLASS if n.startswith(prefix)]
    assert names
    assert [n for n in names if TOOL_CLASS[n] is not READ_ONLY] == []


@pytest.mark.parametrize("prefix", ["delete_", "bulk_delete_"])
def test_delete_prefixes_are_destructive(prefix: str) -> None:
    names = [n for n in TOOL_CLASS if n.startswith(prefix)]
    assert names
    assert [n for n in names if TOOL_CLASS[n].destructiveHint is not True] == []


@pytest.mark.parametrize("prefix", ["update_", "set_"])
def test_update_and_set_are_idempotent(prefix: str) -> None:
    names = [n for n in TOOL_CLASS if n.startswith(prefix)]
    assert names
    assert [n for n in names if TOOL_CLASS[n] is not DESTRUCTIVE_IDEMPOTENT] == []


def test_create_prefix_is_additive() -> None:
    names = [n for n in TOOL_CLASS if n.startswith("create_")]
    assert names
    assert [n for n in names if TOOL_CLASS[n] is not ADDITIVE] == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("fabric_connector_get", READ_ONLY),
        ("fabric_connector_post", ADDITIVE),
        ("fabric_connector_put", DESTRUCTIVE),
        ("fabric_connector_patch", DESTRUCTIVE),
        ("fabric_connector_delete", DESTRUCTIVE),
        ("query_isp_metrics", READ_ONLY),
        ("restart_device", DESTRUCTIVE),
        ("unblock_client", ADDITIVE),
        ("block_client", DESTRUCTIVE),
    ],
)
def test_non_prefix_tools_are_classified_explicitly(name: str, expected: ToolAnnotations) -> None:
    assert TOOL_CLASS[name] is expected


async def test_annotations_reach_mcp_clients(tools: dict[str, Any]) -> None:
    """The protocol-level tool (what tools/list serves) carries the hints."""
    listed = tools["list_hosts"].to_mcp_tool()
    assert listed.annotations is not None
    assert listed.annotations.readOnlyHint is True
    delete = tools["delete_network"].to_mcp_tool().annotations
    assert delete is not None
    assert (delete.readOnlyHint, delete.destructiveHint) == (False, True)
