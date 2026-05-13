"""Regression tests for installer repository source selection.

Running ``bash scripts/install.sh`` from a feature checkout should install from
that checkout's tracked remote/branch, while public/raw installer defaults stay
on NousResearch/main.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


def _stripped_installer_text() -> str:
    text = INSTALL_SH.read_text(encoding="utf-8")
    return re.sub(r"\nmain\s*$", "\n", text)


def test_configure_repo_source_detects_local_checkout_remote(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\nname='hermes-agent'\n", encoding="utf-8")
    installer = scripts / "install.sh"
    installer.write_text(_stripped_installer_text(), encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(["git", "checkout", "-b", "feat/local-installer"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "remote", "add", "fork", "git@github.com:example/hermes-agent.git"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(["git", "config", "branch.feat/local-installer.remote", "fork"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "config", "branch.feat/local-installer.merge", "refs/heads/feat/local-installer"],
        cwd=checkout,
        check=True,
    )

    bash = f"""
set -euo pipefail
cd {checkout}
source {installer}
configure_repo_source >/dev/null
printf 'primary=%s\n' "$REPO_URL_PRIMARY"
printf 'fallback=%s\n' "$REPO_URL_FALLBACK"
printf 'display=%s\n' "$REPO_URL_DISPLAY"
printf 'branch=%s\n' "$BRANCH"
printf 'label=%s\n' "$REPO_SOURCE_LABEL"
"""
    result = subprocess.run(["bash", "-c", bash], text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "primary=git@github.com:example/hermes-agent.git" in result.stdout
    assert "fallback=https://github.com/example/hermes-agent.git" in result.stdout
    assert "display=git@github.com:example/hermes-agent.git" in result.stdout
    assert "branch=feat/local-installer" in result.stdout
    assert "label=local checkout" in result.stdout


def test_mismatched_upstream_feature_branch_uses_local_path(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout-mismatch"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\nname='hermes-agent'\n", encoding="utf-8")
    installer = scripts / "install.sh"
    installer.write_text(_stripped_installer_text(), encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=checkout, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=checkout, check=True)
    subprocess.run(["git", "add", "pyproject.toml", "scripts/install.sh"], cwd=checkout, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:NousResearch/hermes-agent.git"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=checkout, check=True)
    subprocess.run(["git", "checkout", "-b", "feat/local-installer"], cwd=checkout, check=True)
    subprocess.run(["git", "branch", "--set-upstream-to=origin/main"], cwd=checkout, check=True)

    bash = f"""
set -euo pipefail
cd {checkout}
source {installer}
configure_repo_source >/dev/null
printf 'primary=%s\n' "$REPO_URL_PRIMARY"
printf 'fallback=%s\n' "$REPO_URL_FALLBACK"
printf 'branch=%s\n' "$BRANCH"
printf 'label=%s\n' "$REPO_SOURCE_LABEL"
"""
    result = subprocess.run(["bash", "-c", bash], text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert f"primary={checkout}" in result.stdout
    assert "fallback=" in result.stdout
    assert "branch=feat/local-installer" in result.stdout
    assert "label=local checkout path" in result.stdout


def test_clone_repo_uses_selected_source_variables() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    assert '[ -d "$candidate/.git" ] || [ -f "$candidate/.git" ]' in text
    assert 'git remote set-url origin "$REPO_URL_PRIMARY"' in text
    assert 'git remote add origin "$REPO_URL_PRIMARY"' in text
    assert 'git fetch origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"' in text
    assert 'git clone --branch "$BRANCH" "$REPO_URL_PRIMARY" "$INSTALL_DIR"' in text
    assert 'git clone --branch "$BRANCH" "$REPO_URL_FALLBACK" "$INSTALL_DIR"' in text
    assert 'git clone --branch "$BRANCH" "$REPO_URL_SSH" "$INSTALL_DIR"' not in text
    assert 'git clone --branch "$BRANCH" "$REPO_URL_HTTPS" "$INSTALL_DIR"' not in text
