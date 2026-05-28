#!/usr/bin/env bash
set -euo pipefail

COMPONENT="${1:-}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/scripts/stack.env"

if [[ -z "$COMPONENT" ]]; then
  echo "Usage: $0 {backend|frontend}"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

case "$COMPONENT" in
  backend)
    CMD="${BACKEND_CMD:-}"
    ;;
  frontend)
    CMD="${FRONTEND_CMD:-}"
    ;;
  *)
    echo "Unknown component: $COMPONENT"
    exit 1
    ;;
esac

if [[ -z "$CMD" ]]; then
  echo "Command for $COMPONENT is empty in $ENV_FILE"
  exit 1
fi

cd "${APP_DIR:-$ROOT_DIR}"
exec /usr/bin/env bash -lc "$CMD"
