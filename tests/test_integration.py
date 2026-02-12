"""Smoke tests for the Claude integration artifacts.

These verify the config/docs layer is structurally correct without
needing a live Claude Code session or Docker.
"""

import json
import os
import stat
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = PROJECT_ROOT / "claude-integration"


class TestMCPConfig:
    """Verify mcp-config.json structure."""

    config_path = INTEGRATION_DIR / "mcp-config.json"

    def test_file_exists(self):
        assert self.config_path.exists()

    def test_valid_json(self):
        with open(self.config_path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_mcp_servers_key(self):
        with open(self.config_path) as f:
            data = json.load(f)
        assert "mcpServers" in data

    def test_rlm_server_entry(self):
        with open(self.config_path) as f:
            data = json.load(f)
        rlm = data["mcpServers"]["rlm"]
        assert rlm["command"] == "python"
        assert "-m" in rlm["args"]
        assert "mcp_server.server" in rlm["args"]

    def test_has_project_dir_placeholder(self):
        with open(self.config_path) as f:
            data = json.load(f)
        cwd = data["mcpServers"]["rlm"]["cwd"]
        assert "{PROJECT_DIR}" in cwd


class TestRoutingRules:
    """Verify routing rules file has expected content."""

    rules_path = INTEGRATION_DIR / "rlm-routing-rules.md"

    def test_file_exists(self):
        assert self.rules_path.exists()

    def test_has_file_loading_section(self):
        content = self.rules_path.read_text()
        assert "File Loading" in content

    def test_mentions_200_line_threshold(self):
        content = self.rules_path.read_text()
        assert "200 lines" in content

    def test_mentions_rlm_load(self):
        content = self.rules_path.read_text()
        assert "rlm_load" in content

    def test_mentions_rlm_exec(self):
        content = self.rules_path.read_text()
        assert "rlm_exec" in content

    def test_mentions_rlm_sub_agent(self):
        content = self.rules_path.read_text()
        assert "rlm_sub_agent" in content

    def test_mentions_rlm_get(self):
        content = self.rules_path.read_text()
        assert "rlm_get" in content

    def test_has_when_not_to_use_section(self):
        content = self.rules_path.read_text()
        assert "When NOT to Use" in content


class TestSetupScript:
    """Verify setup.sh is valid and has expected structure."""

    script_path = INTEGRATION_DIR / "setup.sh"

    def test_file_exists(self):
        assert self.script_path.exists()

    def test_is_executable(self):
        mode = os.stat(self.script_path).st_mode
        assert mode & stat.S_IXUSR, "setup.sh should be executable"

    def test_has_shebang(self):
        content = self.script_path.read_text()
        assert content.startswith("#!/")

    def test_has_set_euo_pipefail(self):
        content = self.script_path.read_text()
        assert "set -euo pipefail" in content

    def test_references_mcp_config(self):
        content = self.script_path.read_text()
        assert "mcp-config.json" in content

    def test_references_routing_rules(self):
        content = self.script_path.read_text()
        assert "rlm-routing-rules.md" in content

    def test_checks_python_availability(self):
        content = self.script_path.read_text()
        assert "python" in content.lower()

    def test_prints_tool_names(self):
        content = self.script_path.read_text()
        assert "rlm_exec" in content


class TestReadme:
    """Verify README.md exists and covers required topics."""

    readme_path = PROJECT_ROOT / "README.md"

    def test_file_exists(self):
        assert self.readme_path.exists()

    def test_mentions_three_tiers(self):
        content = self.readme_path.read_text()
        assert "Tier 1" in content
        assert "Tier 2" in content
        assert "Tier 3" in content

    def test_mentions_no_docker_flag(self):
        content = self.readme_path.read_text()
        assert "--no-docker" in content or "no-docker" in content

    def test_has_tool_reference(self):
        content = self.readme_path.read_text()
        for tool in ["rlm_exec", "rlm_load", "rlm_get", "rlm_vars", "rlm_sub_agent", "rlm_reset"]:
            assert tool in content, f"README should reference {tool}"

    def test_has_architecture_section(self):
        content = self.readme_path.read_text()
        assert "Architecture" in content or "architecture" in content

    def test_has_quick_start(self):
        content = self.readme_path.read_text()
        assert "Quick Start" in content or "quick start" in content

    def test_mentions_sandbox_compatibility(self):
        content = self.readme_path.read_text()
        assert "/sandbox" in content
