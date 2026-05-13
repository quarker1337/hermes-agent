"""Regression coverage for Hermes installer install options.

These tests intentionally cover the product surface instead of only one module:
public installer flags, Python extras, setup persistence, and post-install
feature commands must agree on the same vocabulary.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _optional_deps() -> dict[str, list[str]]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["optional-dependencies"]


def test_pyproject_defines_public_install_option_and_feature_extras() -> None:
    extras = _optional_deps()

    for name in [
        "minimal",
        "standard",  # backcompat only; not advertised as an install option
        "web-search",
        "browser",
        "image-gen",
        "tts",
        "gateway",
        "dashboard",
        "web",  # hidden/backcompat alias for dashboard deps
        "termux-minimal",
        "termux",
        "termux-all",
        "all",
    ]:
        assert name in extras

    assert extras["minimal"] == ["hermes-agent[cli]", "hermes-agent[web-search]"]
    assert extras["standard"] == ["hermes-agent[minimal]"]
    assert any(dep.startswith("exa-py==") for dep in extras["exa"])
    assert extras["web-search"] == [
        "hermes-agent[exa]",
        "hermes-agent[firecrawl]",
        "hermes-agent[parallel-web]",
    ]
    assert any(dep.startswith("websockets==") for dep in extras["browser"])
    assert extras["image-gen"] == ["hermes-agent[fal]"]
    assert extras["tts"] == ["hermes-agent[edge-tts]"]
    assert extras["gateway"] == ["hermes-agent[messaging]"]
    assert extras["dashboard"] == ["hermes-agent[web]"]

    all_extra = "\n".join(extras["all"])
    assert "hermes-agent[dashboard]" in all_extra
    for lazy_feature_extra in ["web-search", "browser", "image-gen", "tts", "gateway"]:
        assert f"hermes-agent[{lazy_feature_extra}]" not in all_extra


def test_install_script_exposes_install_options_and_gates_optional_features() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    assert 'INSTALL_OPTION="${HERMES_INSTALL_OPTION:-default}"' in text
    assert "INSTALL_OPTION_EXPLICIT=false" in text
    assert "WITH_FEATURES=()" in text
    assert "--install-option NAME  Install option: default (full), minimal, minimalTUI" in text
    assert "--minimal      Alias for --install-option minimal" in text
    assert "--minimal-tui  Alias for --install-option minimalTUI" in text
    assert "--full         Backward-compatible alias for --install-option default" in text
    assert "--with FEATURE Install optional feature" in text
    assert "Valid features: browser, tts, voice, dashboard, tui, gateway, web-search, image-gen, cron, all" in text
    assert "--with web is deprecated; using --with dashboard instead" in text
    assert "--profile NAME Install profile" not in text

    assert "ADDITIVE_INSTALL=false" in text
    assert "ADDITIVE_INSTALL=true" in text
    assert "CONFIG_CREATED=false" in text
    assert "CONFIG_CREATED=true" in text
    assert "normalize_install_option()" in text
    assert "resolve_python_extras()" in text
    assert "should_check_node()" in text
    assert "should_check_ffmpeg()" in text
    assert "should_check_web_network()" in text
    assert "if should_check_node && [ \"$HAS_NODE\" = false ]; then" in text
    assert "if [ \"$INSTALL_OPTION_EXPLICIT\" = false ] && _has_any_extra_feature" in text
    assert 'has_feature "all"; then' in text
    assert 'elif has_feature "tui"; then' in text
    assert 'INSTALL_OPTION="minimal"' in text
    assert 'minimal|minimalTUI) extras+=("minimal") ;;' in text
    assert 'has_feature "dashboard" && extras+=("dashboard")' in text
    assert 'has_feature "browser" && extras+=("browser")' in text
    assert 'UV_PROJECT_ENVIRONMENT="$INSTALL_DIR/venv" $UV_CMD sync --extra all --locked' in text
    assert "--all-extras --locked" not in text
    assert 'extras+=("termux-minimal")' in text
    assert 'has_feature "dashboard" && extras+=("dashboard")' in text
    assert 'termux-minimal,dashboard' in (REPO_ROOT / "website" / "docs" / "getting-started" / "termux.md").read_text(encoding="utf-8")
    assert "Missing value for --with" in text
    assert 'setup_args+=(--install-option "$INSTALL_OPTION")' in text
    assert '[ "$INSTALL_OPTION_EXPLICIT" = true ] || [ "$CONFIG_CREATED" = true ]' in text
    assert '"${setup_args[@]}" --non-interactive' in text


def test_default_config_uses_install_option_not_install_profile() -> None:
    text = (REPO_ROOT / "hermes_cli" / "config.py").read_text(encoding="utf-8")
    assert '"install_option": "default"' in text
    assert '"toolsets": ["hermes-cli"]' in text
    assert '"install_profile"' not in text


def test_setup_install_option_persists_minimal_defaults_noninteractive(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(tmp_path / "hermes-home")
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hermes_cli.main",
            "setup",
            "--install-option",
            "minimal-tui",
            "--non-interactive",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )

    output = result.stdout + result.stderr
    assert "Profile 'minimal' does not exist" not in output
    assert "Unknown install option" not in output
    assert result.returncode == 0, output

    config_text = (Path(env["HERMES_HOME"]) / "config.yaml").read_text(encoding="utf-8")
    assert "install_option: minimalTUI" in config_text
    assert "dispatch_in_gateway: false" in config_text
    assert "- kanban" not in config_text
    for toolset in ["skills", "file", "terminal", "todo", "memory", "session_search", "clarify", "web"]:
        assert f"- {toolset}" in config_text


def test_hermes_install_feature_matches_public_installer_features() -> None:
    text = (REPO_ROOT / "hermes_cli" / "main.py").read_text(encoding="utf-8")

    assert "def cmd_install_feature(args):" in text
    assert '"browser", "tts", "voice", "dashboard", "tui", "gateway",' in text
    assert '"web-search", "image-gen", "cron", "full", "all",' in text
    assert 'aliases = {"web": "dashboard"}' in text
    assert "Feature 'web' is deprecated; installing 'dashboard' instead." in text
    assert '"--skip-setup", "--additive"' in text
    assert "hermes install-feature dashboard" in text
    assert "pip install 'hermes-agent[dashboard]'" in text
    assert "pip install 'hermes-agent[web]'" not in text


def test_docs_use_dashboard_public_feature_name() -> None:
    installation = (REPO_ROOT / "website" / "docs" / "getting-started" / "installation.md").read_text(encoding="utf-8")
    dashboard = (REPO_ROOT / "website" / "docs" / "user-guide" / "features" / "web-dashboard.md").read_text(encoding="utf-8")
    cli_ref = (REPO_ROOT / "website" / "docs" / "reference" / "cli-commands.md").read_text(encoding="utf-8")

    assert "Public feature names include `dashboard`, `browser`, `tts`, `voice`, `gateway`, `web-search`, `image-gen`, `tui`, `cron`, and `all`" in installation
    assert "pip install 'hermes-agent[dashboard,pty]'" in dashboard
    assert "pip install 'hermes-agent[web,pty]'" not in dashboard
    assert "The old `web` extra remains as a hidden backwards-compatible alias" in dashboard
    assert "| `tui` | Node package install path" in cli_ref
