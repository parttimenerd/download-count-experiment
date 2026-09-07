"""
timing.py — repeatedly download a dedicated release and measure how long
GitHub takes to increment the download counter each time.

Produces:
  timing_results.csv   — one row per download: download_number, downloaded_at,
                         counted_at, delay_seconds
  timing_histogram.png — histogram of delay_seconds across all observations

The same release is reused across runs (counts accumulate). Each run appends
to the CSV so you can collect data over multiple sessions.

Usage:
    python3 timing.py                      # 10 samples, poll every 15s
    python3 timing.py --samples 20 --poll 15
    python3 timing.py --plot-only          # regenerate histogram from existing CSV
"""

import csv
import os
import time
from datetime import datetime, timezone

import click
import matplotlib.pyplot as plt
import requests
from rich.console import Console
from rich.table import Table

from config import ASSET_1MB, REPO_NAME, TIMING_TAG
from gh_client import get_asset_info, get_owner

console = Console()

SIZE_1MB = 1 * 1024 * 1024
CSV_FILE = "timing_results.csv"
PLOT_FILE = "timing_histogram.png"
CSV_FIELDS = ["download_number", "downloaded_at", "counted_at", "delay_seconds"]


def get_count(owner, repo, tag):
    for a in get_asset_info(owner, repo):
        if a["asset_name"] == ASSET_1MB and a["tag"] == tag:
            return a["download_count"]
    return None


def full_download(url):
    total = 0
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=65536):
            total += len(chunk)
    return total


def read_existing_csv():
    if not os.path.exists(CSV_FILE):
        return []
    with open(CSV_FILE, newline="") as f:
        return list(csv.DictReader(f))


def append_csv(row):
    exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(row)


def plot_histogram(rows):
    delays = [float(r["delay_seconds"]) for r in rows if r["delay_seconds"]]
    if len(delays) < 2:
        console.print("[yellow]Need at least 2 data points to plot.[/yellow]")
        return

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(delays, bins=max(5, len(delays) // 2), edgecolor="black", color="steelblue")
    ax.set_xlabel("Delay from download completion to counter update (seconds)")
    ax.set_ylabel("Count")
    ax.set_title(
        f"GitHub download counter update delay\n"
        f"n={len(delays)}, "
        f"median={sorted(delays)[len(delays)//2]:.0f}s, "
        f"min={min(delays):.0f}s, max={max(delays):.0f}s"
    )
    ax.axvline(sorted(delays)[len(delays) // 2], color="red", linestyle="--", label="median")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOT_FILE, dpi=150)
    console.print(f"[green]Histogram saved to {PLOT_FILE}[/green]")


@click.command()
@click.option("--repo", default=REPO_NAME, show_default=True)
@click.option("--tag", default=TIMING_TAG, show_default=True)
@click.option("--samples", default=10, show_default=True,
              help="Number of downloads to perform in this run")
@click.option("--poll", default=15, show_default=True,
              help="Seconds between API polls while waiting for counter")
@click.option("--timeout-minutes", default=60, show_default=True,
              help="Per-sample timeout in minutes")
@click.option("--plot-only", is_flag=True,
              help="Skip downloading; regenerate histogram from existing CSV")
def main(repo, tag, samples, poll, timeout_minutes, plot_only):
    existing = read_existing_csv()

    if plot_only:
        if not existing:
            console.print(f"[red]No data in {CSV_FILE}.[/red]")
            raise SystemExit(1)
        plot_histogram(existing)
        return

    owner = get_owner()
    url = f"https://github.com/{owner}/{repo}/releases/download/{tag}/{ASSET_1MB}"

    if get_count(owner, repo, tag) is None:
        console.print(f"[red]Release {tag} not found. Run setup.py first.[/red]")
        raise SystemExit(1)

    download_number = len(existing) + 1
    console.print(f"[bold]Timing run:[/bold] {samples} samples starting at download #{download_number}")
    console.print(f"[bold]Tag:[/bold] {tag} | [bold]Poll:[/bold] {poll}s | [bold]Timeout:[/bold] {timeout_minutes}m\n")

    session_rows = []

    for i in range(samples):
        n = download_number + i
        console.print(f"[bold]Sample {i+1}/{samples} (download #{n})[/bold]")

        before = get_count(owner, repo, tag)
        console.print(f"  Count before: {before}")

        t_start = time.monotonic()
        bytes_recv = full_download(url)
        downloaded_at = datetime.now(timezone.utc)
        t_done = time.monotonic()
        console.print(f"  Downloaded {bytes_recv:,} bytes in {t_done - t_start:.1f}s at {downloaded_at.strftime('%H:%M:%S')}")

        # Poll until counter increments
        deadline = time.monotonic() + timeout_minutes * 60
        delay = None
        polls = 0
        while time.monotonic() < deadline:
            time.sleep(poll)
            polls += 1
            after = get_count(owner, repo, tag)
            elapsed = time.monotonic() - t_done
            console.print(f"  Poll #{polls} (+{elapsed:.0f}s): count={after}", end="\r")
            if after is not None and after > before:
                delay = time.monotonic() - t_done
                counted_at = datetime.now(timezone.utc)
                console.print(f"  Poll #{polls} (+{elapsed:.0f}s): count={after} [green]✓[/green]")
                break
        else:
            console.print(f"\n  [yellow]Timeout — counter didn't update within {timeout_minutes}m[/yellow]")
            counted_at = None

        row = {
            "download_number": n,
            "downloaded_at": downloaded_at.isoformat(),
            "counted_at": counted_at.isoformat() if counted_at else "",
            "delay_seconds": f"{delay:.1f}" if delay is not None else "",
        }
        append_csv(row)
        session_rows.append(row)
        console.print(f"  Delay: [bold]{'%.1f' % delay if delay is not None else 'timeout'}s[/bold]\n")

    # Print session summary table
    all_rows = read_existing_csv()
    completed = [r for r in all_rows if r["delay_seconds"]]
    delays = [float(r["delay_seconds"]) for r in completed]

    table = Table(title=f"Results so far ({len(completed)} completed samples)")
    table.add_column("#", justify="right")
    table.add_column("Downloaded at")
    table.add_column("Delay (s)", justify="right")
    for r in all_rows[-20:]:  # show last 20
        d = r["delay_seconds"] or "timeout"
        style = "green" if r["delay_seconds"] else "yellow"
        table.add_row(r["download_number"], r["downloaded_at"][11:19], f"[{style}]{d}[/{style}]")
    console.print(table)

    if delays:
        s = sorted(delays)
        console.print(
            f"min={s[0]:.0f}s  median={s[len(s)//2]:.0f}s  max={s[-1]:.0f}s  "
            f"mean={sum(delays)/len(delays):.0f}s  n={len(delays)}"
        )
        plot_histogram(all_rows)
    else:
        console.print("[yellow]No completed samples yet — no histogram.[/yellow]")


if __name__ == "__main__":
    main()
