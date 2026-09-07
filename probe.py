import time

import click
import requests
from rich.console import Console
from rich.table import Table

from config import REPO_NAME
from gh_client import get_asset_info, get_owner

console = Console()

MODES = ["zero-abort", "head", "partial-1k", "partial-10k", "partial-50pct", "full"]


def snapshot(owner, repo):
    """Returns {asset_name: download_count}."""
    return {a["asset_name"]: a["download_count"] for a in get_asset_info(owner, repo)}


def do_download(mode, url, size):
    """Perform the request for the given mode. Returns bytes_received."""
    if mode == "zero-abort":
        with requests.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
            # read nothing, close immediately
        return 0

    if mode == "head":
        requests.head(url, timeout=10)
        return 0

    if mode == "partial-1k":
        r = requests.get(url, headers={"Range": "bytes=0-1023"}, timeout=10)
        return len(r.content)

    if mode == "partial-10k":
        r = requests.get(url, headers={"Range": "bytes=0-10239"}, timeout=10)
        return len(r.content)

    if mode == "partial-50pct":
        end = max(0, (size // 2) - 1)
        r = requests.get(url, headers={"Range": f"bytes=0-{end}"}, timeout=30)
        return len(r.content)

    if mode == "full":
        total = 0
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=65536):
                total += len(chunk)
        return total

    raise ValueError(f"Unknown mode: {mode}")


@click.command()
@click.option("--repo", default=REPO_NAME, show_default=True)
@click.option("--wait", default=5, show_default=True, help="Seconds to wait after each download before re-checking count")
def main(repo, wait):
    owner = get_owner()
    assets = get_asset_info(owner, repo)
    if not assets:
        console.print("[red]No assets found. Did you run setup.py?[/red]")
        raise SystemExit(1)

    table = Table(title="Probe Results — Cost per Download Count Increment")
    table.add_column("Asset", style="cyan")
    table.add_column("Mode", style="magenta")
    table.add_column("Bytes transferred", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Cost per +1", style="yellow")

    cheapest = None

    for mode in MODES:
        for asset in assets:
            asset_name = asset["asset_name"]
            url = asset["browser_download_url"]
            size = asset["size"]

            before = snapshot(owner, repo)[asset_name]
            bytes_recv = do_download(mode, url, size)

            console.print(f"  [{mode}] {asset_name}: waiting {wait}s...", end="\r")
            time.sleep(wait)

            after = snapshot(owner, repo)[asset_name]
            delta = after - before

            if delta > 0:
                cost = f"{bytes_recv:,} B / {size:,} B file ({bytes_recv / size * 100:.2f}%)"
                if cheapest is None:
                    cheapest = (mode, bytes_recv, size)
            else:
                cost = "—"

            delta_str = f"[green]+{delta}[/green]" if delta > 0 else "[dim]0[/dim]"
            table.add_row(asset_name, mode, f"{bytes_recv:,}", delta_str, cost)

    console.print(table)

    if cheapest:
        mode, b, s = cheapest
        console.print(
            f"\n[bold green]Minimum request to count:[/bold green] {mode} — "
            f"{b:,} B transferred per +1 on a {s:,} B asset "
            f"({b / s * 100:.2f}% of file size)"
        )
    else:
        console.print("\n[red]No mode incremented the counter.[/red]")


if __name__ == "__main__":
    main()
