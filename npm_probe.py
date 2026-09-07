"""
npm_probe.py — test which HTTP request types npm counts as a download.

npm serves tarballs directly (no redirect), so we test whether the counter
fires at connection time or only after bytes are delivered.

Stats only update daily after UTC midnight. Run downloads today, check
stats tomorrow with --stats-only.

Usage:
    python3 npm_probe.py                 # run all download modes
    python3 npm_probe.py --stats-only    # just print current stats
"""

import json
import subprocess
import time
from datetime import datetime, timezone

import click
import requests
from rich.console import Console
from rich.table import Table

console = Console()

PACKAGE = "download-count-experiment"
VERSION = "1.0.0"
TARBALL_URL = f"https://registry.npmjs.org/{PACKAGE}/-/{PACKAGE}-{VERSION}.tgz"
STATS_URL = f"https://api.npmjs.org/downloads/point/last-day/{PACKAGE}"
LOG_FILE = "npm_probe.log"

MODES = [
    "head",           # HEAD — no body
    "zero-abort",     # connect, read 0 bytes, close
    "partial-1k",     # Range: bytes=0-1023
    "partial-10k",    # Range: bytes=0-10239
    "partial-1pct",   # 1% of tarball
    "partial-50pct",  # 50%
    "full",           # entire tarball
]


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    console.print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_stats():
    r = requests.get(STATS_URL, timeout=10)
    if r.status_code == 200:
        return r.json().get("downloads", 0)
    return None


def get_tarball_size():
    r = requests.head(TARBALL_URL, timeout=10)
    cl = r.headers.get("Content-Length")
    return int(cl) if cl else None


def do_download(mode, size):
    """Perform the request for the given mode. Returns (bytes_received, notes)."""
    if mode == "head":
        r = requests.head(TARBALL_URL, timeout=10)
        return 0, f"HTTP {r.status_code}"

    if mode == "zero-abort":
        with requests.get(TARBALL_URL, stream=True, timeout=10) as r:
            r.raise_for_status()
        return 0, "stream opened, 0 bytes read"

    if mode == "partial-1k":
        r = requests.get(TARBALL_URL, headers={"Range": "bytes=0-1023"}, timeout=10)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-10k":
        r = requests.get(TARBALL_URL, headers={"Range": "bytes=0-10239"}, timeout=10)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-1pct":
        end = max(0, int((size or 0) * 0.01) - 1)
        r = requests.get(TARBALL_URL, headers={"Range": f"bytes=0-{end}"}, timeout=10)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-50pct":
        end = max(0, int((size or 0) * 0.50) - 1)
        r = requests.get(TARBALL_URL, headers={"Range": f"bytes=0-{end}"}, timeout=30)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "full":
        total = 0
        with requests.get(TARBALL_URL, stream=True, timeout=60) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=65536):
                total += len(chunk)
        return total, f"{total:,} bytes"

    raise ValueError(f"Unknown mode: {mode}")


@click.command()
@click.option("--stats-only", is_flag=True, help="Just print current download stats")
@click.option("--modes", "modes_override", default=None,
              help="Comma-separated subset of modes (default: all)")
def main(stats_only, modes_override):
    stats = get_stats()
    console.print(f"\n[bold]Package:[/bold] {PACKAGE}@{VERSION}")
    console.print(f"[bold]Tarball:[/bold] {TARBALL_URL}")
    console.print(f"[bold]Current stats (last-day):[/bold] {stats} downloads")
    console.print("[dim]Note: npm stats update daily after UTC midnight.[/dim]\n")

    if stats_only:
        return

    size = get_tarball_size()
    console.print(f"[bold]Tarball size:[/bold] {size:,} bytes\n" if size else "[yellow]Could not determine tarball size.[/yellow]\n")

    mode_list = MODES
    if modes_override:
        mode_list = [m.strip() for m in modes_override.split(",")]

    table = Table(title=f"npm Probe Results — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    table.add_column("Mode", style="magenta")
    table.add_column("Bytes received", justify="right")
    table.add_column("Notes")
    table.add_column("% of tarball", justify="right")

    log(f"Starting npm probe: {len(mode_list)} modes, tarball size={size}")

    for mode in mode_list:
        console.print(f"  [{mode}] downloading...", end=" ")
        t = time.monotonic()
        bytes_recv, notes = do_download(mode, size)
        elapsed = time.monotonic() - t
        pct = f"{bytes_recv / size * 100:.2f}%" if size and bytes_recv > 0 else ("0%" if bytes_recv == 0 else "?")
        console.print(f"{bytes_recv:,} B ({elapsed:.1f}s)")
        log(f"mode={mode} bytes={bytes_recv} notes={notes} pct={pct}")
        table.add_row(mode, f"{bytes_recv:,}", notes, pct)

    console.print(table)
    console.print(f"\n[bold]Downloads logged to {LOG_FILE}[/bold]")
    console.print(f"\n[dim]Stats update after UTC midnight. Re-run tomorrow:[/dim]")
    console.print(f"[dim]  python3 npm_probe.py --stats-only[/dim]")
    console.print(f"\n[dim]Or check directly:[/dim]")
    console.print(f"[dim]  curl -s '{STATS_URL}' | python3 -m json.tool[/dim]")


if __name__ == "__main__":
    main()
