"""Tests for the bundled Slack reference plugin."""

from __future__ import annotations

import sys

from hermes_cli.plugins import PluginManager


def test_bundled_slack_plugin_registers_platform_and_cli(monkeypatch, tmp_path):
    """Slack is a bundled official-extra plugin, not a core hardcoded platform."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))

    from gateway.platform_registry import platform_registry

    # The registry is process-global; make the assertion deterministic even if
    # another test loaded the plugin earlier in the same process.
    platform_registry.unregister("slack")
    sys.modules.pop("hermes_plugins.builtin__slack", None)

    manager = PluginManager()
    try:
        manager.discover_and_load(force=True)

        loaded = manager._plugins["builtin/slack"]
        assert loaded.enabled is True
        assert loaded.manifest.name == "hermes-slack"
        assert loaded.manifest.kind == "platform"
        assert loaded.manifest.requires_extra == ["slack"]
        assert loaded.manifest.source == "bundled"

        entry = platform_registry.get("slack")
        assert entry is not None
        assert entry.source == "plugin"
        assert entry.plugin_name == "hermes-slack"
        assert entry.label == "Slack"
        assert entry.install_hint == "pip install 'hermes-agent[slack]'"
        assert entry.required_env == ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]
        assert entry.allowed_users_env == "SLACK_ALLOWED_USERS"
        assert entry.allow_all_env == "SLACK_ALLOW_ALL_USERS"
        assert entry.cron_deliver_env_var == "SLACK_HOME_CHANNEL"

        slack_cli = manager._cli_commands["slack"]
        assert slack_cli["plugin"] == "hermes-slack"
        assert slack_cli["help"] == "Slack integration helpers"
        assert callable(slack_cli["setup_fn"])
        assert callable(slack_cli["handler_fn"])
    finally:
        platform_registry.unregister("slack")
        sys.modules.pop("hermes_plugins.builtin__slack", None)
