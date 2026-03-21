#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_CORE_REPO="${REPO_ROOT}/../Synthia"
CORE_REPO="${1:-${DEFAULT_CORE_REPO}}"
CORE_DOCS="${CORE_REPO}/docs"
TARGET_LINK="${REPO_ROOT}/docs/core"

if [[ ! -d "${CORE_DOCS}" ]]; then
  printf 'Core docs directory not found: %s\n' "${CORE_DOCS}" >&2
  printf 'Pass the Hexe Core repo path explicitly, for example:\n' >&2
  printf '  %s /path/to/SynthiaCore\n' "${0}" >&2
  exit 1
fi

if [[ -e "${TARGET_LINK}" && ! -L "${TARGET_LINK}" ]]; then
  printf 'Refusing to replace non-symlink path: %s\n' "${TARGET_LINK}" >&2
  exit 1
fi

if [[ -L "${TARGET_LINK}" && ! -d "${TARGET_LINK}" ]]; then
  rm -f "${TARGET_LINK}"
fi

ln -sfn "${CORE_DOCS}" "${TARGET_LINK}"
printf 'Linked %s -> %s\n' "${TARGET_LINK}" "${CORE_DOCS}"
printf 'This symlink is local-only and is ignored by git.\n'
