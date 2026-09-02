#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  echo "Usage: $0 <socket-dir> <uid> <gid> <helper-image>" >&2
  exit 2
fi

SOCKET_DIR="$1"
RUNTIME_UID="$2"
RUNTIME_GID="$3"
HELPER_IMAGE="$4"
DOCKER_BIN="${DOCKER_BIN:-docker}"

if [[ "$SOCKET_DIR" != /* || "$SOCKET_DIR" == "/" ]]; then
  echo "Socket directory must be an absolute, non-root path: $SOCKET_DIR" >&2
  exit 2
fi
if [[ ! "$RUNTIME_UID" =~ ^[0-9]+$ || ! "$RUNTIME_GID" =~ ^[0-9]+$ ]]; then
  echo "Runtime UID and GID must be numeric" >&2
  exit 2
fi

mkdir -p "$SOCKET_DIR"
if [[ -w "$SOCKET_DIR" ]]; then
  exit 0
fi

# Docker bind mounts retain host ownership. Use the already-configured runtime
# image as a root helper so the non-root llama.cpp process and host-side health
# wrapper can create sockets even when another root container created the
# shared /run directory first.
"$DOCKER_BIN" run --rm \
  --user 0:0 \
  --entrypoint /bin/sh \
  --mount "type=bind,src=$SOCKET_DIR,dst=/socket-dir" \
  "$HELPER_IMAGE" \
  -c 'chown "$1:$2" /socket-dir && chmod 0770 /socket-dir' sh "$RUNTIME_UID" "$RUNTIME_GID"

if [[ ! -w "$SOCKET_DIR" ]]; then
  echo "Socket directory is still not writable after ownership repair: $SOCKET_DIR" >&2
  exit 1
fi
