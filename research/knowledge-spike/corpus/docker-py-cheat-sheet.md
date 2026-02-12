# docker-py Cheat Sheet

## Installation
```bash
pip install docker
```

## Client
```python
import docker
client = docker.from_env()  # uses DOCKER_HOST or default socket
```

## Run Container (detached)
```python
container = client.containers.run(
    image="my-image:latest",
    name="my-container",
    detach=True,
    ports={"8000/tcp": 8000},
    environment={"KEY": "value"},
    volumes={"/host/path": {"bind": "/container/path", "mode": "rw"}},
    mem_limit="2g",
    cpu_quota=200000,  # 2 CPUs (cpu_period default 100000)
    network_mode="none",  # no network access
    restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
    healthcheck={
        "test": ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
        "interval": 30_000_000_000,   # 30s in nanoseconds
        "timeout": 10_000_000_000,    # 10s
        "retries": 3,
        "start_period": 10_000_000_000,
    },
)
```

## Lifecycle
```python
container.start()
container.stop(timeout=10)
container.restart(timeout=10)
container.kill(signal="SIGTERM")
container.remove(force=True)
container.pause()
container.unpause()
```

## Get Existing Container
```python
container = client.containers.get("container-name-or-id")
print(container.status)  # "running", "exited", etc.
```

## List Containers
```python
running = client.containers.list()  # running only
all_containers = client.containers.list(all=True)
```

## Logs
```python
logs = container.logs()  # bytes
logs = container.logs(stream=True)  # generator
```

## Exec in Container
```python
exit_code, output = container.exec_run("python -c 'print(1)'")
```

## Health Check Status
```python
container.reload()  # refresh state from daemon
health = container.attrs["State"]["Health"]["Status"]
# "healthy", "unhealthy", "starting"
```

## Create Without Starting
```python
container = client.containers.create(image="myimg", name="myname", ...)
container.start()
```

## Key Points
- from_env() reads DOCKER_HOST, DOCKER_TLS_VERIFY, DOCKER_CERT_PATH
- healthcheck intervals are in NANOSECONDS (multiply seconds by 1e9)
- network_mode="none" disables all network access
- container.reload() needed to refresh attrs after state changes
- container.status is a cached property — call reload() for current state
