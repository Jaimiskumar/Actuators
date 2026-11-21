"""Command-line interface for Log Detective."""

import json
import sys
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from logdetective.engine import Engine
from logdetective.report_html import generate_html_report
from logdetective.report_terminal import render_terminal_report

app = typer.Typer(
    name="logdetective",
    help="Terminal-Native Log Detective: Fast log clustering and crash reconstruction.",
    add_completion=False,
)
console = Console()


err_console = Console(stderr=True)


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
        help="Output HTML report path (e.g. report.html)",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="Open HTML report automatically in default browser",
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
    threshold_mb: Optional[float] = typer.Option(
        None,
        "--max-memory-mb",
        "--threshold",
        "-m",
        help="Custom memory threshold budget in MB (e.g. --threshold 100)",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Show detailed debug tracebacks",
    ),
):
    """Analyze a log file, cluster errors, and reconstruct crash timeline."""
    try:
        engine = Engine()
        result = engine.analyze(file, memory_threshold_mb=threshold_mb)

        if ai:
            from logdetective.ai import generate_ai_summary
            console.print("[dim]Analyzing incident patterns with Gemini AI...[/dim]")
            result.ai_summary = generate_ai_summary(result)

        if json_output:
            typer.echo(json.dumps(result.to_dict(), indent=2))
            return

        # Render rich terminal summary
        render_terminal_report(result, console)

        # Generate HTML report if requested or if --open is specified
        target_html = html
        if open_browser and not target_html:
            target_html = Path("report.html")

        if target_html:
            html_content = generate_html_report(result.to_dict())
            target_html.parent.mkdir(parents=True, exist_ok=True)
            target_html.write_text(html_content, encoding="utf-8")
            console.print(f"\n[bold green]✓ HTML report generated:[/bold green] [cyan]{target_html.resolve()}[/cyan]")

            if open_browser:
                console.print("[dim]Opening report in browser...[/dim]")
                webbrowser.open(f"file://{target_html.resolve()}")

    except Exception as exc:
        if debug:
            raise
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)


@app.command(name="agent")
def agent(
    file: Path = typer.Argument(
        ...,
        help="Path to log file to investigate with AI Agent",
    ),
    model: str = typer.Option("gemini-3.5-flash", "--model", help="Gemini model name"),
    threshold: Optional[float] = typer.Option(
        512.0,
        "--threshold",
        "-t",
        help="Max peak memory threshold in MB (e.g. 512, 1024, 256)",
    ),
):
    """Run interactive AI SRE Agent to investigate incident and prescribe solutions."""
    try:
        from rich.panel import Panel
        from rich.text import Text
        from logdetective.ai import investigate_incident

        engine = Engine()
        result = engine.analyze(file, memory_threshold_mb=threshold)
        console.print("\n[bold magenta]🤖 Log Detective AI SRE Agent Investigating...[/bold magenta]")
        report = investigate_incident(result, model=model)

        agent_text = Text()
        agent_text.append("📋 Summary:\n", style="bold cyan")
        agent_text.append(f"  {report['summary']}\n\n", style="white")

        agent_text.append("🎯 Patient-Zero Trigger (Root Cause):\n", style="bold yellow")
        agent_text.append(f"  {report['patient_zero']}\n\n", style="white")

        agent_text.append("💥 Cascade Mechanism:\n", style="bold red")
        agent_text.append(f"  {report['cascade_analysis']}\n\n", style="white")

        agent_text.append("🛠️ Recommended Solution (Fix):\n", style="bold green")
        agent_text.append(f"  {report['recommended_fix']}\n", style="white")

        console.print(Panel(agent_text, title="🔍 [bold white]AI INCIDENT INVESTIGATION REPORT[/bold white]", border_style="magenta"))
    except Exception as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)


@app.command(name="serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Dashboard host"),
    port: int = typer.Option(8000, "--port", help="Dashboard port"),
    open_browser: bool = typer.Option(False, "--open", help="Open dashboard automatically in browser"),
):
    """Launch local web dashboard on localhost:8000."""
    try:
        import uvicorn
        console.print(f"[bold green]Starting Log Detective local dashboard at http://{host}:{port}[/bold green]")
        if open_browser:
            webbrowser.open(f"http://{host}:{port}")
        uvicorn.run("logdetective.server:app", host=host, port=port, log_level="info")
    except ImportError as exc:
        console.print(f"[bold red]Error:[/bold red] Missing dashboard dependencies: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)


def main():
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-") and sys.argv[1] not in ("analyze", "serve", "agent"):
        sys.argv.insert(1, "analyze")
    app()


if __name__ == "__main__":
    main()
