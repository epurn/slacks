#!/usr/bin/env python3
"""Guard current Markdown docs against stale product-brand prose."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]

CURRENT_DOC_FILES = (
    "README.md",
    "CHANGELOG.md",
    "AGENTS.md",
    "backend/README.md",
)
DOCS_ROOT = "docs"
EXCLUDED_DOC_PREFIXES = ("docs/verification/",)

BRAND_WORD = re.compile(r"\bfatty\b", re.IGNORECASE)
OLD_REPO_REFERENCE = re.compile(r"github\.com/epurn/fatty(?:\.git)?", re.IGNORECASE)
CHECKOUT_CD = re.compile(r"(?<![\w.-])cd\s+fatty(?:\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class LiteralException:
    pattern: re.Pattern[str]
    reason: str


@dataclass(frozen=True)
class Finding:
    path: str
    line_number: int
    reason: str
    line: str


# These are the intentionally narrow legacy/runtime literals that remain public
# documentation until their owning runtime/config identifiers are migrated.
LITERAL_EXCEPTIONS = (
    LiteralException(
        re.compile(r"FATTY_[A-Z0-9_]+"),
        "current self-host environment variable prefix",
    ),
    LiteralException(
        re.compile(r"\bfatty acids?\b", re.IGNORECASE),
        "ordinary English nutrition term, not the product brand",
    ),
    LiteralException(
        re.compile(r"Fatty/1\.0"),
        "current Open Food Facts user-agent runtime default",
    ),
    LiteralException(
        re.compile(r"\bfatty-backend\b"),
        "current backend package/application identifier",
    ),
    LiteralException(
        re.compile(r"\bfatty-reviewer\b"),
        "current GitHub App slug",
    ),
    LiteralException(
        re.compile(r"postgresql://fatty:fatty@localhost:5432/fatty"),
        "documented local Postgres user/password/database default",
    ),
    LiteralException(
        re.compile(r"\bpsql -U fatty fatty\b"),
        "documented local Postgres user/database command",
    ),
    LiteralException(
        re.compile(r"`fatty`(?: \(UID/GID 10001\)|, UID/GID\b| user\b)"),
        "current non-root container user literal",
    ),
    LiteralException(
        re.compile(r"/home/fatty\b"),
        "current container home/runtime path",
    ),
)


def exception_spans(line: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for exception in LITERAL_EXCEPTIONS:
        spans.extend((match.start(), match.end()) for match in exception.pattern.finditer(line))
    return spans


def span_allowed(start: int, end: int, spans: Iterable[tuple[int, int]]) -> bool:
    return any(allowed_start <= start and end <= allowed_end for allowed_start, allowed_end in spans)


def current_doc_paths(root: Path) -> list[Path]:
    paths = [root / path for path in CURRENT_DOC_FILES if (root / path).is_file()]
    docs_root = root / DOCS_ROOT
    if docs_root.is_dir():
        paths.extend(docs_root.rglob("*.md"))

    current_paths: list[Path] = []
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(prefix) for prefix in EXCLUDED_DOC_PREFIXES):
            continue
        current_paths.append(path)
    return sorted(set(current_paths))


def validate(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in current_doc_paths(root):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            specific_failure_spans: list[tuple[int, int]] = []
            for match in OLD_REPO_REFERENCE.finditer(line):
                specific_failure_spans.append((match.start(), match.end()))
                findings.append(
                    Finding(
                        rel,
                        line_number,
                        "old public repo reference; use github.com/epurn/slacks",
                        line,
                    )
                )
            for match in CHECKOUT_CD.finditer(line):
                specific_failure_spans.append((match.start(), match.end()))
                findings.append(
                    Finding(rel, line_number, "old checkout directory; use cd slacks", line)
                )

            allowed_spans = exception_spans(line) + specific_failure_spans
            for match in BRAND_WORD.finditer(line):
                if span_allowed(match.start(), match.end(), allowed_spans):
                    continue
                findings.append(
                    Finding(
                        rel,
                        line_number,
                        "stale product brand prose; rename to Slacks or add a justified literal exception",
                        line,
                    )
                )

    return findings


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="slacks-brand-guard-") as tmp:
        root = Path(tmp)
        write(root / "README.md", "# Slacks\n\nSlacks uses `FATTY_AUTH_SECRET`.\n")
        write(root / "CHANGELOG.md", "Essential fatty acids remain ordinary prose.\n")
        write(
            root / "backend/README.md",
            "Default DSN: `postgresql://fatty:fatty@localhost:5432/fatty`.\n",
        )
        write(root / "docs/contracts/food-resolution.md", "User agent: `Fatty/1.0`.\n")
        write(root / "docs/verification/FTY-000/README.md", "Fatty is historical evidence.\n")
        if validate(root):
            raise AssertionError("allowed literal fixture should pass")

        write(root / "README.md", "# Slacks\n\nFatty is an app.\n")
        findings = validate(root)
        if not any("README.md:3" in f"{item.path}:{item.line_number}" for item in findings):
            raise AssertionError("stale product prose fixture should fail")

        write(root / "README.md", "git clone https://github.com/epurn/fatty.git\ncd fatty\n")
        findings = validate(root)
        if not any("old public repo reference" in item.reason for item in findings):
            raise AssertionError("old repository fixture should fail")
        if not any("old checkout directory" in item.reason for item in findings):
            raise AssertionError("old checkout directory fixture should fail")

    print("brand name guard self-tests passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return

    findings = validate(args.root.resolve())
    if findings:
        print("brand name check failed:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding.path}:{finding.line_number}: {finding.reason}", file=sys.stderr)
        raise SystemExit(1)

    print("brand name checks passed")


if __name__ == "__main__":
    main()
