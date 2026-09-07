# GitHub Download Count Gaming — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a three-script Python toolkit that proves GitHub release download counts are trivially gameable — find the cheapest request that increments the counter, then bulk-inflate it to any target while reporting actual bandwidth cost.

**Architecture:** `config.py` holds shared constants and a `gh_api()` helper; `setup.py` creates the test repo and uploads two release assets (1 MB and 10 MB); `probe.py` tests six download modes from cheapest to most expensive and prints a cost table; `inflate.py` uses the cheapest counting mode in a loop to reach a target count, printing live progress and a final cost summary.

**Tech Stack:** Python 3, click (CLI), rich (tables/progress), requests (HTTP), gh CLI via subprocess (GitHub API)

---

### Task 1: Project scaffold and shared config

**Files:**
- Create: `requirements.txt`
- Create: `config.py`

- [ ] **Step 1: Create `requirements.txt`**

```
click>=8.0
rich>=13.0
requests>=2.31
```

- [ ] **Step 2: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all three packages install without error.

- [ ] **Step 3: Create `config.py`**

```python
import json
import subprocess

REPO_NAME = "download-count-experiment"
ASSET_1MB = "release-1mb.tar.gz"
ASSET_10MB = "release-10mb.tar.gz"


def gh_api(path, method="GET", fields=None):
    cmd = ["gh", "api", "--method", method, path]
    if fields:
        for key, value in fields.items():
            cmd += ["-f", f"{key}={value}"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def get_owner():
    return gh_api("/user")["login"]


def get_asset_info(owner, repo):
    """Returns list of dicts: {tag, asset_name, download_count, browser_download_url, size}"""
    releases = gh_api(f"/repos/{owner}/{repo}/releases")
    assets = []
    for release in releases:
        for asset in release.get("assets", []):
            assets.append({
                "tag": release["tag_name"],
                "asset_name": asset["name"],
                "download_count": asset["download_count"],
                "browser_download_url": asset["browser_download_url"],
                "size": asset["size"],
            })
    return assets
```

- [ ] **Step 4: Verify config loads**

```bash
python -c "from config import get_owner; print(get_owner())"
```

Expected: prints your GitHub username (requires `gh auth login` to already be done).

- [ ] **Step 5: Commit**

```bash
git init
git add requirements.txt config.py
git commit -m "feat: project scaffold and shared config"
```

---

### Task 2: `setup.py` — generate assets and create GitHub repo

**Files:**
- Create: `setup.py`

- [ ] **Step 1: Create `setup.py`**

```python
import io
import os
import subprocess
import tarfile
import tempfile

import click
from rich.console import Console

from config import ASSET_1MB, ASSET_10MB, REPO_NAME, get_owner, gh_api

console = Console()


def make_tarball(path, size_bytes):
    """Create a .tar.gz at `path` containing one file padded to size_bytes."""
    padding = b"\x00" * size_bytes
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo(name="data.bin")
        info.size = size_bytes
        tar.addfile(info, io.BytesIO(padding))


@click.command()
@click.option("--repo-name", default=REPO_NAME, show_default=True)
@click.option("--dry-run", is_flag=True, help="Print actions without touching GitHub")
def main(repo_name, dry_run):
    owner = get_owner()
    console.print(f"[bold]Owner:[/bold] {owner}")
    console.print(f"[bold]Repo:[/bold] {repo_name}")

    with tempfile.TemporaryDirectory() as tmpdir:
        path_1mb = os.path.join(tmpdir, ASSET_1MB)
        path_10mb = os.path.join(tmpdir, ASSET_10MB)

        console.print("Generating assets...")
        make_tarball(path_1mb, 1 * 1024 * 1024)
        make_tarball(path_10mb, 10 * 1024 * 1024)
        console.print(f"  {ASSET_1MB}: {os.path.getsize(path_1mb):,} bytes")
        console.print(f"  {ASSET_10MB}: {os.path.getsize(path_10mb):,} bytes")

        if dry_run:
            console.print("[yellow]Dry run — stopping here.[/yellow]")
            return

        console.print(f"Creating repo {owner}/{repo_name}...")
        subprocess.run(
            ["gh", "repo", "create", repo_name, "--public", "--add-readme"],
            check=True,
        )

        for tag, title, asset_path, asset_name in [
            ("v1.0", "1MB Release", path_1mb, ASSET_1MB),
            ("v2.0", "10MB Release", path_10mb, ASSET_10MB),
        ]:
            console.print(f"Creating release {tag}: {title}...")
            subprocess.run(
                [
                    "gh", "release", "create", tag,
                    "--repo", f"{owner}/{repo_name}",
                    "--title", title,
                    "--notes", "",
                    asset_path,
                ],
                check=True,
            )

    console.print("\n[green]Done.[/green] Asset URLs:")
    from config import get_asset_info
    for asset in get_asset_info(owner, repo_name):
        console.print(f"  {asset['tag']} / {asset['asset_name']}: {asset['browser_download_url']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run to verify it parses correctly**

```bash
python setup.py --dry-run
```

Expected: prints owner, repo name, asset sizes, then "Dry run — stopping here." No GitHub calls made.

- [ ] **Step 3: Run for real**

```bash
python setup.py
```

Expected: creates repo, two releases, prints two `browser_download_url`s ending in `.tar.gz`. Initial `download_count` will be 0 (visible via API or GitHub UI).

- [ ] **Step 4: Verify in browser**

Open `https://github.com/{your-username}/download-count-experiment/releases` — should show two releases, each with one asset and "0 downloads".

