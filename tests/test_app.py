"""Unit tests for every endpoint. Run with:  pytest"""

import socket

import pytest

from app.main import create_app


@pytest.fixture()
def client():
    """A fixture is reusable setup. Flask's test client sends fake requests
    to the app in memory, with no real server or network needed."""
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_home_returns_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert b"Hello from a containerized Flask app!" in response.data


def test_health_returns_ok_json(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.is_json
    assert response.get_json() == {"status": "ok"}


def test_info_uses_version_from_env(client, monkeypatch):
    # monkeypatch temporarily sets an environment variable for just this test.
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    response = client.get("/api/info")
    assert response.status_code == 200
    data = response.get_json()
    assert data["version"] == "1.2.3"
    assert data["hostname"] == socket.gethostname()


def test_info_falls_back_to_default_version(client, monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    response = client.get("/api/info")
    assert response.get_json()["version"] == "0.0.0-dev"


def test_unknown_route_returns_404(client):
    assert client.get("/does-not-exist").status_code == 404
