"""A deliberately tiny Flask web app.

The app itself is NOT the point of this project. It only exists so there is
something real to test, containerize, and ship through a CI/CD pipeline.

Endpoints:
    GET /            -> a simple HTML homepage
    GET /health      -> JSON status, used by Docker HEALTHCHECK and the CI smoke test
    GET /api/info    -> JSON with the service name, app version, and container hostname
"""

import os
import socket

from flask import Flask, jsonify


# The "application factory" pattern: a function that builds and returns the app.
# It makes testing easier because each test can get its own fresh app instance.
def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def home():
        # Returning a plain string makes Flask send it back as an HTML page.
        return (
            "<!doctype html>"
            "<html lang='en'><head><meta charset='utf-8'><title>Docker CI/CD Demo</title></head>"
            "<body>"
            "<h1>Hello from a containerized Flask app!</h1>"
            "<p>Built and shipped by a GitHub Actions pipeline.</p>"
            "<p>Try <a href='/health'>/health</a> or <a href='/api/info'>/api/info</a>.</p>"
            "</body></html>"
        )

    @app.get("/health")
    def health():
        # Monitoring tools, Docker, and Kubernetes call an endpoint like this to ask
        # "are you alive?". Returning 200 with {"status": "ok"} means yes.
        return jsonify(status="ok")

    @app.get("/api/info")
    def info():
        # APP_VERSION is read from an environment variable, so the SAME image code can
        # report different versions without editing the source. The fallback is used
        # when the variable isn't set (for example, when running locally).
        return jsonify(
            service="docker-cicd-app",
            version=os.environ.get("APP_VERSION", "0.0.0-dev"),
            # Inside a container, the hostname is the container ID, which is handy for
            # seeing WHICH container answered when you run several copies.
            hostname=socket.gethostname(),
        )

    return app


# gunicorn looks for this module-level name: "app.main:app" means
# "in the file app/main.py, use the variable called app".
app = create_app()
