#!/usr/bin/env python3
"""Print the CHANGELOG.md section for one release version.

Used by the release workflow to (a) refuse a release whose version has no changelog
section and (b) produce the GitHub Release notes. Prints the body of
``## [X.Y.Z] - date`` up to the next ``## [`` heading, without the heading itself.

Usage: python3 scripts/changelog_section.py 0.7.0 [--changelog PATH]
Exit status 1 if the section is missing or empty.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\]")


def extract_section(text: str, version: str) -> str | None:
    """Return the stripped body of ``version``'s section, or None if absent or empty."""
    version = version.removeprefix("v")
    lines: list[str] | None = None
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            if lines is not None:
                break
            if match.group("version") == version:
                lines = []
            continue
        if lines is not None:
            lines.append(line)
    if lines is None:
        return None
    body = "\n".join(lines).strip()
    return body or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="Release version, with or without a leading 'v'")
    parser.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    args = parser.parse_args(argv)

    section = extract_section(args.changelog.read_text(encoding="utf-8"), args.version)
    if section is None:
        print(
            f"error: no non-empty '## [{args.version.removeprefix('v')}]' section in "
            f"{args.changelog}",
            file=sys.stderr,
        )
        return 1
    print(section)
    return 0


if __name__ == "__main__":
    sys.exit(main())
