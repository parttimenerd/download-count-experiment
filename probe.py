import time
from datetime import datetime

import click
import requests
from rich.console import Console
from rich.table import Table

from config import ASSET_1MB, MODES, REPO_NAME
from gh_client import get_asset_info, get_owner

console = Console()

SIZE_1MB = 1 * 1024 * 1024


def get_token():
    import subprocess
    result = subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def snapshot_all(owner, repo):
    """Returns {tag: download_count} for all ASSET_1MB assets."""
    return {
        a["tag"]: a["download_count"]
        for a in get_asset_info(owner, repo)
        if a["asset_name"] == ASSET_1MB
    }


def github_url(owner, repo, tag):
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{ASSET_1MB}"


def do_download(mode, owner, repo, tag, token):
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
        end = max(0, int(SIZE_1MB * 0.01) - 1)
        r = requests.get(url, headers={"Range": f"bytes=0-{end}"}, timeout=10)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-10pct":
        end = max(0, int(SIZE_1MB * 0.10) - 1)
        r = requests.get(url, headers={"Range": f"bytes=0-{end}"}, timeout=30)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-50pct":
        end = max(0, int(SIZE_1MB * 0.50) - 1)
        r = requests.get(url, headers={"Range": f"bytes=0-{end}"}, timeout=30)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "partial-99pct":
        end = max(0, int(SIZE_1MB * 0.99) - 1)
        r = requests.get(url, headers={"Range": f"bytes=0-{end}"}, timeout=60)
        return len(r.content), f"HTTP {r.status_code}"

    if mode == "full":
        total = _stream_full(url)
        return total, f"{total:,} bytes"

    if mode == "full-auth":
        total = _stream_full(url, headers={"Authorization": f"Bearer {token}"})
        return total, f"{total:,} bytes (authed)"

    if mode == "full-repeat":
        total1 = _stream_full(url)
        console.print(f"    [dim]full-repeat: first done, waiting 60s before second...[/dim]")
        time.sleep(60)
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
@click.option("--poll", default=30, show_default=True,
              help="Seconds between API polls while waiting for counters")
@click.option("--run", default="1", type=click.Choice(["1", "2"]), show_default=True,
              help="Which run set to use (1 or 2)")
@click.option("--timeout-minutes", default=60, show_default=True,
              help="Give up polling after this many minutes")
@click.option("--modes", "modes_override", default=None,
              help="Comma-separated subset of modes to run (default: all)")
def main(repo, poll, run, timeout_minutes, modes_override):
    owner = get_owner()
    token = get_token()

    mode_list = MODES
    if modes_override:
        mode_list = [m.strip() for m in modes_override.split(",")]

    # Verify all releases exist before starting
    counts = snapshot_all(owner, repo)
    missing = [m for m in mode_list if f"v-{m}-{run}" not in counts]
    if missing:
        console.print(f"[red]Missing releases for: {missing} — did you run setup.py?[/red]")
        raise SystemExit(1)

    # --- Phase 1: download all modes ---
    console.print(f"\n[bold]Phase 1: downloading all {len(mode_list)} modes (run {run})[/bold]")

    # {mode: (bytes_recv, notes, t_downloaded, before_count)}
    results = {}
    for mode in mode_list:
        tag = f"v-{mode}-{run}"
        before = counts[tag]
        console.print(f"  [{mode}] downloading...", end=" ")
        t_start = time.monotonic()
        bytes_recv, notes = do_download(mode, owner, repo, tag, token)
        t_done = time.monotonic()
        console.print(f"{bytes_recv:,} B — {notes} ({t_done - t_start:.1f}s)")
        results[mode] = {
            "bytes": bytes_recv,
            "notes": notes,
            "t_downloaded": datetime.now(),
            "before": before,
            "after": None,
            "delta_seconds": None,
        }

    # --- Phase 2: poll until all counters settle ---
    console.print(f"\n[bold]Phase 2: polling every {poll}s until all counters update (timeout: {timeout_minutes}m)[/bold]")

    pending = set(mode_list)
    deadline = time.monotonic() + timeout_minutes * 60
    poll_num = 0

    while pending and time.monotonic() < deadline:
        time.sleep(poll)
        poll_num += 1
        fresh = snapshot_all(owner, repo)
        ticked = set()
        for mode in list(pending):
            tag = f"v-{mode}-{run}"
            after = fresh.get(tag, results[mode]["before"])
            if after > results[mode]["before"]:
                delta_t = (datetime.now() - results[mode]["t_downloaded"]).total_seconds()
                results[mode]["after"] = after
                results[mode]["delta_seconds"] = delta_t
                ticked.add(mode)
                console.print(f"  [green]+[/green] [{mode}] counted! delta={after - results[mode]['before']} after {delta_t:.0f}s")
        pending -= ticked
        still = ", ".join(sorted(pending)) if pending else "none"
        console.print(f"  Poll #{poll_num}: {len(ticked)} new ticks — still waiting: {still}")

    if pending:
        console.print(f"\n[yellow]Timeout: {len(pending)} modes never incremented: {sorted(pending)}[/yellow]")
        for mode in pending:
            results[mode]["after"] = results[mode]["before"]
            results[mode]["delta_seconds"] = None

    # --- Results table ---
    table = Table(title=f"Probe Results (run {run})")
    table.add_column("Mode", style="magenta")
    table.add_column("Bytes to CDN", justify="right")
    table.add_column("Notes")
    table.add_column("Counted?", justify="center")
    table.add_column("Delay (s)", justify="right")
    table.add_column("Cost per +1", style="yellow")

    cheapest = None
    for mode in mode_list:
        r = results[mode]
        delta = (r["after"] or 0) - r["before"]
        counted = "[green]yes[/green]" if delta > 0 else "[red]no[/red]"
        delay = f"{r['delta_seconds']:.0f}s" if r["delta_seconds"] is not None else "—"
        if delta > 0:
            cost = f"{r['bytes']:,} B ({r['bytes'] / SIZE_1MB * 100:.3f}%)" if r["bytes"] > 0 else "[bold]0 B (!)[/bold]"
            if cheapest is None:
                cheapest = (mode, r["bytes"])
        else:
            cost = "—"
        table.add_row(mode, f"{r['bytes']:,}", r["notes"], counted, delay, cost)

    console.print(table)

    if cheapest:
        mode, b = cheapest
        pct = f"{b / SIZE_1MB * 100:.3f}%" if b > 0 else "0 bytes"
        console.print(
            f"\n[bold green]Cheapest counting mode:[/bold green] {mode} — "
            f"{b:,} B ({pct} of {SIZE_1MB:,} B asset)"
        )
    else:
        console.print("\n[red]No mode incremented any counter.[/red]")


if __name__ == "__main__":
    main()