- [ ] **Step 5: Commit**

```bash
git add setup.py
git commit -m "feat: setup script to create test repo and upload release assets"
```

---

### Task 3: `probe.py` — find cheapest request that counts

**Files:**
- Create: `probe.py`

- [ ] **Step 1: Create `probe.py`**

```python
import time

import click
import requests
from rich.console import Console
from rich.table import Table

from config import REPO_NAME, get_asset_info, get_owner

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
        end = (size // 2) - 1
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
                cost = f"{bytes_recv:,} B / {size / 1024 / 1024:.0f} MB ({bytes_recv / size * 100:.4f}%)"
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
            f"{b:,} B transferred per +1 on a {s / 1024 / 1024:.0f} MB asset "
            f"({b / s * 100:.4f}% of file size)"
        )
    else:
        console.print("\n[red]No mode incremented the counter.[/red]")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run probe against the live repo**

```bash
python probe.py --wait 10
```

Expected: table with six mode rows per asset, deltas of 0 or +1, cost column populated for any mode that counted. Summary line identifies the cheapest counting mode.

- [ ] **Step 3: Commit**

```bash
git add probe.py
git commit -m "feat: probe script to find cheapest request that increments download count"
```

---

### Task 4: `inflate.py` — bulk inflation with cost tracking

**Files:**
- Create: `inflate.py`

- [ ] **Step 1: Create `inflate.py`**

```python
import time

import click
import requests
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn

from config import ASSET_10MB, REPO_NAME, get_asset_info, get_owner
from probe import do_download, snapshot

console = Console()


@click.command()
@click.option("--target", required=True, type=int, help="Target download count to reach")
@click.option("--mode", default="partial-1k", show_default=True,
              type=click.Choice(["zero-abort", "head", "partial-1k", "partial-10k", "partial-50pct", "full"]),
              help="Download mode to use for inflation")
@click.option("--asset", default=ASSET_10MB, show_default=True, help="Asset name to inflate")
@click.option("--repo", default=REPO_NAME, show_default=True)
@click.option("--wait", default=2, show_default=True, help="Seconds between counter checks")
def main(target, mode, asset, repo, wait):
    owner = get_owner()
    assets = get_asset_info(owner, repo)
    asset_info = next((a for a in assets if a["asset_name"] == asset), None)
    if asset_info is None:
        console.print(f"[red]Asset '{asset}' not found. Did you run setup.py?[/red]")
        raise SystemExit(1)

    url = asset_info["browser_download_url"]
    size = asset_info["size"]
    total_bytes = 0
    start = time.time()

    current = snapshot(owner, repo)[asset]
    console.print(f"Starting count: [bold]{current}[/bold] | Target: [bold]{target}[/bold]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Inflating {asset}", total=target - current, completed=0)

        while current < target:
            bytes_recv = do_download(mode, url, size)
            total_bytes += bytes_recv
            time.sleep(wait)
            new_count = snapshot(owner, repo)[asset]
            gained = new_count - current
            current = new_count
            progress.advance(task, gained)
            progress.update(task, description=f"count={current} bw={total_bytes / 1024:.1f}KB")

    elapsed = time.time() - start
    nominal_bytes = target * size
    ratio = total_bytes / nominal_bytes if nominal_bytes > 0 else 0

    console.print(f"\n[bold green]Done.[/bold green]")
    console.print(f"  Final count : {current}")
    console.print(f"  Elapsed     : {elapsed:.1f}s")
    console.print(f"  Bandwidth   : {total_bytes / 1024:.1f} KB transferred")
    console.print(f"  Nominal cost: {nominal_bytes / 1024 / 1024:.1f} MB (if every download were full)")
    console.print(f"  Actual ratio: {ratio * 100:.4f}% of nominal — [bold]{1 / ratio:.0f}× cheaper[/bold] than real downloads" if ratio > 0 else "  Actual ratio: 0 bytes (counter incremented without any data transfer)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run inflate with a small target to verify**

```bash
python inflate.py --target 10 --wait 3
```

Expected: progress bar advances to 10, final summary shows bandwidth used and ratio vs. nominal full-download cost.

- [ ] **Step 3: Run the dramatic demo**

```bash
python inflate.py --target 100 --wait 2
```

Expected: counter reaches 100. Summary line reads something like: *"Faked 100 downloads of a 10 MB file. Actual data transferred: 100 KB (0.001× the real cost)."*

- [ ] **Step 4: Verify in GitHub UI**

Open `https://github.com/{your-username}/download-count-experiment/releases` — the 10MB release asset should show the inflated count matching what the API returned.

- [ ] **Step 5: Commit**

```bash
git add inflate.py
git commit -m "feat: inflate script to bulk-increment download count with cost tracking"
```

---

### Task 5: End-to-end verification run

**Files:** (none new)

- [ ] **Step 1: Check final state of all counts via API**

```bash
python -c "
from config import get_owner, get_asset_info, REPO_NAME
owner = get_owner()
for a in get_asset_info(owner, REPO_NAME):
    print(f\"{a['tag']} / {a['asset_name']}: {a['download_count']} downloads\")
"
```

Expected: both assets show non-zero counts consistent with your probe and inflate runs.

- [ ] **Step 2: Confirm counts match browser**

Open `https://github.com/{your-username}/download-count-experiment/releases` and compare UI counts to API output above.

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "chore: end-to-end verification complete"
```
