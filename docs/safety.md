# Safety & Cleanup

The encoder periodically removes orphaned encodes (files in `DEST_FOLDER` with no matching source) and stale version symlinks. Several safety rails prevent accidental mass deletion:

| Guard | Scope | Behavior |
|---|---|---|
| **Source not accessible** | `cleanup_destination`, `cleanup_orphaned_symlinks` | Aborts if `SOURCE_FOLDER` is not a directory |
| **Empty source** | `cleanup_destination` | Aborts if zero video files are found in source |
| **Persisted count** (primary) | `cleanup_destination`, `cleanup_orphaned_symlinks` | After each successful cleanup, the source video count is written to `DEST_FOLDER/.encoder_source_count`. If the current count drops below 50% of the persisted value, cleanup is refused. To reset after intentionally shrinking the library, delete the `.encoder_source_count` file. |
| **Source vs destination ratio** (secondary) | `cleanup_destination`, `cleanup_orphaned_symlinks` | If source video count is less than 50% of destination encode count, cleanup is refused |
| **Mount health on delete events** | `VideoHandler.on_deleted` | Before trusting a file-delete event from the polling observer, the handler verifies the source mount is responsive. If not, the event is ignored. |
| **Growing tmp files** | `cleanup_destination` | `.tmp` files are kept if they are still being written |

**Same-folder mode** (`SOURCE_FOLDER == DEST_FOLDER`): versioned output filenames (e.g., `Movie - 720p.mkv` or `Movie - 720p.mp4`) are recognized as valid encodes and excluded from orphan cleanup.

**Delete-event rate limiter**: If more than 50 delete events fire within 60 seconds, further deletes are suppressed. This prevents mount outages from cascading into mass encode deletion. The limit resets automatically after the window expires.

**Limitations**: The persisted-count and ratio guards use a 50% threshold. A mount that exposes more than half its files will pass both guards, potentially allowing cleanup of files in invisible subtrees. After bulk intentional deletions, you may need to delete `DEST_FOLDER/.encoder_source_count` to reset the baseline — cleanup will refuse to run until the persisted count is reset or the source count recovers above 50%.

## Restarts on a caught-up library

Every container start submits every source again. A source whose encode already exists is
skipped after a look at the destination and a validation of the existing output, without
probing the source, so a restart on a library of tens of thousands of files costs local
destination checks per source rather than hours of metadata reads against the file server
that holds the originals.
