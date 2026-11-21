#!/usr/bin/env python3
"""Packaging and one-command installation verifier for Log Detective.

Creates an isolated temporary virtual environment, installs the current package via pip,
and confirms that the `logdetective` console command runs from scratch without manual intervention.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from rich.console import Console
    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False


def log(msg: str, style: str = ""):
    if HAS_RICH and console:
        console.print(f"[{style}]{msg}[/{style}]" if style else msg)
    else:
        print(msg)


def verify_one_command_install():
    repo_root = Path(__file__).resolve().parent.parent
    log("=== Verifying One-Command Installation ===", "bold cyan")
    log(f"Repository path: {repo_root}", "dim")

    with tempfile.TemporaryDirectory(prefix="logdetective_install_test_") as tmpdir:
        tmp_path = Path(tmpdir)
        venv_path = tmp_path / "venv"
        log(f"Creating isolated test virtualenv at {venv_path}...", "yellow")

        # 1. Create venv with system site packages so dependencies are available offline
        res = subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(venv_path)], capture_output=True, text=True)
        if res.returncode != 0:
            log(f"Failed to create virtualenv: {res.stderr}", "bold red")
            sys.exit(1)

        # Locate venv python and logdetective binaries
        if sys.platform == "win32":
            venv_python = venv_path / "Scripts" / "python.exe"
            venv_cli = venv_path / "Scripts" / "logdetective.exe"
            venv_pip = venv_path / "Scripts" / "pip.exe"
        else:
            venv_python = venv_path / "bin" / "python"
            venv_cli = venv_path / "bin" / "logdetective"
            venv_pip = venv_path / "bin" / "pip"

        # 2. Run pip install . (using --no-build-isolation to support offline / sandboxed test)
        log("Running 'pip install --no-build-isolation .' inside fresh virtualenv...", "yellow")
        install_res = subprocess.run(
            [str(venv_pip), "install", "--no-build-isolation", "--no-cache-dir", str(repo_root)],
            capture_output=True,
            text=True,
        )
        if install_res.returncode != 0:
            # Fallback to standard pip install if network is available
            log("Offline install failed, retrying standard pip install...", "yellow")
            install_res = subprocess.run(
                [str(venv_pip), "install", "--no-cache-dir", str(repo_root)],
                capture_output=True,
                text=True,
            )
        if install_res.returncode != 0:
            log(f"Installation failed:\n{install_res.stderr}", "bold red")
            sys.exit(1)
        log("Installation completed successfully!", "bold green")

        # 3. Test logdetective --help
        log(f"Verifying standalone '{venv_cli.name} --help' execution...", "yellow")
        cli_res = subprocess.run([str(venv_cli), "--help"], capture_output=True, text=True)
        if cli_res.returncode != 0:
            log(f"CLI invocation failed:\n{cli_res.stderr}", "bold red")
            sys.exit(1)

        assert "Terminal-Native Log Detective" in cli_res.stdout
        log("Standalone CLI command works with exit code 0!", "bold green")

        # 4. Test analyzing a sample file
        sample_log = repo_root / "tests" / "sample_logs" / "sample.log"
        if sample_log.exists():
            log(f"Testing analysis on sample log: {sample_log.name}...", "yellow")
            analyze_res = subprocess.run(
                [str(venv_cli), "analyze", str(sample_log)],
                capture_output=True,
                text=True,
            )
            if analyze_res.returncode == 0:
                log("Log analysis executed successfully via installed CLI!", "bold green")
            else:
                log(f"Log analysis returned error: {analyze_res.stderr}", "bold red")
                sys.exit(1)

        log("One-Command Installation Verified: PASS", "bold green")


if __name__ == "__main__":
    verify_one_command_install()
