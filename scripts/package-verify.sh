#!/usr/bin/env bash
# Run a package's verification hook when the package provides one.
#
# A package opts into root `make verify` by adding an executable `verify.sh` at
# its package root. Until that hook exists, this is a no-op so the monorepo
# scaffold verifies cleanly from a fresh checkout, before any package toolchain
# is installed. See docs/architecture/repo-layout.md.
set -euo pipefail

pkg="${1:?usage: package-verify.sh <package-dir>}"
root="$(cd "$(dirname "$0")/.." && pwd)"
hook="$root/$pkg/verify.sh"

if [[ -x "$hook" ]]; then
  echo "==> verify $pkg"
  ( cd "$root/$pkg" && ./verify.sh )
else
  echo "==> skip $pkg (no verify.sh yet)"
fi
