"""
Tests for the local dashboard: data shaping, privacy (masked accounts), and the web
server's access controls. Uses the demo client; no network beyond 127.0.0.1.
"""
import http.client
import json
import threading

import pytest

from dashboard import data
from dashboard.demo import DemoClient
from dashboard.server import make_server


@pytest.fixture
def server():
    srv = make_server(data.Dashboard(DemoClient(), mode="demo"), port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _get(srv, path, method="GET", token=None, host=None, origin=None):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if token:
        headers["X-Dashboard-Token"] = token
    if origin:
        headers["Origin"] = origin
    conn.request(method, path, headers=headers)
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response, body


class TestShaping:
    def test_symbols_are_cleaned(self):
        assert data.clean_symbols("aapl, msft ,AAPL,<script>,") == ["AAPL", "MSFT"]
        assert len(data.clean_symbols(",".join(f"S{i}" for i in range(100)))) == data.MAX_SYMBOLS

    def test_account_numbers_are_masked(self):
        assert data.mask_account("12345678") == "…5678"
        snap = data.Dashboard(DemoClient(), mode="demo").snapshot("SPY")
        text = json.dumps(snap)
        assert "10004821" not in text and "20007316" not in text
        assert snap["accounts"][0]["label"] == "…4821"

    def test_snapshot_contents(self):
        snap = data.Dashboard(DemoClient(), mode="demo").snapshot("SPY,NOPE")
        assert snap["errors"] == [] and snap["connection"]["ok"] is True
        assert [len(a["positions"]) for a in snap["accounts"]] == [5, 2]
        assert [q["found"] for q in snap["quotes"]] == [True, False]
        assert sum(o["open"] for o in snap["orders"]) == 1
        assert snap["orders"][0]["entered"] >= snap["orders"][-1]["entered"]  # newest first
        assert len(snap["activity"]) == 4 and all(a["ok"] for a in snap["activity"])

    def test_malformed_responses_do_not_crash(self):
        assert data.shape_accounts({"unexpected": 1}) == []
        assert data.shape_accounts([{"securitiesAccount": {"positions": [{}]}}])[0]["positions"][0]["symbol"] == "?"
        assert data.shape_orders(None) == [] and data.shape_market_hours([]) == []
        assert data.shape_quotes("nope", ["SPY"]) == [{"symbol": "SPY", "found": False}]

    def test_failed_section_is_reported_not_fatal(self):
        class Broken(DemoClient):
            def account_details_all(self, fields=None):
                raise ConnectionError("secret-detail")
        snap = data.Dashboard(Broken(), mode="demo").snapshot("SPY")
        assert any(e.startswith("Accounts and positions") for e in snap["errors"])
        assert "secret-detail" not in json.dumps(snap)
        assert snap["quotes"] and snap["orders"]

    def test_expired_sign_in_makes_no_api_calls(self):
        class Expired(DemoClient):
            class tokens:
                @staticmethod
                def status():
                    return {"access_token_seconds_left": -5, "refresh_token_seconds_left": 60, "encrypted": False}

            def account_details_all(self, fields=None):
                raise AssertionError("must not call the API when sign-in has expired")
        snap = data.Dashboard(Expired(), mode="live").snapshot("SPY")
        assert snap["connection"]["reauth_required"] is True and snap["accounts"] == []
        assert snap["activity"] == []

    def test_snapshot_is_cached(self):
        calls = []

        class Counting(DemoClient):
            def quotes(self, symbols, fields=None, indicative=False):
                calls.append(symbols)
                return super().quotes(symbols)
        board = data.Dashboard(Counting(), mode="demo")
        board.snapshot("SPY")
        board.snapshot("SPY")
        assert len(calls) == 1


class TestServer:
    def test_binds_to_loopback_only(self, server):
        assert server.server_address[0] == "127.0.0.1"

    def test_page_and_security_headers(self, server):
        response, body = _get(server, "/")
        assert response.status == 200 and b"Schwab dashboard" in body
        assert "default-src 'none'" in response.getheader("Content-Security-Policy")
        assert response.getheader("X-Frame-Options") == "DENY"
        assert response.getheader("Cache-Control") == "no-store"

    def test_snapshot_requires_token(self, server):
        assert _get(server, "/api/snapshot")[0].status == 401
        assert _get(server, "/api/snapshot", token="wrong")[0].status == 401
        response, body = _get(server, "/api/snapshot?symbols=SPY", token=server.access_token)
        assert response.status == 200 and json.loads(body)["accounts"]

    def test_rejects_foreign_host_and_origin(self, server):
        token = server.access_token
        assert _get(server, "/api/snapshot", token=token, host="evil.example")[0].status == 403
        assert _get(server, "/", host="evil.example:80")[0].status == 403
        assert _get(server, "/api/snapshot", token=token, origin="https://evil.example")[0].status == 403

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_is_read_only(self, server, method):
        assert _get(server, "/api/snapshot", method=method, token=server.access_token)[0].status == 405

    @pytest.mark.parametrize("path", ["/server.py", "/../server.py", "/static/../data.py", "/%2e%2e/data.py", "/api/"])
    def test_no_other_files_are_served(self, server, path):
        assert _get(server, path)[0].status == 404
