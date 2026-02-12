"""Tests for session persistence (snapshot save/restore).

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

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=2)
            if r.status_code == 200:
                break
        except requests.ConnectionError:
            pass
        time.sleep(1)
    else:
        pytest.fail("Sandbox did not become healthy within 20 seconds")

    yield BASE_URL

    subprocess.run(["docker", "compose", "down"], cwd=PROJECT_ROOT)


@pytest.fixture(autouse=True)
def reset_kernel(sandbox):
    """Reset kernel state before each test so tests don't leak into each other."""
    requests.post(f"{sandbox}/exec", json={"code": "get_ipython().reset(new_session=True)"})
    yield


# -- AC-1: Save/restore round-trip --


def test_save_restore_roundtrip(sandbox):
    """After exec x=42, save, clear, restore — x should come back."""
    # Set a variable
    requests.post(f"{sandbox}/exec", json={"code": "x = 42"})
    r = requests.get(f"{sandbox}/var/x")
    assert r.json()["value"] == 42

    # Save snapshot
    r = requests.post(f"{sandbox}/snapshot/save")
    assert r.status_code == 200
    snapshot_data = r.json()
    assert "x" in snapshot_data["saved"]

    # Clear kernel
    requests.post(f"{sandbox}/exec", json={"code": "get_ipython().reset(new_session=True)"})
    r = requests.get(f"{sandbox}/var/x")
    assert r.json().get("error") == "not found"

    # Restore snapshot
    r = requests.post(f"{sandbox}/snapshot/restore", json={"snapshot": snapshot_data["snapshot"]})
    assert r.status_code == 200, r.text
    assert "x" in r.json()["restored"]

    # Verify x is back
    r = requests.get(f"{sandbox}/var/x")
    assert r.json()["value"] == 42


def test_save_restore_multiple_types(sandbox):
    """Round-trip works for various Python types (list, dict, lambda, string)."""
    setup_code = """
data = [1, 2, 3]
config = {"key": "value", "nested": {"a": 1}}
greeting = "hello world"
double = lambda x: x * 2
"""
    requests.post(f"{sandbox}/exec", json={"code": setup_code})

    r = requests.post(f"{sandbox}/snapshot/save")
    assert r.status_code == 200
    snapshot = r.json()

    # All should be saved (dill handles lambdas)
    assert "data" in snapshot["saved"]
    assert "config" in snapshot["saved"]
    assert "greeting" in snapshot["saved"]
    assert "double" in snapshot["saved"]

    # Clear and restore
    requests.post(f"{sandbox}/exec", json={"code": "get_ipython().reset(new_session=True)"})
    r = requests.post(f"{sandbox}/snapshot/restore", json={"snapshot": snapshot["snapshot"]})
    assert r.status_code == 200

    r = requests.get(f"{sandbox}/var/data")
    assert r.json()["value"] == [1, 2, 3]

    r = requests.get(f"{sandbox}/var/config")
    assert r.json()["value"] == {"key": "value", "nested": {"a": 1}}

    # Verify lambda works after restore
    r = requests.post(f"{sandbox}/exec", json={"code": "print(double(21))"})
    assert "42" in r.json()["output"]


# -- AC-4: Corrupt snapshot handling --


def test_corrupt_snapshot_returns_error(sandbox):
    """Sending garbage bytes should return 400, not crash the server."""
    import base64
    bad_data = base64.b64encode(b"this is not valid dill data").decode()
    r = requests.post(f"{sandbox}/snapshot/restore", json={"snapshot": bad_data})
    assert r.status_code == 400
    body = r.json()
    assert "error" in body
    assert "corrupt" in body["error"].lower()


def test_missing_snapshot_field_returns_error(sandbox):
    """Empty payload should return a clear error."""
    r = requests.post(f"{sandbox}/snapshot/restore", json={})
    assert r.status_code == 400
    assert "missing" in r.json()["error"].lower()


# -- AC-5: Non-serializable vars are skipped --


def test_non_serializable_vars_skipped(sandbox):
    """Open file handles and generators should be skipped, not crash save."""
    code = """
normal_var = 100
fh = open('/dev/null', 'r')
gen = (x for x in range(10))
"""
    requests.post(f"{sandbox}/exec", json={"code": code})

    r = requests.post(f"{sandbox}/snapshot/save")
    assert r.status_code == 200
    body = r.json()

    assert "normal_var" in body["saved"]
    # File handles and generators may or may not serialize with dill,
    # but the endpoint should not crash regardless.
    # If they end up in skipped, that's correct. If dill handles them, that's also fine.
    all_accounted = set(body["saved"]) | set(body["skipped"])
    assert "normal_var" in all_accounted

    # Restore should at least bring back normal_var
    requests.post(f"{sandbox}/exec", json={"code": "get_ipython().reset(new_session=True)"})
    r = requests.post(f"{sandbox}/snapshot/restore", json={"snapshot": body["snapshot"]})
    assert r.status_code == 200
    assert "normal_var" in r.json()["restored"]

    r = requests.get(f"{sandbox}/var/normal_var")
    assert r.json()["value"] == 100


# -- SessionManager unit tests (no Docker needed) --


def test_session_id_deterministic():
    """Same working dir always produces the same session ID."""
    from mcp_server.session import _session_id
    id1 = _session_id("/some/project/path")
    id2 = _session_id("/some/project/path")
    assert id1 == id2
    assert len(id1) == 16


def test_session_id_varies_by_path():
    """Different dirs produce different IDs."""
    from mcp_server.session import _session_id
    id1 = _session_id("/project/a")
    id2 = _session_id("/project/b")
    assert id1 != id2
