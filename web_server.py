#!/usr/bin/env python3
"""
Simple static file server for remotely accessing local HTML assets.

Usage:
    python web_server.py --directory public --host 0.0.0.0 --port 8000

The script uses Python's standard-library HTTP server, so you don't need any
additional dependencies. Point the --directory flag at the folder that
contains your HTML (defaults to ./public). Binding to 0.0.0.0 makes the server
reachable from other machines on the network as long as firewall rules allow
it.
"""

from __future__ import annotations

import argparse
import socket
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve HTML (or any static assets) over HTTP."
    )
    parser.add_argument(
        "--directory",
        "-d",
        type=Path,
        default=Path("public"),
        help="Directory containing HTML/CSS/JS files (default: ./public).",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Interface/IP to bind (default: 0.0.0.0 for all interfaces).",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    root = args.directory.expanduser().resolve()
    if not root.exists():
        raise SystemExit(
            f"[error] directory '{root}' does not exist. Create it or point "
            "the server at the folder that holds your HTML files."
        )
    if not root.is_dir():
        raise SystemExit(f"[error] '{root}' is not a directory.")

    handler_cls = partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)

    print(
        f"[info] Serving {root} at http://{args.host}:{args.port}\n"
        "Press Ctrl+C to stop."
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[info] Shutting down...")
    except OSError as exc:
        if isinstance(exc, socket.error):
            print(f"[error] Socket error: {exc}", file=sys.stderr)
        else:
            print(f"[error] {exc}", file=sys.stderr)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
