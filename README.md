# download-count-experiment

Proves that GitHub release download counts are trivially gameable and unreliable as a popularity signal.

## What this does

GitHub exposes `download_count` per release asset via the REST API. Projects cite these numbers in READMEs and funding pitches. This experiment answers:

- What is the **minimum HTTP request** that increments the counter?
- Does a partial download (e.g. 1 KB of a 1 MB file) count?
- Does not following the redirect count?
- Does an authenticated download count differently?
- How long does GitHub take to update the counter after a download?

Even without malicious intent, these numbers are unreliable — a misconfigured CI pipeline that re-downloads a release on every run silently inflates counts. The gaming experiment is the adversarial proof; the CI accident is the everyday reality.

## Why the redirect architecture causes this

When you request a GitHub release asset there are two hops:

**Hop 1 — github.com (where the counter lives)**
```
GET https://github.com/owner/repo/releases/download/v1.0/file.bin
→ 302 Location: https://release-assets.githubusercontent.com/...?jwt=...&sig=...
```
GitHub's server looks up the release asset, **increments the download counter**, and issues a signed short-lived redirect URL to the actual file. The counter fires here — before the client has fetched a single byte of content.

**Hop 2 — release-assets.githubusercontent.com (Azure Blob Storage)**
```
GET https://release-assets.githubusercontent.com/github-production-release-asset/...
→ 200 (file bytes)
```
This is Azure Blob Storage with a signed SAS token. It has no knowledge of GitHub's download counter — it just serves bytes to whoever presents a valid signed URL. GitHub never hears back whether the CDN request succeeded or how many bytes were delivered.

The counter is a side effect of issuing the redirect, not of delivering the file. GitHub has no feedback loop from the CDN. Once it hands out the signed URL, the download is considered to have happened. It's architecturally similar to a ticketing system that counts a sale when the ticket is issued, not when the door is scanned.

## Findings

**Every single mode incremented the counter — including a GET that never left GitHub's servers.**

GitHub's `download_count` is incremented when the redirect request hits `github.com/releases/download/...` and returns a 302. The CDN (`release-assets.githubusercontent.com`) is never contacted. No bytes are transferred. This means:

- You don't need to download anything
- You don't need an account
- A single `curl` without `-L` is enough
- A single `fetch()` call from any browser console is enough

Full results from one probe run (all 13 modes against a 1 MB asset):

| Mode | Bytes to CDN | Counted? | Delay |
|------|-------------|----------|-------|
| `redirect-only` | 0 B | ✅ | ~619s |
| `redirect-only-head` | 0 B | ✅ | ~618s |
| `head` | 0 B | ✅ | ~618s |
| `zero-abort` | 0 B | ✅ | ~617s |
| `partial-1k` | 1,024 B (0.098%) | ✅ | ~617s |
| `partial-10k` | 10,240 B (0.977%) | ✅ | ~616s |
| `partial-1pct` | 10,485 B (1.000%) | ✅ | ~616s |
| `partial-10pct` | 104,857 B (10.000%) | ✅ | ~615s |
| `partial-50pct` | 524,288 B (50.000%) | ✅ | ~615s |
| `partial-99pct` | 1,038,090 B (99.000%) | ✅ | ~614s |
| `full` | 1,048,576 B (100%) | ✅ | ~614s |
| `full-auth` | 1,048,576 B (100%) | ✅ | ~613s |
| `full-repeat` (×2, 60s gap) | 2,097,152 B | ✅ delta=**1** | ~551s |

**`full-repeat` counted only once** — same IP, same release, two downloads within the update window = 1 increment, not 2.

**Same-IP deduplication is per batch window, not per release.** When the WordPress demo site was loaded multiple times from the same IP, only one increment was recorded per ~10 minute window regardless of how many page loads fired the snippet. This means naive inflation scripts running from a single IP are rate-limited to roughly 6 increments per hour. To inflate reliably you need either multiple IPs or to wait between batch windows — which is exactly what a botnet or distributed CI abuse would provide.

**Counter update delay:** ~10 minutes. First observation: 625s. Probe run: 551–619s across all 13 modes. GitHub batches counter updates on a fixed schedule rather than incrementing in real time.

## Reproducing — one-liners

Check the counter before and after:

