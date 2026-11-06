"""Exercise the release check against real HTTP responses and failure cases."""

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from scripts.smoke_test import check_app


@pytest.fixture()
def endpoint():
    state = {
        "health": {"status": "ok"},
        "info": {"service": "docker-cicd-app", "version": "test-sha", "hostname": "test-host"},
        "delay": 0.0,
        "health_status": 200,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(state["delay"])
            value = state["health"] if self.path == "/health" else state["info"]
            status = state["health_status"] if self.path == "/health" else 200
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(json.dumps(value).encode())
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_accepts_the_expected_release(endpoint):
    url, state = endpoint
    assert check_app(url, "test-sha") == state["info"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("service", "another-app", "service identity"),
        ("version", "old-sha", "Version mismatch"),
        ("hostname", "", "hostname"),
    ],
)
def test_rejects_wrong_release_metadata(endpoint, field, value, message):
    url, state = endpoint
    state["info"][field] = value
    with pytest.raises(ValueError, match=message):
        check_app(url, "test-sha")


def test_rejects_a_misleading_health_response(endpoint):
    url, state = endpoint
    state["health"] = {"status": "broken"}
    with pytest.raises(ValueError, match="health response"):
        check_app(url, "test-sha")


def test_startup_failure_has_a_deadline(endpoint):
    url, state = endpoint
    state["health_status"] = 503
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        check_app(url, "test-sha", timeout=0.1)
    assert time.monotonic() - started < 2


def test_unresponsive_request_is_bounded(endpoint):
    url, state = endpoint
    state["delay"] = 0.5
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        check_app(url, "test-sha", timeout=0.1)
    assert time.monotonic() - started < 2


def test_cli_reports_failure_for_the_wrong_commit(endpoint):
    url, _state = endpoint
    script = Path(__file__).resolve().parents[1] / "scripts" / "smoke_test.py"
    result = subprocess.run(
        [sys.executable, str(script), "--base-url", url, "--expected-version", "wrong-sha"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert "Version mismatch" in result.stderr
