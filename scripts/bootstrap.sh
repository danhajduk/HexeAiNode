#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_SERVICE_NAME="hexe-ai-node-backend.service"
FRONTEND_SERVICE_NAME="hexe-ai-node-frontend.service"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
BACKEND_TEMPLATE="$ROOT_DIR/scripts/systemd/hexe-ai-node-backend.service.in"
FRONTEND_TEMPLATE="$ROOT_DIR/scripts/systemd/hexe-ai-node-frontend.service.in"
BACKEND_UNIT_PATH="$SYSTEMD_DIR/$BACKEND_SERVICE_NAME"
FRONTEND_UNIT_PATH="$SYSTEMD_DIR/$FRONTEND_SERVICE_NAME"
LEGACY_PREFIX="syn""thia-ai-node"
LEGACY_BACKEND_SERVICE_NAME="${LEGACY_PREFIX}-backend.service"
LEGACY_FRONTEND_SERVICE_NAME="${LEGACY_PREFIX}-frontend.service"

if [[ ! -f "$ROOT_DIR/scripts/stack.env" ]]; then
  echo "Missing $ROOT_DIR/scripts/stack.env"
  echo "1) cp $ROOT_DIR/scripts/stack.env.example $ROOT_DIR/scripts/stack.env"
  echo "2) set BACKEND_CMD and FRONTEND_CMD"
  exit 1
fi

if [[ ! -f "$BACKEND_TEMPLATE" || ! -f "$FRONTEND_TEMPLATE" ]]; then
  echo "Missing service templates under $ROOT_DIR/scripts/systemd/"
  exit 1
fi

render_template() {
  local template="$1"
  local output="$2"
  mkdir -p "$(dirname "$output")"
  sed \
    -e "s|__APP_DIR__|$ROOT_DIR|g" \
    "$template" >"$output"
}

render_template "$BACKEND_TEMPLATE" "$BACKEND_UNIT_PATH"
render_template "$FRONTEND_TEMPLATE" "$FRONTEND_UNIT_PATH"
chmod 644 "$BACKEND_UNIT_PATH" "$FRONTEND_UNIT_PATH"
chmod +x \
  "$ROOT_DIR/scripts/stack-control.sh" \
  "$ROOT_DIR/scripts/bootstrap.sh" \
  "$ROOT_DIR/scripts/run-from-env.sh" \
  "$ROOT_DIR/scripts/restart-stack.sh"

systemctl --user daemon-reload
systemctl --user stop "$LEGACY_BACKEND_SERVICE_NAME" "$LEGACY_FRONTEND_SERVICE_NAME" 2>/dev/null || true
systemctl --user disable "$LEGACY_BACKEND_SERVICE_NAME" "$LEGACY_FRONTEND_SERVICE_NAME" 2>/dev/null || true
systemctl --user enable "$BACKEND_SERVICE_NAME" "$FRONTEND_SERVICE_NAME"
systemctl --user restart "$BACKEND_SERVICE_NAME" "$FRONTEND_SERVICE_NAME"

echo "Installed and started user services:"
echo " - $BACKEND_SERVICE_NAME"
echo " - $FRONTEND_SERVICE_NAME"
echo "Check status with:"
echo "  systemctl --user status $BACKEND_SERVICE_NAME"
echo "  systemctl --user status $FRONTEND_SERVICE_NAME"
echo
echo "Optional (for start-at-boot without active login session):"
echo "  sudo loginctl enable-linger $USER"
