"""Packaging and installation tests for Log Detective."""

import subprocess
import sys
from pathlib import Path
import pytest


def test_cli_help_execution():
    """Verify that logdetective CLI runs and displays help text cleanly."""
    result = subprocess.run(
        [sys.executable, "-m", "logdetective.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Terminal-Native Log Detective" in result.stdout
    assert "analyze" in result.stdout
    assert "serve" in result.stdout


def test_cli_main_entrypoint():
    """Verify that main function exists and is callable in logdetective.cli."""
    from logdetective.cli import main, app
    assert callable(main)
    assert app is not None


def test_package_modules_import():
    """Verify that all core modules import cleanly without side-effects."""
    import logdetective
    import logdetective.contract
    import logdetective.reader
    import logdetective.parser
    import logdetective.stacktrace
    import logdetective.cli

    assert logdetective.__name__ == "logdetective"


def test_pyproject_toml_configuration():
    """Verify pyproject.toml specifies correct script entry point and metadata."""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    assert pyproject_path.exists()
    content = pyproject_path.read_text(encoding="utf-8")
    assert 'name = "logdetective"' in content
    assert 'logdetective = "logdetective.cli:main"' in content
    assert "typer" in content
    assert "rich" in content


def test_wheel_build(tmp_path):
    """Verify that a distributable wheel can be built cleanly."""
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "-w",
            str(tmp_path),
            str(repo_root),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    assert wheels[0].name.startswith("logdetective-0.1.0")
