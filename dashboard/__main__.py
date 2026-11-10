"""
Run the dashboard:   python -m dashboard            (your Schwab account)
                     python -m dashboard --demo     (made-up data, nothing to set up)
                     python -m dashboard --setup    (save your Schwab app key/secret once)
"""
import argparse
import getpass
import logging
import os
import sys
import webbrowser

from .data import Dashboard, clean_symbols
from .server import make_server


def _setup() -> int:
    import schwabdev
    print("Saving your Schwab developer app credentials to ~/.schwabdev/env.json (readable only by you).")
    print("Input is hidden while you type or paste.")
    app_key = getpass.getpass("App key: ").strip()
    app_secret = getpass.getpass("App secret: ").strip()
    callback_url = input("Callback URL [https://127.0.0.1]: ").strip() or "https://127.0.0.1"
    if not app_key or not app_secret:
        print("Nothing saved: app key and app secret are both required.")
        return 1
    schwabdev.save_env_global(app_key, app_secret, callback_url)
    print("Saved. Start the dashboard with:  python -m dashboard")
    return 0


def _live_client(tokens_db: str):
    import schwabdev
    # Credentials come from the environment or ~/.schwabdev/env.json - never from the command line.
    return schwabdev.Client(
        app_key=os.environ.get("SCHWAB_APP_KEY"),
        app_secret=os.environ.get("SCHWAB_APP_SECRET"),
        callback_url=os.environ.get("SCHWAB_CALLBACK_URL") or "https://127.0.0.1",
        tokens_db=tokens_db,
        encryption=os.environ.get("SCHWABDEV_ENCRYPTION_KEY") or None,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dashboard", description="Local read-only Schwab dashboard.")
    parser.add_argument("--demo", action="store_true", help="show made-up data (no Schwab connection)")
    parser.add_argument("--setup", action="store_true", help="save your Schwab app key and secret, then exit")
    parser.add_argument("--port", type=int, default=8765, help="local port (default 8765)")
    parser.add_argument("--symbols", default="SPY,QQQ,AAPL,MSFT,NVDA", help="starting watchlist, comma separated")
    parser.add_argument("--tokens-db", default="~/.schwabdev/tokens.db", help="where sign-in tokens are stored")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = parser.parse_args(argv)

    if args.setup:
        return _setup()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    if args.demo:
        from .demo import DemoClient
        client, mode = DemoClient(), "demo"
    else:
        try:
            client, mode = _live_client(args.tokens_db), "live"
        except ValueError as e:
            print(f"Could not connect: {e}\nRun  python -m dashboard --setup  first, or try  python -m dashboard --demo")
            return 1

    try:
        server = make_server(Dashboard(client, mode=mode), args.port)
    except OSError as e:
        print(f"Could not start on port {args.port} ({e}). Try another one with --port.")
        return 1
    symbols = clean_symbols(args.symbols)
    link = server.url + ("&" + ",".join(symbols) if symbols else "")
    print(f"Dashboard ({mode}) is running. Open this private link:\n\n  {link}\n\nPress Ctrl+C to stop.")
    if not args.no_browser:
        webbrowser.open(link)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
