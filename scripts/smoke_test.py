"""Check a running release's health, identity, and version before publication."""

import argparse
import json
import sys
import time
from urllib.request import urlopen


def read_json(url: str, deadline: float):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Smoke-test deadline exceeded")
    with urlopen(url, timeout=min(2.0, remaining)) as response:
        return json.loads(response.read(65536))


def check_app(base_url: str, expected_version: str, timeout: float = 30.0):
    """Retry startup errors, then reject incorrect health or release metadata."""
    deadline = time.monotonic() + timeout
    base_url = base_url.rstrip("/")
    last_error = None
    while time.monotonic() < deadline:
        try:
            health = read_json(f"{base_url}/health", deadline)
        except OSError as error:
            last_error = error
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
            continue
        if health != {"status": "ok"}:
            raise ValueError(f"Unexpected health response: {health!r}")
        break
    else:
        raise TimeoutError(f"App did not become ready within {timeout}s: {last_error}")

    info = read_json(f"{base_url}/api/info", deadline)
    if not isinstance(info, dict) or info.get("service") != "docker-cicd-app":
        raise ValueError(f"Unexpected service identity: {info!r}")
    if info.get("version") != expected_version:
        raise ValueError(
            f"Version mismatch: expected {expected_version!r}, got {info.get('version')!r}"
        )
    if not isinstance(info.get("hostname"), str) or not info["hostname"]:
        raise ValueError("App did not return a hostname")
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        info = check_app(args.base_url, args.expected_version, args.timeout)
    except (OSError, ValueError) as error:
        print(f"Smoke test failed: {error}", file=sys.stderr)
        return 1
    print(f"Smoke test passed: {json.dumps(info, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
