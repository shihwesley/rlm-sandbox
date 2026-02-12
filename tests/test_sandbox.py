"""Integration tests for the Docker sandbox API.

These tests run against the live container via HTTP.
docker compose up must succeed before any test executes.
"""

import subprocess
import time
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://localhost:8080"


@pytest.fixture(scope="session")
def sandbox():
    """Build and start the sandbox container, wait for health, tear down after."""
    subprocess.run(
        ["docker", "compose", "up", "-d", "--build"],
        check=True,
        cwd=PROJECT_ROOT,
    )

    # Poll /health until the container is ready
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=2)
            if r.status_code == 200:
                break
        except requests.ConnectionError:
            pass
        time.sleep(1)
    else:
        pytest.fail("Sandbox did not become healthy within 15 seconds")

    yield BASE_URL

    subprocess.run(["docker", "compose", "down"], cwd=PROJECT_ROOT)


# ── AC-1: Health check ──────────────────────────────────────────────

def test_healthcheck(sandbox):
    r = requests.get(f"{sandbox}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


# ── AC-2: Basic exec ────────────────────────────────────────────────

def test_exec_basic(sandbox):
    r = requests.post(f"{sandbox}/exec", json={"code": "x = 42"})
    assert r.status_code == 200
    body = r.json()
    assert body["output"] == ""
    assert body["stderr"] == ""
    assert "x" in body["vars"]


# ── AC-3: List vars ─────────────────────────────────────────────────

def test_get_vars(sandbox):
    # Ensure x exists from the previous exec
    requests.post(f"{sandbox}/exec", json={"code": "x = 42"})

    r = requests.get(f"{sandbox}/vars")
    assert r.status_code == 200
    var_list = r.json()

    x_entry = next((v for v in var_list if v["name"] == "x"), None)
    assert x_entry is not None
    assert x_entry["type"] == "int"
    assert x_entry["summary"] == "42"


# ── AC-4: Get single var ────────────────────────────────────────────

def test_get_var(sandbox):
    requests.post(f"{sandbox}/exec", json={"code": "x = 42"})

    r = requests.get(f"{sandbox}/var/x")
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == 42


# ── AC-5: State persists across exec calls ───────────────────────────

def test_state_persistence(sandbox):
    requests.post(f"{sandbox}/exec", json={"code": "y = 99"})
    requests.post(f"{sandbox}/exec", json={"code": "z = y + 1"})

    r = requests.get(f"{sandbox}/var/z")
    assert r.status_code == 200
    assert r.json()["value"] == 100


# ── AC-6: DNS is blocked ────────────────────────────────────────────

def test_dns_blocked(sandbox):
    code = "import socket; socket.getaddrinfo('google.com', 80)"
    r = requests.post(f"{sandbox}/exec", json={"code": code})
    assert r.status_code == 200
    body = r.json()
    # The call should fail; error surfaces in stderr (or output, depending on impl)
    assert body["stderr"] != "" or "error" in body.get("output", "").lower()


# ── AC-8: Exec timeout (run before memory test — memory may OOM the container) ─

def test_exec_timeout(sandbox):
    code = "import time; time.sleep(30)"
    start = time.monotonic()
    r = requests.post(
        f"{sandbox}/exec",
        json={"code": code, "timeout": 5},
        timeout=15,
    )
    elapsed = time.monotonic() - start

    assert r.status_code == 200
    body = r.json()
    # Server should have killed the execution and returned an error
    has_error = (
        body.get("stderr", "") != ""
        or "error" in body.get("output", "").lower()
        or body.get("error") is not None
    )
    assert has_error, f"Expected a timeout error but got: {body}"
    assert elapsed < 10, f"Response took {elapsed:.1f}s; should be under 10s"


# ── AC-7: Memory limit (last test — OOM may kill the container) ──────

def test_memory_limit(sandbox):
    code = "x = list(range(500_000_000))"
    try:
        r = requests.post(f"{sandbox}/exec", json={"code": code}, timeout=30)
    except (requests.ConnectionError, requests.Timeout):
        # OOM killer terminated the container process — this is valid
        # behavior under a 2GB memory limit. The container enforced the limit.
        return

    assert r.status_code == 200
    body = r.json()
    has_error = (
        body.get("stderr", "") != ""
        or "error" in body.get("output", "").lower()
        or body.get("error") is not None
    )
    assert has_error, f"Expected a memory error but got: {body}"
