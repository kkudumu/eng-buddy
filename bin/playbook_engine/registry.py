"""Tool Registry — modular catalog of available tools, capabilities, and defaults."""

import yaml
from pathlib import Path
from typing import Optional


class ToolRegistry:
    def __init__(self, registry_dir: str):
        self.registry_dir = Path(registry_dir)
        self.tools: dict = {}
        self._defaults: dict = {}  # tool_name -> {action -> {param: value}}
        self._load()

    def _load(self) -> None:
        reg_path = self.registry_dir / "_registry.yml"
        if reg_path.exists():
            with open(reg_path) as f:
                data = yaml.safe_load(f) or {}
            self.tools = data.get("tools", {})

        # Load per-tool defaults
        for yml in self.registry_dir.glob("*.defaults.yml"):
            tool_name = yml.stem.replace(".defaults", "")
            with open(yml) as f:
                self._defaults[tool_name] = yaml.safe_load(f) or {}

    def get_defaults(self, tool_name: str, action: str) -> dict:
        tool_defaults = self._defaults.get(tool_name, {})
        return dict(tool_defaults.get(action, {}))

    def merge_params(self, tool_name: str, action: str, playbook_params: dict) -> dict:
        defaults = self.get_defaults(tool_name, action)
        defaults.update(playbook_params)
        return defaults

    def get_tool_info(self, tool_name: str) -> Optional[dict]:
        return self.tools.get(tool_name)

    def resolve_tool_name(self, mcp_tool_name: str) -> tuple:
        """Given a full MCP tool name like mcp__slack__post_message, return (tool_name, action)."""
        for name, info in self.tools.items():
            prefix = info.get("prefix", "")
            if prefix and mcp_tool_name.startswith(prefix):
                action = mcp_tool_name[len(prefix):]
                return (name, action)
        return (None, None)

    def get_auth_requirement(self, tool_name: str) -> str:
        info = self.tools.get(tool_name, {})
        return info.get("auth", "none")

    def list_tools_for_domain(self, domain: str) -> list:
        return [
            name for name, info in self.tools.items()
            if domain in info.get("domains", [])
        ]
