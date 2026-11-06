# LEARNING.md: How This Project Works, Line by Line

This guide explains every file in plain language. Read it alongside the code. The goal is for you to be able to explain any line in an interview.

---

## Big-picture concepts first

| Term | Plain-language meaning |
|---|---|
| **Container** | A running, isolated process that carries its own copy of everything it needs (Python, libraries, your code). It behaves the same on any machine with Docker. |
| **Image** | The read-only *template* a container is started from. Image : container is like recipe : meal, or class : object. |
| **Dockerfile** | A text recipe of steps that builds an image. |
| **Layer** | Each Dockerfile instruction creates a cached layer. Unchanged layers are reused, so rebuilds are fast. |
| **Registry** | A server that stores images (Docker Hub, GitHub Container Registry `ghcr.io`, AWS ECR). |
| **Tag** | A label on an image version, like `latest` or `sha-<commit>`. |
| **CI (Continuous Integration)** | Automatically building and testing every change so problems show up immediately. |
| **CD (Continuous Delivery/Deployment)** | Automatically packaging and shipping (here: publishing) what passed CI. |
| **Workflow / Job / Step** | In GitHub Actions: a *workflow* is a YAML file; it contains *jobs* (each on a fresh virtual machine called a *runner*); each job has ordered *steps*. |
| **Action** | A reusable step someone else wrote, used with `uses:`, for example `actions/checkout`. |
| **Smoke test** | A quick "does it turn on at all?" check on the finished artifact. |
| **WSGI server** | A program (gunicorn) that talks HTTP to the world and hands requests to a Python web app. |

**The pipeline in one sentence:** you `git push` → GitHub starts a runner → it lints and tests the code → builds the image → runs it and checks `/health` → (on `main`) publishes it to GHCR.

---

## `app/main.py`: the web app

```python
import os
import socket
from flask import Flask, jsonify
```
`os` reads environment variables, `socket` gets the machine's hostname, `Flask` is the web framework, and `jsonify` turns Python data into a JSON HTTP response.

```python
def create_app() -> Flask:
    app = Flask(__name__)
```
An **application factory**: a function that builds the app. Each test can call it to get a clean, separate app. `__name__` tells Flask where to find the app's files.

```python
    @app.get("/")
    def home():
        return "<!doctype html>..."
```
A **decorator** (`@app.get("/")`) registers the function below it to answer `GET` requests to `/`. Returning a string makes Flask send HTML.

```python
    @app.get("/health")
    def health():
        return jsonify(status="ok")
```
The **health endpoint**. Docker's `HEALTHCHECK`, our CI smoke test, and (later) Kubernetes probes call it to ask "are you alive?". It returns `{"status": "ok"}` with HTTP 200.

```python
    @app.get("/api/info")
    def info():
        return jsonify(
            service="docker-cicd-app",
            version=os.environ.get("APP_VERSION", "0.0.0-dev"),
            hostname=socket.gethostname(),
        )
```
- `os.environ.get("APP_VERSION", "0.0.0-dev")` reads an **environment variable**, with a default if it isn't set. This is the standard way to configure containers: the *same image* can behave differently depending on its environment ("12-factor app" configuration).
- Inside a container, `gethostname()` returns the container ID. If you run three copies, this shows which one replied.

```python
app = create_app()
```
Creates the app at import time. gunicorn is told `app.main:app`, meaning "file `app/main.py`, variable `app`".

---

## `tests/test_app.py`: unit tests

- **pytest** finds files named `test_*.py` and runs functions named `test_*`. A plain `assert` is all you need; pytest shows a detailed diff if it fails.
- `@pytest.fixture()` defines reusable setup. Any test that lists `client` as a parameter automatically receives it.
- `app.test_client()` is Flask's fake browser. It calls the app **in memory** with no server or network, so tests are fast.
- `monkeypatch.setenv(...)` / `delenv(...)` change an environment variable for **one test only** and restore it afterward, so tests don't affect each other.
- The API tests cover homepage HTML, `/health` JSON, `/api/info` identity and version, the default version, and unknown routes.
- `tests/test_smoke_test.py` exercises the release checker against a local HTTP server, including wrong service/version, invalid health, startup failures, request timeouts, and a failing command-line exit status.

---

## `requirements.txt` and `requirements-dev.txt`

