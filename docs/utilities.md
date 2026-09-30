# Utilities

## compare_encodes.py

A standalone diagnostic script that compares source and destination folders to report encoding coverage.

```bash
# Command-line usage
python scripts/compare_encodes.py --source /media/movies --dest /media/movies-720p

# Inside a running container
docker exec quality-gate-encoder python3 /app/scripts/compare_encodes.py

# Output as JSON or CSV
python scripts/compare_encodes.py -s /media/movies -d /media/movies-720p --format json
python scripts/compare_encodes.py -s /media/movies -d /media/movies-720p --format csv

# Include files that were skipped (already 720p or lower)
python scripts/compare_encodes.py -s /media/movies -d /media/movies-720p --show-skipped
```

| Option | Env Variable | Description |
|---|---|---|
| `-s, --source` | `SOURCE_FOLDER` | Source folder with original videos |
| `-d, --dest` | `DEST_FOLDER` | Destination folder with encoded videos |
| `-f, --format` | `OUTPUT_FORMAT` | Output format: `text`, `json`, `csv` |
| `--show-skipped` | `SHOW_SKIPPED` | Include skipped low-quality files in the report |
| `--ignore` | `IGNORE_PATTERNS` | Additional regex patterns to ignore (comma-separated) |

<details>
<summary>Example output</summary>

```
================================================================================
ENCODING COMPARISON REPORT
================================================================================

Source folder:      /app/source
Destination folder: /app/destination

----------------------------------------
SUMMARY
----------------------------------------
Total source files:     4
Total destination files: 3
Matched (encoded):      3
Missing encodes:        1
Orphaned encodes:       0
Skipped (low quality):  0

----------------------------------------
MISSING ENCODES (1 files, 90.9 MiB total)
----------------------------------------
  [    90.9 MiB] Elephants Dream (2006)/Elephants Dream (2006).mkv

================================================================================
STATUS: Issues found - 1 missing encodes
================================================================================
```

</details>

That is the report from the four-film demo library in [Getting started](getting-started.md#what-you-see-when-it-worked).
Elephants Dream shows as missing although the encoder skipped it: the report judges quality from markers in the
file name (`720p`, `480p`, `dvdrip` and similar), not with ffprobe, so a 576p file named without one is counted
as a missing encode.
