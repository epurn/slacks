#!/usr/bin/env python3
"""Guard first-party code shape and backend-estimator boundaries.

The guard is dependency-free. It enforces two contracts with different weights:

* **LOC thresholds are advisory (warn-only).** Every first-party file over its
  kind's threshold is reported as a stable, greppable ``loc-advisory:`` line so
  authors and reviewers can see it (and file a refactor story), but it never
  fails the gate. Oversized files are addressed through dedicated refactor
  stories, not by blocking unrelated PRs.
* **Backend/estimator boundary imports are blocking.** A crossing that is not
  in the ``boundary_imports`` allowlist of ``code-shape-baseline.json`` fails
  the governance gate.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "scripts" / "code-shape-baseline.json"

SOURCE_EXTENSIONS = {".js", ".jsx", ".md", ".py", ".sh", ".ts", ".tsx", ".yaml", ".yml"}
SOURCE_ROOTS = (
    ".github/",
    "backend/",
    "contracts/",
    "docs/",
    "infra/",
    "mobile/",
    "packages/",
    "scripts/",
    "searxng/",
)
EXCLUDED_PARTS = {
    ".expo",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "fixtures",
    "htmlcov",
    "node_modules",
    "snapshots",
    "tmp",
    "venv",
}
EXCLUDED_PREFIXES = (
    "backend/tests/fixtures/",
    "backend/tests/snapshots/",
    "docs/verification/",
)
ESTIMATOR_PUBLIC_FACADE = "app.estimator"


@dataclass(frozen=True)
class SourceFile:
    path: str
    absolute_path: Path
    kind: str
    lane: str
    lines: int


@dataclass(frozen=True)
class BoundaryImport:
    direction: str
    path: str
    module: str
    line: int

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.direction, self.path, self.module)


def fail(message: str) -> None:
    print(f"code shape check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_baseline(path: Path) -> dict[str, Any]:
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing baseline file: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid baseline JSON {path}: {exc}")

    if baseline.get("version") != 1:
        fail("code shape baseline must have version 1")
    if not isinstance(baseline.get("loc_thresholds"), dict):
        fail("code shape baseline must define loc_thresholds")
    if not isinstance(baseline.get("boundary_imports"), list):
        fail("code shape baseline must define boundary_imports")
    return baseline


def git_files(root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    return [line for line in result.stdout.splitlines() if line]


def walk_files(root: Path) -> list[str]:
    paths: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if excluded(rel):
            continue
        paths.append(rel)
    return sorted(paths)


def repository_files(root: Path) -> list[str]:
    files = git_files(root)
    if files is not None:
        return sorted(files)
    return walk_files(root)


def excluded(path: str) -> bool:
    parts = set(Path(path).parts)
    if parts & EXCLUDED_PARTS:
        return True
    if path.startswith(EXCLUDED_PREFIXES):
        return True
    name = Path(path).name
    if name.startswith(".env") and name != ".env.example":
        return True
    return False


def is_first_party_source(path: str) -> bool:
    if excluded(path):
        return False
    if Path(path).suffix not in SOURCE_EXTENSIONS:
        return False
    if path.startswith(SOURCE_ROOTS):
        return True
    return "/" not in path and (
        Path(path).suffix == ".md" or Path(path).name.startswith("docker-compose.")
    )


def classify_lane(path: str) -> str:
    if path.startswith("backend/app/estimator/") or path.startswith(
        "backend/tests/parse_calibration/"
    ):
        return "estimator"
    if path.startswith("backend/"):
        return "backend"
    if path.startswith("mobile/"):
        return "mobile"
    if path.startswith("packages/"):
        return "packages"
    if path.startswith("contracts/"):
        return "contracts"
    if path.startswith("infra/") or path.startswith("searxng/") or path.startswith("docker-compose"):
        return "infra"
    if path.startswith("scripts/") or path.startswith(".github/"):
        return "scripts-ci"
    if path.startswith("docs/"):
        return "docs"
    return "other"


def classify_kind(path: str) -> str:
    file_name = Path(path).name
    if (
        "/tests/" in f"/{path}"
        or path.startswith("backend/tests/")
        or path.startswith("mobile/e2e/")
        or ".test." in file_name
        or file_name.endswith("_test.py")
    ):
        return "test"
    return "source"


def line_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    return len(text.splitlines())


def collect_source_files(root: Path) -> list[SourceFile]:
    files: list[SourceFile] = []
    for rel in repository_files(root):
        if not is_first_party_source(rel):
            continue
        absolute_path = root / rel
        if not absolute_path.is_file():
            continue
        files.append(
            SourceFile(
                path=rel,
                absolute_path=absolute_path,
                kind=classify_kind(rel),
                lane=classify_lane(rel),
                lines=line_count(absolute_path),
            )
        )
    return sorted(files, key=lambda item: item.path)


def estimator_internal_modules(root: Path) -> set[str]:
    estimator_dir = root / "backend" / "app" / "estimator"
    if not estimator_dir.is_dir():
        return set()
    return {path.stem for path in estimator_dir.glob("*.py") if path.name != "__init__.py"}


def imported_modules(node: ast.Import | ast.ImportFrom, internal_modules: set[str]) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]

    if node.level != 0 or not node.module:
        return []

    modules: list[str] = []
    for alias in node.names:
        if alias.name == "*":
            modules.append(f"{node.module}.*")
        elif node.module == "app" and alias.name in {"services", "routers"}:
            modules.append(f"app.{alias.name}")
        elif node.module in {"app.services", "app.routers"}:
            modules.append(f"{node.module}.{alias.name}")
        elif node.module == ESTIMATOR_PUBLIC_FACADE and alias.name in internal_modules:
            modules.append(f"{node.module}.{alias.name}")
        else:
            modules.append(node.module)
    return modules


def collect_boundary_imports(root: Path) -> list[BoundaryImport]:
    internal_modules = estimator_internal_modules(root)
    findings: dict[tuple[str, str, str], BoundaryImport] = {}
    for rel in repository_files(root):
        if not rel.startswith("backend/app/") or Path(rel).suffix != ".py" or excluded(rel):
            continue

        text = (root / rel).read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            fail(f"cannot parse Python source {rel}: {exc}")

        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for module in imported_modules(node, internal_modules):
                finding = classify_boundary_import(rel, module, getattr(node, "lineno", 0))
                if finding is not None:
                    existing = findings.get(finding.key)
                    if existing is None or finding.line < existing.line:
                        findings[finding.key] = finding

    return sorted(findings.values(), key=lambda item: item.key)


def classify_boundary_import(path: str, module: str, line: int) -> BoundaryImport | None:
    if path.startswith("backend/app/estimator/") and (
        module == "app.services"
        or module.startswith("app.services.")
        or module == "app.routers"
        or module.startswith("app.routers.")
    ):
        return BoundaryImport("estimator_to_backend", path, module, line)

    if path.startswith("backend/app/services/") and (
        module == "app.estimator" or module.startswith("app.estimator.")
    ):
        if module == ESTIMATOR_PUBLIC_FACADE:
            return None
        return BoundaryImport("service_to_estimator_internal", path, module, line)

    return None


def loc_advisories(source_files: list[SourceFile], baseline: dict[str, Any]) -> list[str]:
    """Advisory (warn-only) lines for first-party files over their LOC threshold.

    LOC is never blocking: over-threshold files are surfaced as one stable,
    greppable ``loc-advisory:`` line each so authors/reviewers can file refactor
    stories, but they do not contribute to the violations list.
    """
    thresholds = baseline["loc_thresholds"]
    source_threshold = int(thresholds.get("source", 0))
    test_threshold = int(thresholds.get("test", 0))
    advisories: list[str] = []

    for source_file in source_files:
        threshold = test_threshold if source_file.kind == "test" else source_threshold
        if source_file.lines <= threshold:
            continue
        advisories.append(
            f"loc-advisory: {source_file.path} — {source_file.lines} LOC "
            f"exceeds {source_file.kind} threshold {threshold}"
        )

    return advisories


def validate_boundary_imports(
    findings: list[BoundaryImport], baseline: dict[str, Any]
) -> list[str]:
    allowed = {
        (str(item["direction"]), str(item["path"]), str(item["module"]))
        for item in baseline["boundary_imports"]
    }
    violations: list[str] = []
    for finding in findings:
        if finding.key not in allowed:
            violations.append(
                f"{finding.path}:{finding.line}: {finding.direction} import "
                f"{finding.module!r} is not in scripts/code-shape-baseline.json"
            )
    return violations


def stale_boundary_baseline(findings: list[BoundaryImport], baseline: dict[str, Any]) -> list[str]:
    active = {finding.key for finding in findings}
    stale: list[str] = []
    for item in baseline["boundary_imports"]:
        key = (str(item["direction"]), str(item["path"]), str(item["module"]))
        if key not in active:
            stale.append(f"{key[1]}: {key[0]} {key[2]} is no longer present")
    return stale


def print_report(
    source_files: list[SourceFile],
    findings: list[BoundaryImport],
    advisories: list[str],
    stale_boundaries: list[str],
) -> None:
    print("code shape report")
    print("largest first-party source files:")
    largest = sorted(source_files, key=lambda item: (-item.lines, item.path))[:10]
    for item in largest:
        print(f"  {item.lines:4d} {item.kind:6s} {item.lane:10s} {item.path}")

    print("LOC advisories (warn-only, non-blocking):")
    if advisories:
        for advisory in advisories:
            print(advisory)
    else:
        print("  none")

    print("boundary exceptions:")
    if findings:
        for finding in findings:
            print(f"  {finding.direction}: {finding.path} -> {finding.module}")
    else:
        print("  none")

    if stale_boundaries:
        print("baseline shrink opportunities:")
        for item in stale_boundaries:
            print(f"  {item}")


def validate(root: Path, baseline_path: Path, *, report: bool = True) -> list[str]:
    baseline = load_baseline(baseline_path)
    source_files = collect_source_files(root)
    boundaries = collect_boundary_imports(root)
    violations = validate_boundary_imports(boundaries, baseline)

    if report:
        print_report(
            source_files,
            boundaries,
            loc_advisories(source_files, baseline),
            stale_boundary_baseline(boundaries, baseline),
        )

    return violations


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture_baseline(root: Path, boundaries: list[dict[str, str]]) -> Path:
    baseline = {
        "version": 1,
        "loc_thresholds": {"source": 3, "test": 3},
        "boundary_imports": [
            {
                "direction": item["direction"],
                "path": item["path"],
                "module": item["module"],
                "reason": "fixture baseline",
            }
            for item in boundaries
        ],
    }
    path = root / "scripts" / "code-shape-baseline.json"
    write(path, json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    return path


def run_self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="slacks-code-shape-") as tmp:
        root = Path(tmp)
        write(root / "mobile/state/Huge.ts", "\n".join(["export const x = 1;"] * 5) + "\n")
        write(
            root / "backend/app/estimator/parse.py",
            "from app import services\n",
        )
        boundary = {
            "direction": "estimator_to_backend",
            "path": "backend/app/estimator/parse.py",
            "module": "app.services",
        }

        # LOC is advisory: an over-threshold file with no baseline entry must
        # NOT fail the gate (no violations) while the boundary import is allowed.
        baseline = fixture_baseline(root, [boundary])
        if validate(root, baseline, report=False):
            fail("self-test expected an over-threshold file to be advisory (exit zero)")

        # ...and it must surface as a stable, greppable loc-advisory: line.
        advisories = loc_advisories(collect_source_files(root), load_baseline(baseline))
        expected = "loc-advisory: mobile/state/Huge.ts — 5 LOC exceeds source threshold 3"
        if expected not in advisories:
            fail(f"self-test expected advisory line {expected!r}, got {advisories!r}")
        if len([a for a in advisories if a.startswith("loc-advisory: mobile/state/Huge.ts")]) != 1:
            fail("self-test expected exactly one advisory line per over-threshold file")

        # Boundary imports remain blocking: an unbaselined crossing fails.
        baseline_without_boundary = fixture_baseline(root, [])
        violations = validate(root, baseline_without_boundary, report=False)
        if not any("estimator_to_backend" in item for item in violations):
            fail("self-test expected an unbaselined estimator-to-service import violation")

    print("code shape self-tests passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return

    violations = validate(args.root.resolve(), args.baseline.resolve(), report=not args.no_report)
    if violations:
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        raise SystemExit(1)

    print("code shape checks passed")


if __name__ == "__main__":
    main()