- Direct dependency versions are **pinned** with `==`. This does not lock their transitive dependencies. The Docker base tag can also change. A full dependency lock and base-image digest would provide stronger repeatability.
- `requirements.txt` holds what the app needs to **run**. `requirements-dev.txt` adds tools for **development/CI** (pytest, ruff) and starts with `-r requirements.txt` to include the runtime ones. The Docker image installs only the first file, so it's smaller and has fewer things to attack.
- `.github/dependabot.yml` proposes weekly updates to Python packages, action versions, and the Docker base image after the configuration reaches the default branch. Updates still need review and CI checks.

## `pyproject.toml`

Central settings for tools. `[tool.ruff]` sets line length and which rule families to check (`E`/`W` style, `F` unused code, `I` import order, `B` likely bugs, `UP` outdated syntax). `[tool.pytest.ini_options]` tells pytest to look in `tests/`. Keeping this in the repo means your laptop and CI use identical rules.

---

## `Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1
```
Selects the current stable Dockerfile syntax.

### Stage 1: builder

```dockerfile
FROM python:3.13-slim AS builder
```
Start from the official Python image. **slim** is a smaller Debian-based variant than the full image. `AS builder` names this stage.

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
```
Don't create `.pyc` cache files, and print logs immediately instead of buffering them. The second one matters in containers, so `docker logs` is live.

```dockerfile
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
```
Creates a virtual environment and puts it first on `PATH`, so `pip` and `python` use it. All installed packages end up in one folder that's easy to copy to the next stage.

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```
Copy **only** the requirements file, then install. Because Docker caches layers, this slow step is skipped whenever `requirements.txt` hasn't changed, even if your code did. This is the single most common Dockerfile optimization. `--no-cache-dir` stops pip from storing downloaded files.

### Stage 2: runtime

```dockerfile
FROM python:3.13-slim AS runtime
```
A **fresh** image. Nothing from the builder stage is here unless we copy it in. That's the point of **multi-stage builds**: build tools and caches stay behind, so the shipped image is smaller and has less attack surface. (In this project the saving is modest because there's no compiler step. The pattern matters more with compiled dependencies.)

```dockerfile
ARG APP_VERSION=0.0.0-dev
ENV APP_VERSION=${APP_VERSION}
```
`ARG` is a value passed **at build time** (`--build-arg`). Copying it into an `ENV` makes it available to the running app. CI passes the commit SHA, so `/api/info` shows exactly which commit the image was built from.

```dockerfile
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
```
Creates a system user and group with no home folder and no login shell. Fixed IDs (10001) make permissions predictable, for example later in Kubernetes.

```dockerfile
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app/ ./app/
```
Set the working folder, copy the finished virtual environment out of the builder stage, then copy our code owned by the `app` user. (`.dockerignore` keeps tests, docs, and junk out.)

```dockerfile
USER app
```
Everything after this, including the running app, uses the unprivileged user. **Running as root inside a container is a common security mistake.**

```dockerfile
EXPOSE 8000
```
Documentation that the app listens on 8000. It does *not* open the port. `-p 8000:8000` does that.

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
```
Every 30 seconds Docker runs this command. If it exits non-zero 3 times in a row, the container shows as `unhealthy`. `start-period` gives the app a few seconds to boot. We use Python's built-in `urllib` because slim images don't include `curl`, and installing it would add size. (`urlopen` raises an error on HTTP 4xx/5xx, which makes the command fail as desired.)

```dockerfile
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "app.main:app"]
```
- Flask's built-in server is for development only. **gunicorn** is a production WSGI server.
- `0.0.0.0` means listen on all network interfaces. If you used `127.0.0.1`, nothing outside the container could reach it.
- `--workers 2` runs two worker processes. `--access-logfile -` sends request logs to stdout so `docker logs` shows them.
- The **list ("exec") form** runs gunicorn directly as the main process, so it receives stop signals correctly.

## `.dockerignore`

Lists files Docker should not send to the builder: `.git`, virtual environments, caches, tests, docs, `.env`. Benefits: faster builds, smaller context, and secrets can't accidentally be copied into an image layer.

## `docker-compose.yml`

