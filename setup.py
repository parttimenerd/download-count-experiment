import io
import os
import subprocess
import tarfile
import tempfile

import click
from rich.console import Console

from config import ASSET_1MB, ASSET_10MB, REPO_NAME
from gh_client import get_asset_info, get_owner

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

        for tag, title, asset_path in [
            ("v1.0", "1MB Release", path_1mb),
            ("v2.0", "10MB Release", path_10mb),
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
    for asset in get_asset_info(owner, repo_name):
        console.print(f"  {asset['tag']} / {asset['asset_name']}: {asset['browser_download_url']}")


if __name__ == "__main__":
    main()
