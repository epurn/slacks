#!/usr/bin/env python3
"""Validate the public monorepo scaffold from FTY-010.

The check stays dependency-free so root verification works before backend,
mobile, or contract package toolchains are installed.
"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]

PACKAGE_READMES = {
    "apps/backend/README.md": [
        "Path: `apps/backend`",
        "FTY-010",
        "FastAPI",
        "No runtime services",
    ],
    "apps/mobile/README.md": [
        "Path: `apps/mobile`",
        "FTY-010",
        "Expo / React Native",
        "No UI shell",
    ],
    "packages/contracts/README.md": [
        "Path: `packages/contracts`",
        "FTY-010",
        "DTO schemas",
        "`docs/contracts`",
    ],
}

MAKEFILE_TERMS = [
    "apps/backend",
    "apps/mobile",
    "packages/contracts",
    "verify-monorepo-scaffold.py",
    "$$package/Makefile",
]


def fail(message: str) -> None:
    print(f"monorepo scaffold check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_terms(path: str, terms: list[str]) -> None:
    content = read(path)
    for term in terms:
        if term not in content:
            fail(f"{path} must include {term!r}")


def main() -> None:
    for path, terms in PACKAGE_READMES.items():
        if not (ROOT / path).is_file():
            fail(f"missing package ownership file: {path}")
        require_terms(path, terms)

    require_terms("Makefile", MAKEFILE_TERMS)

    print("monorepo scaffold checks passed")


if __name__ == "__main__":
    main()
