"""Tests for /tools slash command handler in the interactive CLI."""

from unittest.mock import MagicMock, patch, call

from cli import HermesCLI


def _make_cli(enabled_toolsets=None):
    """Build a minimal HermesCLI stub without running __init__."""
    cli_obj = HermesCLI.__new__(HermesCLI)
    cli_obj.enabled_toolsets = set(enabled_toolsets or ["web", "memory"])
    cli_obj._command_running = False
    cli_obj.console = MagicMock()
    return cli_obj


# ── /tools (no subcommand) ──────────────────────────────────────────────────


class TestToolsSlashNoSubcommand:

    def test_bare_tools_shows_tool_list(self):
        cli_obj = _make_cli()
        with patch.object(cli_obj, "show_tools") as mock_show:
            cli_obj._handle_tools_command("/tools")
        mock_show.assert_called_once()

    def test_unknown_subcommand_falls_back_to_show_tools(self):
        cli_obj = _make_cli()
        with patch.object(cli_obj, "show_tools") as mock_show:
            cli_obj._handle_tools_command("/tools foobar")
        mock_show.assert_called_once()


# ── /tools list ─────────────────────────────────────────────────────────────


class TestToolsSlashList:

    def test_list_calls_backend(self, capsys):
        cli_obj = _make_cli()
        with patch("hermes_cli.tools_config.load_config",
                   return_value={"platform_toolsets": {"cli": ["web"]}}), \
             patch("hermes_cli.tools_config._runtime_status_for_toolset",
                   return_value={"available": True, "reason": "available", "available_count": 1, "declared_count": 1}), \
             patch("hermes_cli.tools_config.save_config"):
            cli_obj._handle_tools_command("/tools list")
        out = capsys.readouterr().out
        assert "web" in out

    def test_list_does_not_modify_enabled_toolsets(self):
        """List is read-only — self.enabled_toolsets must not change."""
        cli_obj = _make_cli(["web", "memory"])
        with patch("hermes_cli.tools_config.load_config",
                   return_value={"platform_toolsets": {"cli": ["web"]}}), \
             patch("hermes_cli.tools_config._runtime_status_for_toolset",
                   return_value={"available": True, "reason": "available", "available_count": 1, "declared_count": 1}):
            cli_obj._handle_tools_command("/tools list")
        assert cli_obj.enabled_toolsets == {"web", "memory"}


class TestToolsetsSlashDisplay:

    def test_show_toolsets_hides_unavailable_unenabled_extras(self, capsys):
        cli_obj = _make_cli(["web"])
        statuses = {
            "web": {
                "available": True,
                "reason": "available",
                "hint": "",
                "available_count": 2,
                "declared_count": 2,
            },
            "yuanbao": {
                "available": False,
                "reason": "install/config required",
                "hint": "configure yuanbao",
                "available_count": 0,
                "declared_count": 5,
            },
        }
        with patch(
            "hermes_cli.tools_config._get_effective_configurable_toolsets",
            return_value=[("web", "Web", "web"), ("yuanbao", "Yuanbao", "yb")],
        ), patch("cli.get_toolset_runtime_status", side_effect=lambda name: statuses[name]), \
             patch("cli.get_toolset_info", side_effect=lambda name: {"description": f"{name} desc"}):
            cli_obj.show_toolsets()
        out = capsys.readouterr().out
        assert "web" in out
        assert "yuanbao" not in out
        assert "Hidden: 1 uninstalled/unconfigured optional toolsets" in out

    def test_show_toolsets_keeps_enabled_but_unready_with_hint(self, capsys):
        cli_obj = _make_cli(["yuanbao"])
        status = {
            "available": False,
            "reason": "install/config required",
            "hint": "configure yuanbao",
            "available_count": 0,
            "declared_count": 5,
        }
        with patch(
            "hermes_cli.tools_config._get_effective_configurable_toolsets",
            return_value=[("yuanbao", "Yuanbao", "yb")],
        ), patch("cli.get_toolset_runtime_status", return_value=status), \
             patch("cli.get_toolset_info", return_value={"description": "Yuanbao desc"}):
            cli_obj.show_toolsets()
        out = capsys.readouterr().out
        assert "(!) yuanbao" in out
        assert "hint: configure yuanbao" in out


