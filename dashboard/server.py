"""
The dashboard's web server. Deliberately small and locked down:

* listens on 127.0.0.1 only (never reachable from the network)
* read-only: GET requests only, and no order placement/cancel code exists here
* every data request must carry the random access token printed at start-up
* rejects requests whose Host/Origin is not this server (blocks DNS-rebinding and cross-site reads)
* strict Content-Security-Policy; the page loads nothing from the internet
"""
import hmac
import http.server
import json
import pathlib
import secrets
import urllib.parse

from .data import Dashboard

_STATIC = pathlib.Path(__file__).parent / "static"
_FILES = {  # fixed whitelist: request paths are never joined onto the filesystem
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "SchwabdevDashboard"
    sys_version = ""

    def log_message(self, *args):  # keep the terminal quiet (and free of request details)
        pass

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in _SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict):
        self._send(status, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def _local_request(self) -> bool:
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{h}" for h in hosts}

    def do_GET(self):
        if not self._local_request():
            return self._json(403, {"error": "forbidden"})
        url = urllib.parse.urlsplit(self.path)
        if url.path in _FILES:
            name, content_type = _FILES[url.path]
            return self._send(200, (_STATIC / name).read_bytes(), content_type)
        if url.path == "/api/snapshot":
            supplied = self.headers.get("X-Dashboard-Token") or ""
            if not hmac.compare_digest(supplied.encode(), self.server.access_token.encode()):
                return self._json(401, {"error": "missing or wrong access token"})
            symbols = urllib.parse.parse_qs(url.query).get("symbols", [""])[0]
            try:
                return self._json(200, self.server.dashboard.snapshot(symbols))
            except Exception:
                return self._json(500, {"error": "could not build the snapshot"})
        return self._json(404, {"error": "not found"})

    def _read_only(self):
        self._json(405, {"error": "this dashboard is read-only"})

    do_POST = do_PUT = do_DELETE = do_PATCH = _read_only


def make_server(dashboard: Dashboard, port: int = 8765) -> http.server.ThreadingHTTPServer:
    """Build the server (bound to loopback only). Its `url` attribute is the link to open."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    server.daemon_threads = True
    server.dashboard = dashboard
    server.access_token = secrets.token_urlsafe(32)
    # The token rides in the URL fragment, which browsers never send over the network or log.
    server.url = f"http://127.0.0.1:{server.server_address[1]}/#{server.access_token}"
    return server
