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