# ── /tools disable (session reset) ──────────────────────────────────────────


class TestToolsSlashDisableWithReset:

    def test_disable_applies_directly_and_resets_session(self):
        """Disable applies immediately (no confirmation prompt) and resets session."""
        cli_obj = _make_cli(["web", "memory"])
        with patch("hermes_cli.tools_config.load_config",
                   return_value={"platform_toolsets": {"cli": ["web", "memory"]}}), \
             patch("hermes_cli.tools_config.save_config"), \
             patch("hermes_cli.tools_config._get_platform_tools", return_value={"memory"}), \
             patch("hermes_cli.config.load_config", return_value={}), \
             patch.object(cli_obj, "new_session") as mock_reset:
            cli_obj._handle_tools_command("/tools disable web")
        mock_reset.assert_called_once()
        assert "web" not in cli_obj.enabled_toolsets

    def test_disable_does_not_prompt_for_confirmation(self):
        """Disable no longer uses input() — it applies directly."""
        cli_obj = _make_cli(["web", "memory"])
        with patch("hermes_cli.tools_config.load_config",
                   return_value={"platform_toolsets": {"cli": ["web", "memory"]}}), \
             patch("hermes_cli.tools_config.save_config"), \
             patch("hermes_cli.tools_config._get_platform_tools", return_value={"memory"}), \
             patch("hermes_cli.config.load_config", return_value={}), \
             patch.object(cli_obj, "new_session"), \
             patch("builtins.input") as mock_input:
            cli_obj._handle_tools_command("/tools disable web")
        mock_input.assert_not_called()

    def test_disable_always_resets_session(self):
        """Even without a confirmation prompt, disable always resets the session."""
        cli_obj = _make_cli(["web", "memory"])
        with patch("hermes_cli.tools_config.load_config",
                   return_value={"platform_toolsets": {"cli": ["web", "memory"]}}), \
             patch("hermes_cli.tools_config.save_config"), \
             patch("hermes_cli.tools_config._get_platform_tools", return_value={"memory"}), \
             patch("hermes_cli.config.load_config", return_value={}), \
             patch.object(cli_obj, "new_session") as mock_reset:
            cli_obj._handle_tools_command("/tools disable web")
        mock_reset.assert_called_once()

    def test_disable_missing_name_prints_usage(self, capsys):
        cli_obj = _make_cli()
        cli_obj._handle_tools_command("/tools disable")
        out = capsys.readouterr().out
        assert "Usage" in out


# ── /tools enable (session reset) ───────────────────────────────────────────


class TestToolsSlashEnableWithReset:

    def test_enable_applies_directly_and_resets_session(self):
        """Enable applies immediately (no confirmation prompt) and resets session."""
        cli_obj = _make_cli(["memory"])
        with patch("hermes_cli.tools_config.load_config",
                   return_value={"platform_toolsets": {"cli": ["memory"]}}), \
             patch("hermes_cli.tools_config._runtime_status_for_toolset",
                   return_value={"available": True, "reason": "available", "hint": ""}), \
             patch("hermes_cli.tools_config.save_config"), \
             patch("hermes_cli.tools_config._get_platform_tools", return_value={"memory", "web"}), \
             patch("hermes_cli.config.load_config", return_value={}), \
             patch.object(cli_obj, "new_session") as mock_reset:
            cli_obj._handle_tools_command("/tools enable web")
        mock_reset.assert_called_once()
        assert "web" in cli_obj.enabled_toolsets

    def test_enable_missing_name_prints_usage(self, capsys):
        cli_obj = _make_cli()
        cli_obj._handle_tools_command("/tools enable")
        out = capsys.readouterr().out
        assert "Usage" in out
