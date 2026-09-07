import json
import subprocess

from config import REPO_NAME


def gh_api(path, method="GET", fields=None):
    cmd = ["gh", "api", "--method", method, path]
    if fields:
        for key, value in fields.items():
            cmd += ["-f", f"{key}={value}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise RuntimeError("gh CLI not found. Install it from https://cli.github.com/") from None
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gh api {path} failed (exit {e.returncode}): {e.stderr.strip()}") from e
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
