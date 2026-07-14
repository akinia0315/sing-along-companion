#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Run this audit from an initialized Git work tree." >&2
  exit 2
fi

for forbidden in '.env' 'data/' 'uploads/' 'recordings/' 'screenshots/' 'cache/'; do
  if git ls-files --error-unmatch "$forbidden" >/dev/null 2>&1; then
    echo "Refusing tracked private/runtime path: $forbidden" >&2
    exit 1
  fi
done

private_marker='BEGIN (RSA|EC|OPENSSH) PRIVATE ''KEY'
github_marker='github''_pat_'
legacy_marker='gh''p_'
service_marker='s''k-'
matches="$(git grep -I -l -E "(${private_marker}|${github_marker}[A-Za-z0-9_]+|${legacy_marker}[A-Za-z0-9]+|${service_marker}[A-Za-z0-9_-]{20,})" || true)"
if [[ -n "$matches" ]]; then
  echo "Potential secret marker found in tracked file name(s):" >&2
  printf '%s\n' "$matches" >&2
  exit 1
fi

echo "Public audit passed: no tracked runtime-data paths or common secret markers found."
