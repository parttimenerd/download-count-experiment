import os
import subprocess
import tempfile

import click
from rich.console import Console

from config import ASSET_1MB, MODES, REPO_NAME
from gh_client import get_asset_info, get_owner

console = Console()

SIZE_1MB = 1 * 1024 * 1024


def make_random_file(path, size_bytes):
    with open(path, "wb") as f:
        f.write(os.urandom(size_bytes))


def release_tag(mode, run):
    return f"v-{mode}-{run}"


def release_title(mode, run):
    return f"{mode} (run {run})"


@click.command()
@click.option("--repo-name", default=REPO_NAME, show_default=True)
@click.option("--dry-run", is_flag=True, help="Print actions without touching GitHub")
def main(repo_name, dry_run):
    owner = get_owner()
    console.print(f"[bold]Owner:[/bold] {owner}")
    console.print(f"[bold]Repo:[/bold] {repo_name}")
    console.print(f"[bold]Releases to create:[/bold] {len(MODES) * 2} ({len(MODES)} modes × 2 runs)")

    if dry_run:
        for mode in MODES:
            for run in (1, 2):
                console.print(f"  [dim]{release_tag(mode, run)}[/dim] — {release_title(mode, run)}")
        console.print("[yellow]Dry run — stopping here.[/yellow]")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        asset_path = os.path.join(tmpdir, ASSET_1MB)
        console.print(f"Generating {ASSET_1MB} ({SIZE_1MB:,} bytes of random data)...")
        make_random_file(asset_path, SIZE_1MB)

        console.print(f"Creating repo {owner}/{repo_name}...")
        result = subprocess.run(
            ["gh", "repo", "create", repo_name, "--public", "--add-readme"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            if "already exists" in result.stderr:
                console.print("[yellow]Repo already exists, skipping creation.[/yellow]")
            else:
                raise RuntimeError(f"gh repo create failed: {result.stderr.strip()}")

        for mode in MODES:
            for run in (1, 2):
                tag = release_tag(mode, run)
                title = release_title(mode, run)
                console.print(f"  Creating {tag}: {title}...")
                subprocess.run(
                    [
                        "gh", "release", "create", tag,
                        "--repo", f"{owner}/{repo_name}",
                        "--title", title,
                        "--notes", "",
                        asset_path,
                    ],
                    check=True,
                    capture_output=True,
                )

    console.print("\n[green]Done.[/green]")
    console.print(f"Releases: https://github.com/{owner}/{repo_name}/releases")


if __name__ == "__main__":
    main()
