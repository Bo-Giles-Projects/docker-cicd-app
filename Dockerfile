# syntax=docker/dockerfile:1

# ============================================================================
# Stage 1: "builder". Installs dependencies into a virtual environment.
# Everything in this stage is thrown away except what we copy out of it.
# ============================================================================
FROM python:3.13-slim AS builder

# Don't write .pyc files, and don't buffer output (so logs appear immediately).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create a virtual environment in /opt/venv. Copying this one folder into the
# final image is the easiest way to move installed packages between stages.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Copy ONLY the requirements file first. Docker caches each step ("layer"), so as
# long as requirements.txt doesn't change, this slow install step is reused
# even when our source code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -m pip uninstall --yes pip

# ============================================================================
# Stage 2: "runtime". The small image we actually ship.
# It has no pip cache and no build leftovers, just Python + the venv + our code.
# ============================================================================
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# A build argument lets CI stamp the version into the image: --build-arg APP_VERSION=...
# Turning it into an ENV makes it readable by the app at runtime (os.environ).
ARG APP_VERSION=0.0.0-dev
ENV APP_VERSION=${APP_VERSION}

# Security: create an unprivileged user so the app does NOT run as root.
# If an attacker breaks into the app, they get far fewer permissions.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Bring in the installed packages from the builder stage, then our code.
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app/ ./app/

# Package installers are build tools; the running app does not need them.
# Remove the base image's pip and bundled installer wheels as well.
RUN /usr/local/bin/python -m pip uninstall --yes pip \
 && /usr/local/bin/python -c "import ensurepip, shutil; from pathlib import Path; shutil.rmtree(Path(ensurepip.__file__).parent)"

# Switch to the unprivileged user for everything from here on.
USER app

# Documentation: the app listens on port 8000. (You still publish it with -p.)
EXPOSE 8000

# Docker runs this command periodically. If it fails repeatedly, the container
# is marked "unhealthy". We use Python's standard library because the slim image
# doesn't include curl.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# Flask's built-in server is only for development. gunicorn is a production-grade
# WSGI server. "app.main:app" = module app/main.py, variable "app".
# 0.0.0.0 means "accept connections from outside the container".
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "app.main:app"]
