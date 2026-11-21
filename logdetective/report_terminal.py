"""Terminal output rendering using Rich for Log Detective."""

import webbrowser
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from logdetective.contract import Result


def render_terminal_report(result: Result, console: Optional[Console] = None):
    """Render full incident analysis report to the terminal using Rich."""
    if console is None:
        console = Console()

    meta = result.meta

    # 1. Stats Panel
    stats_text = Text()
    stats_text.append(f"File: ", style="bold cyan")
    stats_text.append(f"{meta.file} ({meta.size_bytes / (1024*1024):.2f} MB)\n")
    stats_text.append(f"Ingestion: ", style="bold cyan")
    stats_text.append(f"{meta.lines:,} lines ({meta.events:,} events) processed in {meta.duration_s:.2f}s\n")
    throughput = int(meta.lines / meta.duration_s) if meta.duration_s > 0 else 0
    stats_text.append(f"Throughput: ", style="bold cyan")
    stats_text.append(f"{throughput:,} lines/sec  |  Peak Memory: {meta.peak_mem_mb:.1f} MB\n")

    if meta.memory_threshold_mb is not None:
        if meta.budget_exceeded:
            stats_text.append(f"Memory Budget: ", style="bold red")
            stats_text.append(f"{meta.peak_mem_mb:.1f} MB / {meta.memory_threshold_mb:.1f} MB budget (EXCEEDED)\n", style="red")
        else:
            stats_text.append(f"Memory Budget: ", style="bold green")
            stats_text.append(f"{meta.peak_mem_mb:.1f} MB / {meta.memory_threshold_mb:.1f} MB budget (MAINTAINED)\n", style="green")
    
    if meta.time_range and meta.time_range[0] and meta.time_range[1]:
        stats_text.append(f"Time Range: ", style="bold cyan")
        stats_text.append(f"{meta.time_range[0]}  ->  {meta.time_range[1]}\n")

    # Level breakdown summary
    lvl_str = "  ".join(
        f"[{_level_color(k)}]{k}: {v:,}[/{_level_color(k)}]"
        for k, v in meta.level_counts.items()
        if v > 0
    )
    stats_text.append(f"Breakdown: ", style="bold cyan")
    stats_text.append(Text.from_markup(lvl_str))

    console.print(Panel(stats_text, title="[bold white]LOG DETECTIVE ANALYSIS[/bold white]", border_style="cyan"))

    # 2. Clusters Table
    if not result.clusters:
        console.print("[bold green]No errors or warnings found in log file.[/bold green]\n")
        return

    table = Table(title="[bold white]TOP ERROR CLUSTERS[/bold white]", border_style="dim", expand=True)
    table.add_column("ID", style="bold yellow", width=6)
    table.add_column("Level", width=8)
    table.add_column("Count", justify="right", style="bold red", width=9)
    table.add_column("Pattern Template", style="white")
    table.add_column("First Seen", style="dim cyan", width=22)

    for c in result.clusters[:8]:
        lvl_styled = f"[{_level_color(c.level)}]{c.level}[/{_level_color(c.level)}]"
        first_seen_str = f"L{c.first_seen.line_no}"
        if c.first_seen.ts:
            first_seen_str += f" ({c.first_seen.ts[11:19]})"

        table.add_row(
            c.id,
            lvl_styled,
            f"{c.count:,}",
            c.template,
            first_seen_str,
        )

    console.print(table)

    # 3. First Occurrence Highlights
    console.print("\n[bold white]PATIENT-ZERO FAILURES (First Occurrences)[/bold white]")
    for c in result.clusters[:4]:
        fo = c.first_seen
        ts_part = f"at {fo.ts} " if fo.ts else ""
        console.print(
            f"  • [bold yellow]{c.id}[/bold yellow] ([{_level_color(c.level)}]{c.level}[/{_level_color(c.level)}]) "
            f"first seen at [bold cyan]Line {fo.line_no}[/bold cyan] {ts_part}\n"
            f"    [dim]Sample:[/dim] [white]{c.sample}[/white]"
        )

    # 4. Crash Timeline Reconstruction
    if result.crashes:
        console.print(f"\n[bold red]CRASH SEQUENCE RECONSTRUCTION ({len(result.crashes)} Crash Events Detected)[/bold red]")
        for idx, crash in enumerate(result.crashes[:2], start=1):
            ts_str = f"at {crash.trigger.ts} " if crash.trigger.ts else ""
            console.print(f"\n  [bold red]Crash #{idx}:[/bold red] Line {crash.trigger.line_no} {ts_str}")
            console.print(f"  [bold red]Trigger:[/bold red] [white on red] {crash.trigger.message} [/white on red]")
            console.print("  [dim]Pre-crash cascade (ordered chronological events):[/dim]")

            for step in crash.sequence:
                ts_step = f"[{step.ts[11:19]}] " if step.ts and len(step.ts) >= 19 else ""
                lvl_tag = f"[{_level_color(step.level)}]{step.level:<5}[/{_level_color(step.level)}]"
                
                if step.is_trigger:
                    marker = "[bold red]TRIGGER ->[/bold red]"
                    console.print(f"    {marker} {ts_step}{lvl_tag} [bold red]{step.message}[/bold red]")
                elif step.is_first_occurrence:
                    marker = "[bold yellow]ROOT FO ->[/bold yellow]"
                    console.print(f"    {marker} {ts_step}{lvl_tag} [yellow]{step.message}[/yellow]")
                else:
                    marker = "   [dim]↳[/dim]       "
                    console.print(f"    {marker} {ts_step}{lvl_tag} [dim]{step.message}[/dim]")

    # 5. AI Root Cause Summary (if generated)
    if result.ai_summary:
        console.print()
        console.print(
            Panel(
                Text(result.ai_summary, style="white"),
                title="[bold magenta]AI ROOT CAUSE SUMMARY (Gemini)[/bold magenta]",
                border_style="magenta",
            )
        )


def _level_color(level: str) -> str:
    lvl = level.upper()
    if lvl == "FATAL":
        return "bold red"
    if lvl == "ERROR":
        return "red"
    if lvl == "WARN":
        return "yellow"
    if lvl == "INFO":
        return "green"
    if lvl == "DEBUG":
        return "blue"
    return "dim white"
