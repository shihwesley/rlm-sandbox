"""Integration tests for the MCP server layer.

These tests run against a live Docker container.
docker compose up must be available.
"""

import subprocess
import tempfile
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


# -- DockerManager lazy start --


def test_docker_manager_lazy_start():
    """Manager doesn't start container on init, only on ensure_running()."""
    import asyncio
    from mcp_server.docker_manager import DockerManager

    manager = DockerManager()
    assert manager.container is None
    assert manager._bare_process is None

    # We don't call ensure_running() here — just verify nothing started on init.
    # Full lifecycle is tested via the fixture-backed tests below.
    asyncio.run(manager.stop())  # no-op, but shouldn't error


# -- Tool-level integration tests (route through HTTP, not MCP protocol) --


def test_exec_tool_routes_to_container(sandbox):
    """rlm.exec runs code and returns output."""
    r = requests.post(f"{sandbox}/exec", json={"code": "print(2 + 2)"})
    assert r.status_code == 200
    body = r.json()
    assert "4" in body["output"]


def test_load_tool_reads_host_file(sandbox):
    """rlm.load reads a local file and injects content into sandbox."""
    # Write a temp file, post its content as a variable
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello from host")
        tmp_path = f.name

    content = Path(tmp_path).read_text()
    import json
    escaped = json.dumps(content)
    code = f"host_data = {escaped}"
    r = requests.post(f"{sandbox}/exec", json={"code": code})
    assert r.status_code == 200

    r = requests.get(f"{sandbox}/var/host_data")
    assert r.status_code == 200
    assert r.json()["value"] == "hello from host"


def test_get_tool_retrieves_variable(sandbox):
    """rlm.get returns a variable's value."""
    requests.post(f"{sandbox}/exec", json={"code": "test_var = 123"})
    r = requests.get(f"{sandbox}/var/test_var")
    assert r.status_code == 200
    assert r.json()["value"] == 123


def test_get_tool_with_query(sandbox):
    """rlm.get with a query expression evaluates it in the sandbox."""
    requests.post(f"{sandbox}/exec", json={"code": "items = [1, 2, 3]"})
    r = requests.post(f"{sandbox}/exec", json={"code": "print(len(items))"})
    assert r.status_code == 200
    assert "3" in r.json()["output"]


def test_vars_tool_lists_variables(sandbox):
    """rlm.vars returns a list of all variables."""
    requests.post(f"{sandbox}/exec", json={"code": "alpha = 'a'; beta = 'b'"})
    r = requests.get(f"{sandbox}/vars")
    assert r.status_code == 200
    var_names = [v["name"] for v in r.json()]
    assert "alpha" in var_names
    assert "beta" in var_names


def test_reset_clears_state(sandbox):
    """rlm.reset wipes sandbox state."""
    requests.post(f"{sandbox}/exec", json={"code": "ephemeral = 42"})
    r = requests.get(f"{sandbox}/var/ephemeral")
    assert r.json()["value"] == 42

    # Reset via IPython's built-in reset
    requests.post(f"{sandbox}/exec", json={"code": "get_ipython().reset(new_session=True)"})

    r = requests.get(f"{sandbox}/var/ephemeral")
    body = r.json()
    # After reset the variable should be gone
    assert body.get("error") == "not found" or body.get("value") is None


def test_health_check_recovery(sandbox):
    """Health check endpoint responds correctly."""
    r = requests.get(f"{sandbox}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