```bash
gh api /repos/parttimenerd/download-count-experiment/releases \
  | python3 -c "import json,sys; [print(a['name'], a['download_count']) for r in json.load(sys.stdin) for a in r['assets']]"
```

**Minimal JavaScript — one `fetch()` from any browser console or Node.js, zero CDN traffic:**

```javascript
// Stops at the 302, never contacts the CDN. Still increments the counter.
// Browser: response.type === "opaqueredirect", response.status === 0
// Node.js: response.status === 302
fetch("https://github.com/parttimenerd/download-count-experiment/releases/download/v-redirect-only-2/release-1mb.bin", {redirect: "manual"})
```

**curl — the cheapest (0 bytes from CDN):**
```bash
# redirect-only: GET without following redirect
curl -s -o /dev/null "https://github.com/parttimenerd/download-count-experiment/releases/download/v-redirect-only-2/release-1mb.bin"

# redirect-only-head: HEAD without following redirect
curl -s -o /dev/null -I "https://github.com/parttimenerd/download-count-experiment/releases/download/v-redirect-only-head-2/release-1mb.bin"
```

**Also counts — no bytes from CDN:**
```bash
# head: HEAD following redirect to CDN
curl -s -o /dev/null -I -L "https://github.com/parttimenerd/download-count-experiment/releases/download/v-head-2/release-1mb.bin"

# zero-abort: connect, receive response headers, close
curl -s -o /dev/null -L --max-filesize 0 "https://github.com/parttimenerd/download-count-experiment/releases/download/v-zero-abort-2/release-1mb.bin" || true
```

**Partial downloads — all count regardless of how little you fetch:**
```bash
# 1 KB of a 1 MB file (0.1%)
curl -s -o /dev/null -L -H "Range: bytes=0-1023" "https://github.com/parttimenerd/download-count-experiment/releases/download/v-partial-1k-2/release-1mb.bin"

# 50% of file
curl -s -o /dev/null -L -H "Range: bytes=0-524287" "https://github.com/parttimenerd/download-count-experiment/releases/download/v-partial-50pct-2/release-1mb.bin"
```

**Full download:**
```bash
curl -s -o /dev/null -L "https://github.com/parttimenerd/download-count-experiment/releases/download/v-full-2/release-1mb.bin"
```

## Modes tested

| Mode | Description |
|------|-------------|
| `redirect-only` | GET github.com URL, don't follow the 302 to CDN |
| `redirect-only-head` | HEAD github.com URL, don't follow |
| `head` | HEAD after following redirect to CDN |
| `zero-abort` | Follow redirect, open stream, read 0 bytes |
| `partial-1k` | 1 KB (0.1%) |
| `partial-10k` | 10 KB (~1%) |
| `partial-1pct` | exactly 1% |
| `partial-10pct` | 10% |
| `partial-50pct` | 50% |
| `partial-99pct` | 99% |
| `full` | Entire file |
| `full-auth` | Entire file with Bearer token |
| `full-repeat` | Same release downloaded twice (tests IP deduplication) |

Each mode has a run-1 and run-2 release. Run-2 for `full-repeat` does the two downloads 60 seconds apart.

## Scripts

| Script | Purpose |
|--------|---------|
| `setup.py` | Creates the test repo with 26 releases (13 modes × 2 runs) + 1 timing release, each with a 1 MB random-byte asset |
| `probe.py` | Downloads all modes in Phase 1, then polls all counters together in Phase 2 |
| `timing.py` | Repeatedly downloads the timing release, records delay per sample to CSV, plots histogram |
| `inflate.py` | Bulk-inflates a counter to a target value, reports bandwidth cost |
| `watch_counter.py` | Downloads once (or twice 60s apart for run-2), polls until counter updates, pings audibly |

## Usage

```bash
pip install -r requirements.txt

# one-time setup (repo already exists if you cloned this)
python3 setup.py

# probe all modes — Phase 1 downloads all, Phase 2 polls together (~15 min total)
python3 probe.py

# measure counter update delay over many samples
python3 timing.py --samples 20 --poll 15

# regenerate histogram from existing timing_results.csv
python3 timing.py --plot-only

# bulk inflate a counter
python3 inflate.py --target 100
```

## Requirements

- Python 3.9+
- [`gh` CLI](https://cli.github.com/) authenticated (`gh auth login`)
