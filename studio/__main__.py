"""Start the standalone local application."""

import argparse
from pathlib import Path

from .server import create_server
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="Local OpenAPI flow studio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=Path("data/studio.sqlite3"))
    options = parser.parse_args()
    server = create_server(options.host, options.port, Store(options.db))
    print(f"API Flow Studio: http://{options.host}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
