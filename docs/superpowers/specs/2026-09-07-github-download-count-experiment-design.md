# GitHub Release Download Count — Gaming the Numbers

## Context

GitHub release `download_count` is widely used as a proxy for software popularity and adoption. The API exposes it prominently; projects cite it in READMEs and funding pitches. This experiment proves the number is trivially fakeable: an attacker can inflate any project's download count to an arbitrary value with negligible bandwidth and no authentication required.

The experiment has two goals:
1. Find the **cheapest request** that still increments the counter (minimum effort per +1)
2. Demonstrate **bulk inflation** — a loop that drives the counter to a target number and shows the cost

The output is a concrete claim with evidence: *"GitHub counts any GET that returns N bytes as a download. Inflating a 10MB asset's counter by 1000 costs X KB."*

Even without malicious intent, download counts are inherently unreliable. A misconfigured CI pipeline that re-downloads a release asset on every run will silently inflate counts — a common accident as AI-generated scripts and copy-pasted workflows proliferate. A project with 50,000 "downloads" may have 48,000 of them from a single broken GitHub Actions job. The gaming experiment is the adversarial proof; the CI scenario is the accidental one. Both point to the same conclusion: the number cannot be trusted as a popularity signal.

---

## Architecture

```
setup.py       # one-time: create repo, build assets, upload releases
probe.py       # phase 1: find minimum request type that counts
inflate.py     # phase 2: bulk inflation loop with cost tracking
config.py      # shared: repo name, asset names, gh_api() helper
requirements.txt
```

### Dependencies

| Library | Purpose |
|---------|---------|
| `click` | CLI argument/option parsing |
| `rich` | Colored terminal tables |
| `requests` | Controlled HTTP (Range, streaming, abort) |
| `gh` CLI (subprocess) | Fetch release stats via `gh api` |

---

## `setup.py`

Creates the experiment infrastructure once.

1. Resolve GitHub owner via `gh api user`.
2. Generate two `.tar.gz` archives:
   - `release-1mb.tar.gz` — 1 MiB padded archive (low-cost baseline)
   - `release-10mb.tar.gz` — 10 MiB padded archive (makes cost ratio dramatic)
3. Create public repo `download-count-experiment` (fail loudly if exists).
4. Initialize with a dummy README commit (required before tags).
5. Create releases:
   - Tag `v1.0` → "1MB Release" → upload `release-1mb.tar.gz`
   - Tag `v2.0` → "10MB Release" → upload `release-10mb.tar.gz`
6. Print both `browser_download_url`s and exit.

```
python setup.py [--repo-name download-count-experiment] [--dry-run]
```

---

## `probe.py`

Finds the minimum request type that increments the counter. Runs each mode **once** against each asset, snapshots before/after, and reports delta + bytes transferred.

**Modes tested, ordered cheapest to most expensive:**

| Mode | What it sends |
|------|--------------|
| `zero-abort` | TCP connect, 0 bytes read, close |
| `head` | HTTP HEAD — headers only |
| `partial-1k` | `Range: bytes=0-1023` (1 KB) |
| `partial-10k` | `Range: bytes=0-10239` (10 KB) |
| `partial-50pct` | `Range: bytes=0-<half of file>` |
| `full` | Entire file streamed to `/dev/null` |

**Output table:**

```
┌──────────────┬──────────────┬───────────────┬───────┬──────────────────────┐
│ Asset        │ Mode         │ Bytes sent    │ Delta │ Cost per +1          │
├──────────────┼──────────────┼───────────────┼───────┼──────────────────────┤
│ release-10mb │ zero-abort   │ 0 B           │     0 │ —                    │
│ release-10mb │ head         │ 0 B           │     0 │ —                    │
│ release-10mb │ partial-1k   │ 1,024 B       │    +1 │ 1,024 B / 10 MB file │
│ ...          │ ...          │ ...           │   ... │ ...                  │
└──────────────┴──────────────┴───────────────┴───────┴──────────────────────┘
```

The "cheapest counting mode" is identified in a summary line: *"Minimum request to count: partial-1k — 1 KB transferred per +1 on a 10 MB asset (0.01% of file size)."*

```
python probe.py [--wait 5] [--repo download-count-experiment]
```

---

## `inflate.py`

Uses the cheapest counting mode found by `probe.py` (or overridden via `--mode`) to drive the counter to a target value.

Tracks and prints running totals:

```
Inflating release-10mb download count...
  Target: 1000 | Current: 47 | Bandwidth used: 47 KB | Elapsed: 12s
  ...
Done. Counter: 1000. Total bandwidth: 1,000 KB (0.1% of nominal downloads)
```

Final summary states: *"Faked 1000 downloads of a 10 MB file. Actual data transferred: 1 MB (0.01× the 'real' cost)."*

```
python inflate.py --target 100 [--mode partial-1k] [--repo download-count-experiment]
```

---

## `config.py`

- `REPO_NAME`, `ASSET_1MB`, `ASSET_10MB` constants
- `gh_api(path)` — thin wrapper around `subprocess.run(["gh", "api", path])` returning parsed JSON
- `get_download_count(owner, repo, tag)` — convenience function used by both probe and inflate

---

## Expected Conclusion

The experiment should produce one of:
- **"Any partial GET counts"** — 1 KB per fake download on a 10 MB file = 0.01% bandwidth cost
- **"Only full downloads count"** — gaming is expensive (but still unauthenticated, so trivial to script)
- **"HEAD/zero-abort counts"** — near-zero cost, pure counter increment

Either finding demonstrates the metric is unreliable as a trust signal.

---

## Verification

1. `python setup.py` — confirm two releases visible at `github.com/{owner}/download-count-experiment/releases`, counts at 0.
2. `python probe.py --wait 10` — review cost table; identify cheapest counting mode.
3. `python inflate.py --target 50 --wait 2` — confirm counter increments to 50, review bandwidth summary.
4. Visit the repo's release page in a browser — counts should match what the API reported.