Compose describes how to run containers in a single file, so you type `docker compose up --build` instead of long `docker build` and `docker run` commands. `build` says where the Dockerfile is and passes the build arg; `ports: "8000:8000"` maps *host port : container port*; `environment` sets a runtime variable (it overrides the baked-in value); `restart: unless-stopped` restarts it after crashes.

---

## `.github/workflows/ci.yml`: the pipeline

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```
**Triggers.** Run on pushes to `main` and on pull requests that target `main`.

```yaml
permissions:
  contents: read
```
**Least privilege.** The automatic `GITHUB_TOKEN` gets read-only access to the repo for the whole workflow. A job can request more only if it needs it.

```yaml
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```
If you push again before the last run finishes, the older run for that branch is cancelled, which saves time on a stale run.

```yaml
env:
  IMAGE_NAME: ghcr.io/${{ github.repository }}
```
A workflow-level variable. `${{ ... }}` is GitHub's expression syntax; `github.repository` is `owner/repo`.

### Job `test`

```yaml
runs-on: ubuntu-latest
```
Run on a GitHub-hosted Linux virtual machine that is created fresh and thrown away afterward.

| Step | Explanation |
|---|---|
| `actions/checkout@v7` | Downloads your repository code onto the runner. Without it the runner has an empty folder. |
| `actions/setup-python@v7` | Installs Python 3.13. `cache: pip` saves downloaded packages between runs. |
| `pip install -r requirements-dev.txt` | Installs the app dependencies plus pytest and ruff. |
| `ruff check .` | Lints the code: unused imports, likely bugs, import order. A non-zero exit code fails the step. |
| `ruff format --check .` | Verifies formatting, without changing files. |
| `pytest -v` | Runs the API tests and release-check success/failure tests. |

**How failure works:** if any step's command exits with a non-zero code, the step fails, the job stops, and the run turns red. That's all "CI failing" means.

### Job `docker`

```yaml
needs: test
permissions:
  contents: read
  packages: write
