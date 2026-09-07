"""
watch_counter.py — download a release, then poll until the download_count
increments, log elapsed time, and play an audible ping.

For --tag ending in -1: one download, then poll.
For --tag ending in -2: two downloads spaced 60s apart, then poll.
  This tests whether GitHub deduplicates same-IP downloads within a time window.

Usage:
    python3 watch_counter.py                        # full-1: single download
    python3 watch_counter.py --tag v-full-2         # full-2: two downloads 60s apart
    python3 watch_counter.py --tag v-full-1 --poll 15

Designed to be run in the background: python3 watch_counter.py --tag v-full-2 &
"""

import subprocess
import time

import click
import requests
from rich.console import Console

from config import ASSET_1MB, REPO_NAME
from gh_client import get_asset_info, get_owner

console = Console()
LOG_FILE = "watch_counter.log"
SOUND = "/System/Library/Sounds/Glass.aiff"


def ping():
    subprocess.run(["afplay", SOUND], check=False)


def log(msg):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    line = f"[{ts}] {msg}"
    console.print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


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


@click.command()
@click.option("--repo", default=REPO_NAME, show_default=True)
@click.option("--tag", default="v-full-1", show_default=True,
              help="Release tag to download and watch")
@click.option("--poll", default=15, show_default=True,
              help="Seconds between API polls")
@click.option("--timeout-hours", default=4.0, show_default=True,
              help="Give up after this many hours if counter never increments")
def main(repo, tag, poll, timeout_hours):
    owner = get_owner()
    url = f"https://github.com/{owner}/{repo}/releases/download/{tag}/{ASSET_1MB}"

    before = get_count(owner, repo, tag)
    if before is None:
        console.print(f"[red]Release {tag} not found.[/red]")
        raise SystemExit(1)

    log(f"Starting watch: repo={owner}/{repo} tag={tag} current_count={before}")

    is_run2 = tag.endswith("-2")

    log(f"Downloading {url} ...")
    t_download_start = time.monotonic()
    bytes_recv = full_download(url)
    t_downloaded = time.monotonic()
    log(f"Download 1 complete: {bytes_recv:,} bytes in {t_downloaded - t_download_start:.1f}s")

    if is_run2:
        log("Run-2 mode: waiting 60s before second download...")
        time.sleep(60)
        log(f"Downloading {url} (second time)...")
        t2_start = time.monotonic()
        bytes_recv2 = full_download(url)
        t_downloaded = time.monotonic()
        log(f"Download 2 complete: {bytes_recv2:,} bytes in {t_downloaded - t2_start:.1f}s")
        log("Both downloads done. Now polling...")
    else:
        log(f"Polling every {poll}s until counter increments (timeout: {timeout_hours}h)...")

    deadline = time.monotonic() + timeout_hours * 3600
    polls = 0

    while time.monotonic() < deadline:
        time.sleep(poll)
        polls += 1
        after = get_count(owner, repo, tag)
        elapsed_total = time.monotonic() - t_downloaded
        log(f"Poll #{polls} (+{elapsed_total:.0f}s after download): count={after}")

        if after is not None and after > before:
            delta_t = time.monotonic() - t_downloaded
            extra = " (both downloads counted)" if is_run2 and after - before > 1 else ""
            log(f"[COUNTER UPDATED] {before} → {after}{extra} — {delta_t:.0f}s after last download")
            ping()
            ping()
            return

    log(f"Timeout after {timeout_hours}h — counter never incremented.")


if __name__ == "__main__":
    main()
