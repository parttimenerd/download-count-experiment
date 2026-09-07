"""
watch_counter.py — download a release, then poll until the download_count
increments, log elapsed time, and play an audible ping.

Usage:
    python3 watch_counter.py            # uses full-1 release by default
    python3 watch_counter.py --tag v-full-1 --poll 15

Runs indefinitely until the counter increments (or Ctrl-C).
Designed to be run in the background: python3 watch_counter.py &
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
    log(f"Downloading {url} ...")

    t_download_start = time.monotonic()
    bytes_recv = full_download(url)
    t_downloaded = time.monotonic()
    elapsed_download = t_downloaded - t_download_start

    log(f"Download complete: {bytes_recv:,} bytes in {elapsed_download:.1f}s")
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
            log(f"[COUNTER UPDATED] {before} → {after} — {delta_t:.0f}s after download completed")
            ping()
            ping()
            return

    log(f"Timeout after {timeout_hours}h — counter never incremented.")


if __name__ == "__main__":
    main()
