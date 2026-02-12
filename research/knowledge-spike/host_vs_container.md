# Host-side vs Container-side Execution

## Context
The Docker sandbox has a 2GB memory limit and no network access. The MCP server runs host-side with full network and unlimited memory.

## FAISS+fastembed Resource Profile
- Peak RAM: 1.1 GB (Python + ONNX runtime + model + index)
- Model download: ~50MB (requires network on first use, cached after)
- Embedding speed: 51 chunks/s
- Query latency: 2.4ms

## Comparison

| Factor | Host-side (MCP server) | Container-side (Docker sandbox) |
|--------|----------------------|-------------------------------|
| Memory headroom | Unlimited | 900MB free (2GB - 1.1GB) — tight |
| Model download | Cached in host fs | Would need pre-baking or volume mount |
| Network for download | Available | Blocked by policy |
| Startup overhead | None (loaded with MCP server) | Per-container or per-exec call |
| Isolation | Shares MCP server process | Isolated but eats container memory |
| API complexity | Direct Python calls | HTTP round-trip through FastAPI |
| Scaling | One index serves all containers | Each container needs its own index |

## Recommendation: Host-side

Run the search engine in the MCP server process, not inside the container.

Reasons:
1. **Memory.** 1.1GB in a 2GB container leaves only 900MB for the IPython kernel, user code, and DSPy operations. That's workable but fragile — a large dataframe or model load could OOM. Host-side has no such constraint.

2. **Model management.** fastembed downloads BGE-small on first use. The container has no network access. We'd need to pre-bake the model into the Docker image or mount it as a volume. Host-side just caches it in `~/.cache/fastembed/`.

3. **Shared state.** One search index on the host can serve multiple sandbox sessions. Container-side would need separate indexes per container, or a shared volume — both add complexity.

4. **Architecture alignment.** DSPy already runs host-side in the MCP server for the same reasons (no API keys in container). Search follows the same pattern.

The only downside is that the MCP server process gets heavier (1.1GB more RAM). On a development machine with 16-64GB RAM, this isn't a real constraint.
