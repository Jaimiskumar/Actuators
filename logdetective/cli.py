"""Command-line interface for Log Detective."""

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="logdetective",
    help="Terminal-Native Log Detective: Fast log clustering and crash reconstruction.",
    add_completion=False,
)
console = Console()


@app.command(name="analyze")
def analyze(
    file: Path = typer.Argument(
        ...,
        help="Path to log file (.log, .gz, or '-' for stdin)",
        exists=False,
    ),
    html: Optional[Path] = typer.Option(
        None,
        "--html",
        help="Output HTML report path",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="Open HTML report automatically in browser",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output raw Result JSON to stdout",
    ),
    ai: bool = typer.Option(
        False,
        "--ai",
        help="Generate AI root cause summary (requires GEMINI_API_KEY)",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Show detailed debug tracebacks",
    ),
):
    """Analyze a log file, cluster errors, and reconstruct crash timeline."""
    try:
        # Phase 1 scaffold: placeholder indicating engine invocation
        console.print(f"[bold cyan]Log Detective[/bold cyan] analyzing [yellow]{file}[/yellow]...")
        console.print("[dim]Phase 1 Skeleton active. Engine pipeline is scheduled in Phase 2/3.[/dim]")
    except Exception as exc:
        if debug:
            raise
        console.print(f"[bold red]Error:[/bold red] {exc}", file=sys.stderr)
        raise typer.Exit(code=1)


@app.command(name="serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Dashboard host"),
    port: int = typer.Option(8000, "--port", help="Dashboard port"),
):
    """Launch local web dashboard."""
    console.print(f"[bold green]Starting Log Detective local dashboard at http://{host}:{port}[/bold green]")
    console.print("[dim]Dashboard backend will be mounted in Phase 5.[/dim]")


def main():
    # If invoked directly with a file as first argument, default to analyze
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-") and sys.argv[1] not in ("analyze", "serve"):
        sys.argv.insert(1, "analyze")
    app()


if __name__ == "__main__":
    main()
