"""Docker lifecycle management for the sandbox container."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import docker
import httpx

log = logging.getLogger(__name__)

CONTAINER_NAME = "rlm-sandbox"
CONTAINER_PORT = 8080
IMAGE_NAME = "rlm-sandbox-sandbox"  # docker compose default: <project>-<service>
BASE_URL = f"http://localhost:{CONTAINER_PORT}"
HEALTH_INTERVAL = 30  # seconds
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class DockerManager:
    """Manage the sandbox Docker container lifecycle."""

    container: docker.models.containers.Container | None = field(default=None, init=False)
    _client: docker.DockerClient | None = field(default=None, init=False)
    _health_task: asyncio.Task | None = field(default=None, init=False)
    _bare_process: subprocess.Popen | None = field(default=None, init=False)
    _no_docker: bool = field(default=False, init=False)

    def _get_client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    async def start(self) -> None:
        """Start the sandbox container (builds if image missing)."""
        try:
            client = self._get_client()
        except docker.errors.DockerException:
            log.warning("Docker not available, falling back to bare kernel subprocess")
            await self._start_bare()
            return

        # Check if container already exists
        try:
            existing = client.containers.get(CONTAINER_NAME)
            if existing.status == "running":
                self.container = existing
                log.info("Container %s already running", CONTAINER_NAME)
                return
            existing.remove(force=True)
        except docker.errors.NotFound:
            pass

        # Build image via docker compose to match the project's Dockerfile
        try:
            subprocess.run(
                ["docker", "compose", "build"],
                check=True,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            log.error("Docker build failed: %s", e.stderr)
            raise RuntimeError(f"Failed to build sandbox image: {e.stderr}") from e

        # Use bridge networking with null DNS (matches docker-compose.yml)
        # instead of network_mode="none" which blocks port mapping entirely.
        # extra_hosts maps host.docker.internal via /etc/hosts (bypasses null DNS)
        # so the llm_query callback can reach the host.
        self.container = client.containers.run(
            image=IMAGE_NAME,
            name=CONTAINER_NAME,
            detach=True,
            ports={f"{CONTAINER_PORT}/tcp": CONTAINER_PORT},
            mem_limit="2g",
            cpu_quota=200000,
            dns=["0.0.0.0"],
            extra_hosts={"host.docker.internal": "host-gateway"},
            healthcheck={
                "test": ["CMD-SHELL", f"curl -f http://localhost:{CONTAINER_PORT}/health || exit 1"],
                "interval": 30_000_000_000,
                "timeout": 10_000_000_000,
                "retries": 3,
            },
        )
        log.info("Started container %s", CONTAINER_NAME)

        # Wait for the container to be healthy
        await self._wait_healthy()

    async def _start_bare(self) -> None:
        """Fallback: run uvicorn directly (no Docker)."""
        self._no_docker = True
        self._bare_process = subprocess.Popen(
            ["uvicorn", "sandbox.server:app", "--host", "127.0.0.1", "--port", str(CONTAINER_PORT)],
            cwd=PROJECT_ROOT,
        )
        await self._wait_healthy()

    async def _wait_healthy(self, timeout: float = 15) -> None:
        """Poll /health until the server responds."""
        async with httpx.AsyncClient() as client:
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                try:
                    r = await client.get(f"{BASE_URL}/health", timeout=2)
                    if r.status_code == 200:
                        return
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(0.5)
        raise TimeoutError(f"Sandbox did not become healthy within {timeout}s")

    async def stop(self) -> None:
        """Stop and remove the container."""
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        if self._bare_process:
            self._bare_process.terminate()
            self._bare_process.wait(timeout=5)
            self._bare_process = None
            return

        if self.container:
            try:
                self.container.stop(timeout=10)
                self.container.remove(force=True)
            except docker.errors.NotFound:
                pass
            self.container = None
            log.info("Stopped container %s", CONTAINER_NAME)

    async def health_check(self) -> bool:
        """Check if the sandbox is responding."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{BASE_URL}/health", timeout=5)
                return r.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def restart(self) -> None:
        """Restart the container (or bare process)."""
        if self._no_docker and self._bare_process:
            self._bare_process.terminate()
            self._bare_process.wait(timeout=5)
            await self._start_bare()
            return

        if self.container:
            self.container.restart(timeout=10)
            await self._wait_healthy()
            log.info("Restarted container %s", CONTAINER_NAME)

    async def ensure_running(self) -> None:
        """Lazy start: start if not already running, health-check if running."""
        if self.container is None and self._bare_process is None:
            await self.start()
            self._start_health_loop()
            return

        if not await self.health_check():
            log.warning("Health check failed, restarting")
            await self.restart()

    def _start_health_loop(self) -> None:
        """Background task that checks health periodically."""
        if self._health_task and not self._health_task.done():
            return
        self._health_task = asyncio.create_task(self._health_loop())

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(HEALTH_INTERVAL)
            if not await self.health_check():
                log.warning("Health check failed, auto-restarting")
                try:
                    await self.restart()
                except Exception:
                    log.exception("Auto-restart failed")
