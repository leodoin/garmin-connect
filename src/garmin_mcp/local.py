"""Private stdio entry point for the OpenAI tunnel (no listening MCP port)."""
import os
from pathlib import Path

from dotenv import load_dotenv

from .history import History
from .server import create_server

ROOT = Path(__file__).resolve().parents[2]


def main():
    os.umask(0o077)
    load_dotenv(ROOT / ".env")
    token_dir = Path(os.getenv("GARMIN_TOKEN_DIR", str(ROOT / ".data/garmin")))
    if not token_dir.is_absolute():
        token_dir = ROOT / token_dir
    create_server(History(str(token_dir))).run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
