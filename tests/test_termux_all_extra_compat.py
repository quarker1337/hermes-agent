"""Regression coverage for Termux installer extras."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


def test_pyproject_defines_termux_all_without_known_blockers() -> None:
    text = PYPROJECT.read_text()
    assert "termux-all = [" in text
    assert '"hermes-agent[termux]"' in text
    assert '"hermes-agent[matrix]"' not in text.split("termux-all = [", 1)[1].split("]", 1)[0]
    assert '"hermes-agent[voice]"' not in text.split("termux-all = [", 1)[1].split("]", 1)[0]


def test_install_script_maps_termux_extras_by_install_option() -> None:
    text = INSTALL_SH.read_text()
    assert "resolve_termux_extra()" in text
    assert 'extras+=("termux-all")' in text
    assert 'extras+=("termux-minimal")' in text
    assert 'extras+=("termux")' in text
    assert 'has_feature "dashboard" && extras+=("dashboard")' in text
    assert 'has_feature "gateway" && extras+=("gateway")' in text
    assert 'local termux_extra' in text
    assert 'termux_extra="$(resolve_termux_extra)"' in text
    assert "python -m pip install -e '.[$(resolve_termux_extra)]' -c constraints-termux.txt" in text
    assert 'pip install -e ".[${termux_extra}]" -c constraints-termux.txt' in text
    assert "Termux extra (.[${termux_extra}]) failed, trying baseline Termux profile..." in text
    assert "Termux baseline profile (.[termux]) failed, trying base install..." in text
