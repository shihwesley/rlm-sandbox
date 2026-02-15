#!/usr/bin/env bash
set -euo pipefail

# rlm-sandbox plugin setup
# Creates venv, installs Python deps, optionally pulls Docker image.

PLUGIN_ROOT="${RLM_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV_DIR="$PLUGIN_ROOT/.venv"

echo "=== rlm-sandbox setup ==="

# 1. Python venv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python venv..."
    python3 -m venv "$VENV_DIR"
fi

echo "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q \
    "mcp[cli]" \
    httpx \
    docker \
    dill \
    dspy \
    memvid-sdk \
    sentence-transformers \
    html2text \
    fastapi \
    uvicorn \
    ipython

# 2. Data directories
mkdir -p ~/.rlm-sandbox/knowledge
mkdir -p ~/.rlm-sandbox/sessions
echo "Knowledge store: ~/.rlm-sandbox/knowledge/"
echo "Session store:   ~/.rlm-sandbox/sessions/"

# 3. Docker (optional — needed for sandbox, not for knowledge tools)
if command -v docker &>/dev/null; then
    if docker info &>/dev/null 2>&1; then
        echo "Docker available. Building sandbox image..."
        if [ -f "$PLUGIN_ROOT/Dockerfile" ]; then
            docker build -t rlm-sandbox "$PLUGIN_ROOT" -q 2>/dev/null || \
                echo "Warning: Docker build failed. Sandbox tools won't work, but knowledge tools will."
        fi
    else
        echo "Docker installed but daemon not running. Sandbox tools need Docker; knowledge tools work without it."
    fi
else
    echo "Docker not installed. Sandbox tools (rlm_exec, rlm_load, etc.) won't work."
    echo "Knowledge tools (rlm_search, rlm_fetch, etc.) work fine without Docker."
fi

echo ""
echo "=== Setup complete ==="
echo "Tools available:"
echo "  Always:  rlm_search, rlm_ask, rlm_fetch, rlm_research, rlm_knowledge_status"
echo "  Always:  rlm_apple_search, rlm_apple_export, rlm_apple_read, rlm_context7_ingest"
echo "  Docker:  rlm_exec, rlm_load, rlm_get, rlm_vars, rlm_sub_agent, rlm_reset"
