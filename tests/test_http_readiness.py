import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from scripts.check_http_readiness import check_endpoint


@pytest.fixture(scope="module")
def probe_server():
    responses = {
        "/health": (200, "application/json", json.dumps({"status": "healthy"})),
        "/ready": (200, "application/json", json.dumps({"status": "ready", "checks": {"database": "ok", "redis": "ok"}})),
        "/html": (200, "text/html", '<html><div id="app"></div></html>'),
        "/old-ready": (200, "application/json", json.dumps({"status": "ready"})),
        "/redis-down": (200, "application/json", json.dumps({"status": "ready", "checks": {"database": "ok", "redis": "unavailable"}})),
        "/database-missing": (200, "application/json", json.dumps({"status": "ready", "checks": {"redis": "ok"}})),
        "/unavailable": (503, "application/json", json.dumps({"status": "not_ready"})),
        "/malformed": (200, "application/json", "invalid json"),
        "/list": (200, "application/json", "[]"),
        "/large": (200, "application/json", " " * 65537),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, content_type, body = responses[self.path]
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.mark.parametrize("path,ready,expected", [
    ("/health", False, True),
    ("/ready", True, True),
    ("/html", False, False),
    ("/html", True, False),
    ("/old-ready", True, False),
    ("/redis-down", True, False),
    ("/database-missing", True, False),
    ("/unavailable", True, False),
    ("/malformed", True, False),
    ("/list", True, False),
    ("/large", True, False),
])
def test_probe_validates_actual_http_contract(probe_server, path, ready, expected):
    assert check_endpoint(probe_server + path, ready=ready) is expected