```
- `needs: test`: this job waits for `test` and is skipped if it fails. You never build from broken code.
- This job's `permissions` replace the top-level ones. `packages: write` is what allows pushing to GHCR with `GITHUB_TOKEN`. Only this job gets it.

| Step | Explanation |
|---|---|
| `docker/setup-buildx-action@v4` | Sets up **Buildx**, Docker's modern builder, which supports the layer cache used below. |
| `docker/metadata-action@v6` | Computes image tags and labels. `type=sha,format=long` makes `sha-<full commit SHA>`; `type=raw,value=latest,enable={{is_default_branch}}` adds `latest` only on the default branch. It also lowercases the image name, since registries require lowercase. |
| `docker/build-push-action@v7` | Builds the image once, applying its labels and commit version. `load: true` loads it into local Docker as `smoke-test:ci`; `push: false` keeps publication separate. GitHub Actions caching speeds up later runs. |
| **Smoke test** | Starts the container on loopback port 8000 and runs `scripts/smoke_test.py`. It waits for readiness, then checks health JSON and service, expected commit version, and hostname. Startup retries share a 30-second budget; each request has at most a two-second socket timeout. CI also imposes a two-minute step limit. Failures return a nonzero exit status and container logs are shown. |
| **Trivy scan** | Reports high/critical vulnerabilities with available fixes. `exit-code: "0"` makes findings informational, and `continue-on-error: true` also permits scanner errors. Inspect the step logs; a tool error is not a clean scan. |
| `docker/login-action@v4` | Logs in to `ghcr.io` with `github.actor` (who triggered the run) and `secrets.GITHUB_TOKEN`. No password is stored anywhere: GitHub generates the token for each run and it expires when the job ends. |
| **Push the tested image** | `docker tag` assigns the generated GHCR tags to the local tested image. The workflow checks that their image IDs match before `docker push`. There is no rebuild. |
| **Cleanup** | `if: always()` removes the smoke-test container after success or failure. |

```yaml
if: github.event_name == 'push' && github.ref == 'refs/heads/main'
```
On the login and push steps: run only when the event is a **push** (not a pull request) **and** the branch is `main`. This is how the same workflow tests PRs without publishing from them.

**Why publish the same image?** A second independent build could resolve changed upstream inputs. Retagging and pushing the already-tested local image preserves the tested image content. This is a single-platform workflow; multi-platform releases need verification for each target platform.

**Version numbers like `@v7`:** these are release tags of each action. Check each action's GitHub Releases page occasionally and bump the major version when new ones appear. Dependabot can open those update PRs automatically.

---

## Common problems and fixes

| Symptom | Likely cause / fix |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop isn't running. Start it and wait for it to say it's running. |
| `port is already allocated` / `address already in use` | Something else uses port 8000. Stop it, or change the left side to `"8080:8000"`. |
| Push step fails with `denied` or `permission_denied: write_package` | Check `packages: write` is in the `docker` job, and that the repository's Actions settings allow the workflow to run. |
| `ruff format --check` fails | Run `ruff format .` locally, then commit the result. |
| Badge shows "no status" | The workflow hasn't run yet, or the username in the badge URL is still `[[YOUR-GITHUB-USERNAME]]`. |
| Can't pull your image | The package may be private. See the README's GHCR section. |

---

## Interview questions and answers

**1. What's the difference between an image and a container?**
An image is a read-only template made of layers: the OS files, Python, dependencies, and code. A container is a running instance of an image with its own process, network, and writable layer. You can start many containers from one image.

**2. Why use a multi-stage build?**
It separates *building* from *running*. Build tools, caches, and intermediate files stay in the builder stage, and only what the app needs is copied into the final stage. The result is a smaller image with less attack surface, and it's faster to push and pull. The effect is bigger when a project compiles dependencies.

**3. Why does the Dockerfile copy `requirements.txt` before the rest of the code?**
Layer caching. Docker re-runs a step only if that step or an earlier one changed. Code changes often and dependencies rarely, so installing dependencies in an earlier layer means most rebuilds skip the slow install.

**4. Why run the container as a non-root user?**
Least privilege. If an attacker exploits the app, they land with the permissions of that process. As root inside a container they'd have far more power, and any container-escape bug would be more serious. A non-root user limits the damage.

**5. What does the HEALTHCHECK do, and why is there a separate smoke test in CI?**
HEALTHCHECK lets Docker periodically test the running container and mark it healthy or unhealthy. Orchestrators can use that signal. The CI smoke test checks something different: that the freshly built image actually *starts and serves traffic* before we publish it. Unit tests run the code outside the container, so they can't catch problems like a missing file in the image, a wrong port, or a bad `CMD`.

**6. How does the pipeline authenticate to GitHub Container Registry without a stored password?**
GitHub creates a short-lived `GITHUB_TOKEN` for each workflow run. The `docker/login-action` step uses it as the password, and the `docker` job declares `packages: write` so the token is allowed to push packages. There's no long-lived secret to leak or rotate, and the token expires when the job ends.

**7. Why does the push step only run on `main`, and not on pull requests?**
Pull requests are unreviewed code, and often come from branches or forks. We test them (lint, tests, build, smoke test) but don't publish, so `latest` is published only from pushes to `main`, including direct pushes as well as merges. This is enforced with `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`.

**8. How would you extend this pipeline into a full CD pipeline, or make it more secure?**
- *Deploy:* add a job that runs after the push and deploys the new image to a server, ECS, or Kubernetes (the next project in this portfolio), ideally with an approval gate for production.
- *Security:* consider making the informational Trivy scan blocking after deciding how to handle findings and tool errors, pin actions to commit SHAs, and consider signing images. Dependabot update configuration is already included.
- *Quality:* add test coverage reporting and a required-status-check branch protection rule so nothing merges unless CI is green.
- *Versioning:* add semantic version tags on releases.

---

## Try it yourself (to build understanding)

1. Break a test on purpose (change `"ok"` to `"fine"` in `main.py`), push to a branch, open a pull request, and watch CI fail. Fix it and watch it go green.
2. Change the `HEALTHCHECK` port to `9999`, rebuild, and watch `docker ps` show `unhealthy`. Then revert.
3. Run `docker history docker-cicd-app:local` to see the layers, and `docker images` to see the image size.
4. Run `docker run --rm docker-cicd-app:local whoami` and confirm it prints `app`.
5. Add a new `/version` endpoint **with a test**, open a pull request, then merge it after checks pass. The push to `main` publishes a new `sha-` tag.

## Windows line endings

`.gitattributes` keeps text files in LF format across Windows and Linux and treats screenshots as binary files. This avoids relying on each developer's Git line-ending settings.
