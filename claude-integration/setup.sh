#!/usr/bin/env bash
set -euo pipefail

# rlm-sandbox Claude Code integration installer
# Safe to run multiple times (idempotent).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Claude Code MCP config location
CLAUDE_MCP_DIR="$HOME/.claude"
CLAUDE_MCP_CONFIG="$CLAUDE_MCP_DIR/mcp_settings.json"

echo "rlm-sandbox integration setup"
echo "Project: $PROJECT_DIR"
echo ""

# --- Check dependencies ---

if ! command -v python &>/dev/null && ! command -v python3 &>/dev/null; then
    echo "Error: Python not found. Install Python 3.12+ first."
    exit 1
fi

PYTHON_CMD="python"
if ! command -v python &>/dev/null; then
    PYTHON_CMD="python3"
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo "Python: $PYTHON_VERSION"

# Check that mcp package is importable
if ! $PYTHON_CMD -c "import mcp" &>/dev/null; then
    echo ""
    echo "MCP package not installed. Installing dependencies..."
    pip install -r "$PROJECT_DIR/mcp_server/requirements.txt"
fi

# --- Install MCP config ---

echo ""
echo "Installing MCP server config..."

mkdir -p "$CLAUDE_MCP_DIR"

# Build the config with the real project path (escape for sed safety)
ESCAPED_DIR=$(printf '%s\n' "$PROJECT_DIR" | sed 's/[\/&|]/\\&/g')
CONFIG_CONTENT=$(sed "s|{PROJECT_DIR}|$ESCAPED_DIR|g" "$SCRIPT_DIR/mcp-config.json")

if [ -f "$CLAUDE_MCP_CONFIG" ]; then
    # Backup before any modifications
    cp "$CLAUDE_MCP_CONFIG" "$CLAUDE_MCP_CONFIG.bak"
    # Merge into existing config: add the rlm server entry
    if $PYTHON_CMD -c "
import json, sys
with open('$CLAUDE_MCP_CONFIG') as f:
    existing = json.load(f)
new = json.loads('''$CONFIG_CONTENT''')
existing.setdefault('mcpServers', {}).update(new['mcpServers'])
with open('$CLAUDE_MCP_CONFIG', 'w') as f:
    json.dump(existing, f, indent=2)
    f.write('\n')
print('Merged rlm config into existing MCP settings.')
"; then
        :
    else
        echo "Warning: Could not merge config. Restoring backup and writing fresh."
        cp "$CLAUDE_MCP_CONFIG.bak" "$CLAUDE_MCP_CONFIG"
        echo "$CONFIG_CONTENT" > "$CLAUDE_MCP_CONFIG"
    fi
else
    echo "$CONFIG_CONTENT" > "$CLAUDE_MCP_CONFIG"
    echo "Created $CLAUDE_MCP_CONFIG"
fi

# --- Install routing rules ---

echo ""
echo "Installing routing rules..."

PROJECT_CLAUDE_DIR="$PROJECT_DIR/.claude"
mkdir -p "$PROJECT_CLAUDE_DIR"

RULES_DEST="$PROJECT_CLAUDE_DIR/rlm-routing-rules.md"

if [ -L "$RULES_DEST" ] || [ -f "$RULES_DEST" ]; then
    rm "$RULES_DEST"
fi

# Symlink so updates to the source propagate automatically
ln -s "$SCRIPT_DIR/rlm-routing-rules.md" "$RULES_DEST"
echo "Linked routing rules -> $RULES_DEST"

# --- Verify ---

echo ""
echo "Verifying setup..."

if $PYTHON_CMD -c "import mcp; import httpx; import docker" &>/dev/null; then
    echo "All Python dependencies available."
elif $PYTHON_CMD -c "import mcp; import httpx" &>/dev/null; then
    echo "Core dependencies available (docker package missing — Tier 1 mode only)."
else
    echo "Warning: Some dependencies missing. Run: pip install -r $PROJECT_DIR/mcp_server/requirements.txt"
fi

echo ""
echo "--- Setup complete ---"
echo ""
echo "Quick start:"
echo "  1. Restart Claude Code (or reload MCP servers)"
echo "  2. The 'rlm' server should appear in your tool list"
echo "  3. Try: \"Use rlm_exec to print hello world\""
echo ""
echo "Tools available: rlm_exec, rlm_load, rlm_get, rlm_vars, rlm_sub_agent, rlm_reset"
