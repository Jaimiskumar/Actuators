#!/usr/bin/env python3
"""Download real-world open-source log samples from Loghub for judging and benchmarking validation.

Datasets provided by LogPAI Loghub (https://github.com/logpai/loghub).
Includes real production logs from distributed systems, web servers, and operating systems:
- HDFS (Hadoop Distributed File System)
- Apache (Apache HTTP Server)
- BGL (Blue Gene/L supercomputer log)
- Hadoop (Hadoop mapreduce job logs)
- Spark (Apache Spark framework log)
- Linux (Linux system logs)
- ZooKeeper (Apache ZooKeeper distributed coordination service)
"""

import argparse
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Optional

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from rich.console import Console
    from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn, TransferSpeedColumn
    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False

LOGHUB_BASE_URL = "https://raw.githubusercontent.com/logpai/loghub/master"

# Curated standard datasets suitable for fast downloading and validation
DATASETS = {
    "hdfs": {
        "name": "HDFS",
        "description": "Hadoop Distributed File System log (2,000 real-world events with block transactions and exceptions)",
        "url": f"{LOGHUB_BASE_URL}/HDFS/HDFS_2k.log",
        "filename": "HDFS_2k.log",
    },
    "apache": {
        "name": "Apache",
        "description": "Apache Web Server error & access logs (notices, worker errors, mod_jk child states)",
        "url": f"{LOGHUB_BASE_URL}/Apache/Apache_2k.log",
        "filename": "Apache_2k.log",
    },
    "bgl": {
        "name": "BGL",
        "description": "BlueGene/L Supercomputer log with hardware failures and fatal kernel alerts",
        "url": f"{LOGHUB_BASE_URL}/BGL/BGL_2k.log",
        "filename": "BGL_2k.log",
    },
    "hadoop": {
        "name": "Hadoop",
        "description": "Hadoop MapReduce log records (task tracker failures, connection retries)",
        "url": f"{LOGHUB_BASE_URL}/Hadoop/Hadoop_2k.log",
        "filename": "Hadoop_2k.log",
    },
    "spark": {
        "name": "Spark",
        "description": "Apache Spark application and driver execution logs",
        "url": f"{LOGHUB_BASE_URL}/Spark/Spark_2k.log",
        "filename": "Spark_2k.log",
    },
    "linux": {
        "name": "Linux",
        "description": "Standard Linux syslog entries (/var/log/messages)",
        "url": f"{LOGHUB_BASE_URL}/Linux/Linux_2k.log",
        "filename": "Linux_2k.log",
    },
    "zookeeper": {
        "name": "ZooKeeper",
        "description": "Apache ZooKeeper coordination service state logs",
        "url": f"{LOGHUB_BASE_URL}/ZooKeeper/ZooKeeper_2k.log",
        "filename": "ZooKeeper_2k.log",
    },
}


def create_ssl_context() -> ssl.SSLContext:
    """Create an SSL context that gracefully falls back if default certificates are missing."""
    ctx = ssl.create_default_context()
    try:
        # Check if default CA certificates can be loaded
        ctx.load_default_certs()
    except Exception:
        # If running in restricted or proxy environment without local CA bundle
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def download_dataset(
    dataset_key: str,
    output_dir: Path = Path("tests/sample_logs"),
    force: bool = False,
    show_progress: bool = True,
) -> Path:
    """Download a specified Loghub dataset to output_dir and return the local path."""
    key = dataset_key.lower().strip()
    if key not in DATASETS:
        valid_keys = ", ".join(DATASETS.keys())
        raise ValueError(f"Unknown dataset '{dataset_key}'. Available datasets: {valid_keys}")

    meta = DATASETS[key]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / meta["filename"]

    if target_path.exists() and not force and target_path.stat().st_size > 0:
        if show_progress:
            msg = f"[green]Using existing cached sample:[/green] [cyan]{target_path}[/cyan] ({target_path.stat().st_size:,} bytes)"
            if HAS_RICH and console:
                console.print(msg)
            else:
                print(f"Using existing cached sample: {target_path} ({target_path.stat().st_size:,} bytes)")
        return target_path

    url = meta["url"]
    if show_progress:
        msg = f"[bold cyan]Downloading Loghub dataset '{meta['name']}'[/bold cyan] from [yellow]{url}[/yellow]..."
        if HAS_RICH and console:
            console.print(msg)
        else:
            print(f"Downloading Loghub dataset '{meta['name']}' from {url}...")

    ctx = create_ssl_context()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; LogDetectiveBenchmark/1.0)"},
    )

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            content = resp.read()
            if not content:
                raise RuntimeError(f"Downloaded empty response from {url}")
            target_path.write_bytes(content)
    except Exception as exc:
        raise RuntimeError(f"Failed to download dataset '{key}' from {url}: {exc}") from exc

    size_bytes = target_path.stat().st_size
    line_count = sum(1 for _ in target_path.open("r", encoding="utf-8", errors="replace"))

    if show_progress:
        msg = (
            f"[bold green]Successfully downloaded {meta['name']} log sample:[/bold green] "
            f"[cyan]{target_path}[/cyan] ({line_count:,} lines, {size_bytes:,} bytes)"
        )
        if HAS_RICH and console:
            console.print(msg)
        else:
            print(f"Successfully downloaded {meta['name']} log sample: {target_path} ({line_count:,} lines, {size_bytes:,} bytes)")

    return target_path


def list_available_datasets() -> dict[str, dict[str, str]]:
    """Return dictionary of available datasets."""
    return DATASETS.copy()


def main():
    parser = argparse.ArgumentParser(
        description="Download real-world Loghub datasets (HDFS, Apache, BGL, etc.) for Log Detective validation."
    )
    parser.add_argument(
        "--dataset",
        "-d",
        default="hdfs",
        help=f"Dataset name to download ({', '.join(DATASETS.keys())}, or 'all')",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("tests/sample_logs"),
        help="Destination directory (default: tests/sample_logs)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force re-download even if cached file exists",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available datasets and exit",
    )

    args = parser.parse_args()

    if args.list:
        if HAS_RICH and console:
            from rich.table import Table
            table = Table(title="Available Real-World Loghub Datasets", title_style="bold green")
            table.add_column("Key", style="bold cyan", width=12)
            table.add_column("Name", style="yellow", width=12)
            table.add_column("Description", style="white")
            for k, info in DATASETS.items():
                table.add_row(k, info["name"], info["description"])
            console.print(table)
        else:
            print("Available Real-World Loghub Datasets:")
            for k, info in DATASETS.items():
                print(f"  {k:12} {info['name']:12} {info['description']}")
        return

    datasets_to_download = list(DATASETS.keys()) if args.dataset.lower() == "all" else [args.dataset.lower()]

    for ds in datasets_to_download:
        try:
            download_dataset(ds, output_dir=args.output_dir, force=args.force)
        except Exception as exc:
            print(f"Error downloading {ds}: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
