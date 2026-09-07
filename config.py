REPO_NAME = "download-count-experiment"
ASSET_1MB = "release-1mb.bin"

# Tag used by timing.py — a dedicated release that gets re-downloaded many times
TIMING_TAG = "v-timing"

# All probe modes, ordered cheapest to most expensive
MODES = [
    "redirect-only",       # GET github.com URL, don't follow 302
    "redirect-only-head",  # HEAD github.com URL, don't follow 302
    "head",                # HEAD CDN URL (redirect followed)
    "zero-abort",          # Follow redirect, read 0 bytes, close
    "partial-1k",          # 1 KB
    "partial-10k",         # 10 KB
    "partial-1pct",        # 1% = 10,485 B
    "partial-10pct",       # 10% = 104,857 B
    "partial-50pct",       # 50% = 524,288 B
    "partial-99pct",       # 99% = 1,038,090 B
    "full",                # entire file
    "full-auth",           # entire file with Bearer token
    "full-repeat",         # same release downloaded twice — counts 1 or 2?
]
