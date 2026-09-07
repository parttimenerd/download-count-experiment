import os
import time

import click
import requests
from rich.console import Console
from rich.table import Table

from config import ASSET_1MB, MODES, REPO_NAME
from gh_client import get_asset_info, get_owner

console = Console()

SIZE_1MB = 1 * 1024 * 1024


def get_token():
    result = __import__("subprocess").run(
        ["gh", "auth", "token"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def snapshot(owner, repo):
    """Returns {tag: download_count} for the ASSET_1MB asset in each release."""
    counts = {}
    for a in get_asset_info(owner, repo):
        if a["asset_name"] == ASSET_1MB:
            counts[a["tag"]] = a["download_count"]
    return counts


def github_url(owner, repo, tag):
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{ASSET_1MB}"


def do_download(mode, owner, repo, tag, size, token):
    """Perform the request for the given mode. Returns (bytes_from_cdn, notes)."""
    url = github_url(owner, repo, tag)

    if mode == "redirect-only":
        r = requests.get(url, allow_redirects=False, timeout=10)
        return 0, f"HTTP {r.status_code}"

    if mode == "redirect-only-head":
        r = requests.head(url, allow_redirects=False, timeout=10)
        return 0, f"HTTP {r.status_code}"

    if mode == "head":
        r = requests.head(url, timeout=10)
        return 0, f"HTTP {r.status_code}"

    if mode == "zero-abort":
        with requests.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
        return 0, "stream opened, 0 bytes read"

    if mode == "partial-1k":
        r = requests.get(url, headers={"Range": "bytes=0-1023"}, timeout=10)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-10k":
        r = requests.get(url, headers={"Range": "bytes=0-10239"}, timeout=10)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-1pct":
        end = max(0, int(size * 0.01) - 1)
        r = requests.get(url, headers={"Range": f"bytes=0-{end}"}, timeout=10)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-10pct":
        end = max(0, int(size * 0.10) - 1)
        r = requests.get(url, headers={"Range": f"bytes=0-{end}"}, timeout=30)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-50pct":
        end = max(0, int(size * 0.50) - 1)
        r = requests.get(url, headers={"Range": f"bytes=0-{end}"}, timeout=30)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-99pct":
        end = max(0, int(size * 0.99) - 1)
        r = requests.get(url, headers={"Range": f"bytes=0-{end}"}, timeout=60)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "full":
        total = _stream_full(url)
        return total, f"{total:,} bytes"

    if mode == "full-auth":
        total = _stream_full(url, headers={"Authorization": f"Bearer {token}"})
        return total, f"{total:,} bytes (authed)"

    if mode == "full-repeat":
        # Download the same release twice — does counter go +1 or +2?
        total1 = _stream_full(url)
        total2 = _stream_full(url)
        return total1 + total2, f"2× full ({total1 + total2:,} bytes)"

    raise ValueError(f"Unknown mode: {mode}")


def _stream_full(url, headers=None):
    total = 0
    with requests.get(url, stream=True, timeout=120, headers=headers) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=65536):
            total += len(chunk)
    return total


@click.command()
@click.option("--repo", default=REPO_NAME, show_default=True)
@click.option("--wait", default=10, show_default=True,
              help="Seconds to wait after download before re-checking count")
@click.option("--run", default=1, type=click.Choice(["1", "2"]), show_default=True,
              help="Which run set to use (1 or 2)")
@click.option("--modes", default=None,
              help="Comma-separated subset of modes to run (default: all)")
def main(repo, wait, run, modes):
    owner = get_owner()
    token = get_token()
    size = SIZE_1MB

    mode_list = MODES
    if modes:
        mode_list = [m.strip() for m in modes.split(",")]

    all_counts = snapshot(owner, repo)

    table = Table(title=f"Probe Results (run {run}, wait={wait}s)")
    table.add_column("Mode", style="magenta")
    table.add_column("Bytes to CDN", justify="right")
    table.add_column("Notes")
    table.add_column("Before", justify="right")
    table.add_column("After", justify="right")
    table.add_column("Delta", justify="right", style="bold")
    table.add_column("Cost per +1", style="yellow")

    cheapest = None

    for mode in mode_list:
        tag = f"v-{mode}-{run}"
        if tag not in all_counts:
            console.print(f"[red]Release {tag} not found — did you run setup.py?[/red]")
            continue

        before = all_counts[tag]
        bytes_recv, notes = do_download(mode, owner, repo, tag, size, token)

        console.print(f"  [{mode}] waiting {wait}s...", end="\r")
        time.sleep(wait)

        after = snapshot(owner, repo).get(tag, before)
        delta = after - before

        if delta > 0:
            cost = f"{bytes_recv:,} B ({bytes_recv / size * 100:.3f}%)" if bytes_recv > 0 else "0 B (!))"
            if cheapest is None:
                cheapest = (mode, bytes_recv, size)
        else:
            cost = "—"

        delta_str = f"[green]+{delta}[/green]" if delta > 0 else "[dim]0[/dim]"
        table.add_row(mode, f"{bytes_recv:,}", notes, str(before), str(after), delta_str, cost)

    console.print(table)

    if cheapest:
        mode, b, s = cheapest
        pct = f"{b / s * 100:.3f}%" if b > 0 else "0 bytes"
        console.print(
            f"\n[bold green]Cheapest counting mode:[/bold green] {mode} — "
            f"{b:,} B transferred ({pct} of {s:,} B asset)"
        )
    else:
        console.print("\n[yellow]No mode incremented the counter during this run.[/yellow]")
        console.print("[dim]GitHub uses a ~2h cache. Wait before re-running, or use --run 2.[/dim]")


if __name__ == "__main__":
    main()
