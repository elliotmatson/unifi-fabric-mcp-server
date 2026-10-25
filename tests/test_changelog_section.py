"""Tests for scripts/changelog_section.py (release-notes extraction)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import changelog_section  # noqa: E402

_CHANGELOG = """# Changelog

## [Unreleased]

### Added
- unreleased thing

## [1.2.0] - 2026-01-02

### Added
- new tool

### Fixed
- a bug

## [1.1.0] - 2026-01-01

## [1.0.0] - 2025-12-31

### Added
- first release
"""


def test_extracts_middle_section_without_heading() -> None:
    body = changelog_section.extract_section(_CHANGELOG, "1.2.0")
    assert body == "### Added\n- new tool\n\n### Fixed\n- a bug"


def test_accepts_leading_v() -> None:
    assert changelog_section.extract_section(_CHANGELOG, "v1.0.0") == "### Added\n- first release"


def test_missing_version_returns_none() -> None:
    assert changelog_section.extract_section(_CHANGELOG, "9.9.9") is None


def test_empty_section_returns_none() -> None:
    assert changelog_section.extract_section(_CHANGELOG, "1.1.0") is None


def test_version_is_not_prefix_matched() -> None:
    assert changelog_section.extract_section(_CHANGELOG, "1.2") is None


def test_main_prints_section(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(_CHANGELOG, encoding="utf-8")
    assert changelog_section.main(["v1.2.0", "--changelog", str(path)]) == 0
    assert capsys.readouterr().out.startswith("### Added\n- new tool")


def test_main_fails_on_missing_section(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(_CHANGELOG, encoding="utf-8")
    assert changelog_section.main(["2.0.0", "--changelog", str(path)]) == 1
    assert "no non-empty '## [2.0.0]'" in capsys.readouterr().err
