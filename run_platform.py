"""Start the Jarvis Communication Platform as a standalone service.

Usage:
    python run_platform.py                  # default port 9000
    python run_platform.py --port 9001      # custom port
"""
import argparse
import uvicorn

from jarvis.app.platform.app import create_platform_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis Communication Platform")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=9000, help="Bind port (default: 9000)")
    args = parser.parse_args()

    app = create_platform_app()
    print(f"Starting Jarvis Communication Platform on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
