"""Regression tests for install.sh repository source selection.

The public installer must keep defaulting to NousResearch/main when fetched via
curl/raw, but running scripts/install.sh directly from a fork/feature checkout
must be able to install that checkout's tracked remote/branch. Otherwise local
pre-merge smoke installs silently update ~/.hermes/hermes-agent from upstream
main and the user never sees the branch changes they are testing.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


def _write_install_lib(path: Path) -> None:
    text = INSTALL_SH.read_text()
    text = re.sub(r"\nmain\s*$", "\n", text)
    assert "main\n" not in text[-20:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Hermes Test",
            "GIT_AUTHOR_EMAIL": "hermes-test@example.com",
            "GIT_COMMITTER_NAME": "Hermes Test",
            "GIT_COMMITTER_EMAIL": "hermes-test@example.com",
        }
    )
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _init_repo(path: Path, marker: str) -> None:
    path.mkdir(parents=True)
    _run(["git", "init", "-b", "main"], cwd=path)
    (path / "pyproject.toml").write_text("[project]\nname = 'hermes-test'\nversion = '0'\n")
    (path / "marker.txt").write_text(marker)
    _run(["git", "add", "."], cwd=path)
    _run(["git", "commit", "-m", "initial"], cwd=path)


def test_direct_checkout_uses_tracked_remote_and_branch(tmp_path: Path) -> None:
    remote = tmp_path / "fork.git"
    work = tmp_path / "checkout"
    _run(["git", "init", "--bare", str(remote)])
    _init_repo(work, "feature branch\n")
    _run(["git", "checkout", "-b", "feat/installer-source"], cwd=work)
    _run(["git", "remote", "add", "fork", str(remote)], cwd=work)
    _run(["git", "push", "-u", "fork", "feat/installer-source"], cwd=work)

    install_lib = work / "scripts" / "install.sh"
    _write_install_lib(install_lib)

    probe = tmp_path / "probe.sh"
    probe.write_text(
        f"""
set -e
source {install_lib}
configure_repo_source
printf 'branch=%s\n' "$BRANCH"
printf 'primary=%s\n' "$REPO_URL_PRIMARY"
printf 'fallback=%s\n' "$REPO_URL_FALLBACK"
printf 'label=%s\n' "$REPO_SOURCE_LABEL"
"""
    )

    result = _run(["bash", str(probe)])

    assert "branch=feat/installer-source" in result.stdout
    assert f"primary={remote}" in result.stdout
    assert "fallback=\n" in result.stdout
    assert f"label=local checkout ({work})" in result.stdout


def test_existing_upstream_install_updates_from_checkout_branch(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream.git"
    fork = tmp_path / "fork.git"
    upstream_work = tmp_path / "upstream-work"
    fork_work = tmp_path / "fork-work"
    install_dir = tmp_path / "install"

    _run(["git", "init", "--bare", str(upstream)])
    _run(["git", "init", "--bare", str(fork)])

    _init_repo(upstream_work, "upstream main\n")
    _run(["git", "remote", "add", "origin", str(upstream)], cwd=upstream_work)
    _run(["git", "push", "-u", "origin", "main"], cwd=upstream_work)

    _run(["git", "clone", "--branch", "main", str(upstream), str(fork_work)])
    _run(["git", "checkout", "-b", "feat/installer-source"], cwd=fork_work)
    (fork_work / "marker.txt").write_text("fork feature\n")
    _run(["git", "commit", "-am", "feature marker"], cwd=fork_work)
    _run(["git", "remote", "add", "fork", str(fork)], cwd=fork_work)
    _run(["git", "push", "-u", "fork", "feat/installer-source"], cwd=fork_work)

    _run(["git", "clone", "--branch", "main", str(upstream), str(install_dir)])
    assert (install_dir / "marker.txt").read_text() == "upstream main\n"

    install_lib = fork_work / "scripts" / "install.sh"
    _write_install_lib(install_lib)

    probe = tmp_path / "probe-update.sh"
    probe.write_text(
        f"""
set -e
source {install_lib}
configure_repo_source
INSTALL_DIR={install_dir}
clone_repo >/tmp/hermes-install-source-selection.log
printf 'marker=%s' "$(cat {install_dir / 'marker.txt'})"
printf '\nbranch=%s\n' "$(git -C {install_dir} branch --show-current)"
printf 'origin=%s\n' "$(git -C {install_dir} remote get-url origin)"
"""
    )

    result = _run(["bash", str(probe)])

    assert "marker=fork feature" in result.stdout
    assert "branch=feat/installer-source" in result.stdout
    assert f"origin={fork}" in result.stdout


def test_public_defaults_remain_upstream_and_repo_override_is_documented() -> None:
    text = INSTALL_SH.read_text()

    assert 'DEFAULT_REPO_URL_HTTPS="https://github.com/NousResearch/hermes-agent.git"' in text
    assert 'DEFAULT_REPO_URL_SSH="git@github.com:NousResearch/hermes-agent.git"' in text
    assert "--repo URL|PATH" in text
    assert "configure_repo_source" in text
    assert "detect_installer_repo_root" in text
    assert "git remote set-url origin \"$REPO_URL_PRIMARY\"" in text
