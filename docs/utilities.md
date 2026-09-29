# Utilities

### compare_encodes.py

A standalone diagnostic script that compares source and destination folders to report encoding coverage.

```bash
# Command-line usage
python scripts/compare_encodes.py --source /media/movies --dest /media/movies-720p

# Inside a running container
docker exec quality-gate-encoder python /app/scripts/compare_encodes.py

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

Source folder:      /media/movies
Destination folder: /media/movies-720p

----------------------------------------
SUMMARY
----------------------------------------
Total source files:     4,463
Total destination files: 4,440
Matched (encoded):      4,420
Missing encodes:        23
Orphaned encodes:       20
Skipped (low quality):  20

----------------------------------------
MISSING ENCODES (23 files, 45.2 GiB total)
----------------------------------------
  [   2.1 GiB] Movie Title (2024) [BDRemux 1080p].mkv
  [   1.8 GiB] Another Movie (2023) [UHD 2160p].mkv
  ...

================================================================================
STATUS: Issues found - 23 missing encodes, 20 orphaned files
================================================================================
```

</details>
