#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import select
import socket
import socketserver
from pathlib import Path


class UnixSocketTcpBridgeHandler(socketserver.BaseRequestHandler):
    unix_socket_path = ""

    def handle(self) -> None:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            upstream.connect(self.unix_socket_path)
            self._bridge(self.request, upstream)
        finally:
            upstream.close()

    @staticmethod
    def _bridge(client: socket.socket, upstream: socket.socket) -> None:
        sockets = [client, upstream]
        while True:
            readable, _, failed = select.select(sockets, [], sockets)
            if failed:
                return
            for source in readable:
                target = upstream if source is client else client
                data = source.recv(65536)
                if not data:
                    return
                target.sendall(data)


class ThreadedTcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge local TCP connections to a Unix-domain socket.")
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--pid-file", default="")
    args = parser.parse_args()

    socket_path = Path(args.socket_path)
    if not socket_path.exists():
        raise SystemExit(f"socket path does not exist: {socket_path}")
    UnixSocketTcpBridgeHandler.unix_socket_path = str(socket_path)

    pid_file = Path(args.pid_file) if args.pid_file else None
    if pid_file is not None:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")

    with ThreadedTcpServer((str(args.host), int(args.port)), UnixSocketTcpBridgeHandler) as server:
        try:
            server.serve_forever()
        finally:
            if pid_file is not None:
                try:
                    pid_file.unlink()
                except FileNotFoundError:
                    pass


if __name__ == "__main__":
    main()
