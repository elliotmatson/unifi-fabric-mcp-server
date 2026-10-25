"""Read-only mode and tool-family selectors (UNIFI_READ_ONLY, UNIFI_*TOOL_FAMILIES)."""

from __future__ import annotations

from collections import Counter

import pytest
from fastmcp import Client

from unifi_fabric import server
from unifi_fabric._tool_selection import parse_families, unavailable_reason
from unifi_fabric.config import Settings
from unifi_fabric.tools._annotations import READ_ONLY, TOOL_CLASS
from unifi_fabric.tools._families import FAMILY_DESCRIPTIONS, FAMILY_TOOLS, TOOL_FAMILY


def _settings(**kwargs: object) -> Settings:
    return Settings(api_key="synthetic-key", **kwargs)


# --------------------------------------------------------------------------- #
# Family table
# --------------------------------------------------------------------------- #


async def test_family_table_matches_registered_tools_exactly() -> None:
    registered = {t.name for t in await server.mcp.list_tools()}
    assert set(TOOL_FAMILY) == registered


def test_each_tool_is_in_exactly_one_family() -> None:
    counts = Counter(name for names in FAMILY_TOOLS.values() for name in names)
    assert [name for name, n in counts.items() if n > 1] == []


def test_every_family_is_described_and_non_empty() -> None:
    assert set(FAMILY_DESCRIPTIONS) == set(FAMILY_TOOLS)
    assert all(FAMILY_TOOLS.values())


@pytest.mark.parametrize(
    ("tool", "family"),
    [
        ("list_hosts", "site_manager"),
        ("get_fleet_summary", "site_manager"),
        ("list_networks", "network"),
        ("list_hotspot_vouchers", "hotspot"),
        ("create_hotspot_operator", "hotspot"),
        ("list_vpn_servers", "vpn"),
        ("create_radius_profile", "vpn"),
        ("list_acl_rules", "firewall"),
        ("restart_device", "devices"),
        ("block_client", "clients"),
        ("list_cameras", "protect"),
        ("list_recognition_groups", "protect"),
        ("fabric_connector_get", "connector"),
    ],
)
def test_family_assignments(tool: str, family: str) -> None:
    assert TOOL_FAMILY[tool] == family


# --------------------------------------------------------------------------- #
# Selection rules
# --------------------------------------------------------------------------- #


def test_defaults_expose_everything() -> None:
    settings = _settings()
    assert all(unavailable_reason(name, settings) is None for name in TOOL_FAMILY)


def test_read_only_hides_every_write() -> None:
    settings = _settings(read_only=True)
    for name, hints in TOOL_CLASS.items():
        reason = unavailable_reason(name, settings)
        assert (reason is None) == (hints is READ_ONLY), name
    assert "read-only" in (unavailable_reason("delete_network", settings) or "")


def test_family_allow_and_deny_lists_combine() -> None:
    settings = _settings(tool_families="network, protect", disabled_tool_families="protect")
    assert unavailable_reason("list_networks", settings) is None
    assert "UNIFI_DISABLED_TOOL_FAMILIES" in (unavailable_reason("list_cameras", settings) or "")
    assert "UNIFI_TOOL_FAMILIES" in (unavailable_reason("list_hosts", settings) or "")


def test_parse_families_accepts_commas_spaces_and_case() -> None:
    assert parse_families(" Network,protect  vpn ", "X") == {"network", "protect", "vpn"}
    assert parse_families("", "X") == set()


def test_parse_families_rejects_unknown_names() -> None:
    with pytest.raises(
        ValueError, match=r"UNIFI_TOOL_FAMILIES has unknown tool families \['netwrok'\]"
    ):
        parse_families("netwrok", "UNIFI_TOOL_FAMILIES")


def test_settings_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_API_KEY", "synthetic-key")
    settings = Settings()
    assert settings.read_only is False
    assert settings.tool_families == ""
    assert settings.disabled_tool_families == ""
    monkeypatch.setenv("UNIFI_READ_ONLY", "true")
    monkeypatch.setenv("UNIFI_TOOL_FAMILIES", "network")
    settings = Settings()
    assert settings.read_only is True
    assert settings.tool_families == "network"


# --------------------------------------------------------------------------- #
# End to end through the real server
# --------------------------------------------------------------------------- #


async def _listed(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> set[str]:
    monkeypatch.setattr(server, "_settings", settings)
    async with Client(server.mcp) as client:
        return {t.name for t in await client.list_tools()}


async def test_tools_list_default_is_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await _listed(monkeypatch, _settings()) == set(TOOL_FAMILY)


async def test_tools_list_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    listed = await _listed(monkeypatch, _settings(read_only=True))
    assert listed == {name for name, hints in TOOL_CLASS.items() if hints is READ_ONLY}


async def test_tools_list_by_family(monkeypatch: pytest.MonkeyPatch) -> None:
    listed = await _listed(monkeypatch, _settings(tool_families="protect"))
    assert listed == set(FAMILY_TOOLS["protect"])
    listed = await _listed(monkeypatch, _settings(disabled_tool_families="connector"))
    assert listed == set(TOOL_FAMILY) - set(FAMILY_TOOLS["connector"])


async def test_calling_a_hidden_tool_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_settings", _settings(read_only=True))
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "delete_network",
            {"host": "h", "site": "s", "network_id": "000000000000000000000001"},
            raise_on_error=False,
        )
    assert result.is_error
    assert "not available on this server" in result.content[0].text
    assert "UNIFI_READ_ONLY" in result.content[0].text


async def test_startup_rejects_unknown_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_settings", _settings(disabled_tool_families="conector"))
    with pytest.raises(Exception, match="unknown tool families"):
        async with Client(server.mcp):
            pass
