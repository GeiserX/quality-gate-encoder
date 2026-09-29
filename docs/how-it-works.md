# How it works

```
Source folder (polling observer)
        |
        v
  New or renamed file detected ──> Wait for file completion (size-stable for 60s)
        |
        v
  Resolution check ──> Skip if <= 720p
        |
        v
  FFmpeg transcode ──> scale to 720p, encode video and audio, copy/convert subtitles
        |
        v
  Verify output (ffprobe duration check)
        |
        v
  Atomic rename .tmp -> .mkv/.mp4 ──> Create Jellyfin version symlink (optional)
```

Key design decisions:

- **Polling observer** (`watchdog.PollingObserver`) instead of inotify, ensuring compatibility with NFS, CIFS, and other network filesystems.
- **Temp-file workflow** -- encodes to a `.tmp` file first and atomically renames on success, preventing Jellyfin from indexing incomplete files.
- **File-growth detection** -- before deleting stale `.tmp` files, the cleanup routine checks whether the file is still being written by another instance.
- **ProcessPoolExecutor behind a priority queue** -- one worker for hardware encoding (GPU is the bottleneck), multiple workers for software encoding (CPU-bound). Files wait in the encoder's own queue, and a dispatcher thread hands the executor the next one by [priority](configuration.md#priority-list) whenever a worker frees up, so the executor never holds more than it can run.
- **Container-agnostic output lookup** -- an encode is located by filename stem across every container the tool writes, so changing codec or container never re-encodes a library that is already done.

## Polling interval

Every poll takes a snapshot of the whole source tree: one `stat` for every file and folder
under `SOURCE_FOLDER`. The watcher waits `POLL_INTERVAL` seconds, takes the snapshot, and
reports what changed since the previous one. A new file is therefore noticed within one
interval plus one snapshot.

On a local disk a snapshot is cheap. On a network share holding tens of thousands of files it
is not: a snapshot of a 54k-entry CIFS tree took about 80 seconds, and with the old
one-second wait the file server answered around 1,500 metadata requests per second around
the clock for nothing. `POLL_INTERVAL` defaults to 60. Raise it to 300 or 600 for a large
library on NFS or CIFS; encoding one film takes longer than any of these intervals, so the
wait never decides throughput. A value that is not a number, not above zero, or above
86400 logs a warning and falls back to 60. The startup `Config:` line prints the value in
use.

The watcher matches files by inode, so a rename inside the source tree arrives as a move: a
download finishing its rename from `.part` or `.!qB` into `.mkv`, a folder renamed by hand,
or a file renamed by hand is handled within one poll. A finished encode follows its source:
it is renamed in the destination, the manifest entry and the version symlink move with it,
and nothing is encoded again, so renaming a whole folder costs a rename per file. A source
is encoded under the new name only when its encode is missing, still being written, or
cannot be renamed in place, for instance across filesystems. A file copied in from outside is
a plain create and is handled the same way.

## Features in detail

- **Automatic folder monitoring** -- watches source directories for new, renamed and deleted files using polling (NFS/CIFS compatible)
- **Hardware-accelerated encoding** -- NVIDIA NVENC and Intel Quick Sync Video (QSV), with transparent software fallback (libx265 / libx264 / libsvtav1)
- **Smart skip logic** -- detects files already at 720p or lower via filename heuristics and ffprobe resolution analysis
- **Jellyfin multi-version support** -- creates version symlinks so Jellyfin presents both original and transcoded copies to the user
- **H.264 / AAC / MP4 output** -- set `ENCODING_CODEC: "h264"` for MP4 output that Jellyfin clients direct play without transcoding, and without re-encoding the library you already have (see [H.264, AAC and MP4 Output](configuration.md#h264-aac-and-mp4-output))
- **Audio normalization** -- re-encodes audio for consistent playback: AAC keeping up to 5.1 for MP4, stereo AC3 at 192 kbps for MKV
- **Subtitle preservation** -- copies MKV-native subtitle codecs and converts incompatible ones (MOV text, WebVTT) to SRT; converts text subtitles to `mov_text` for MP4
- **Guarded automatic cleanup** -- periodically removes orphaned encodes and stale symlinks with mount-health checks to prevent mass deletion (see [Safety and cleanup](safety.md) below)
- **Temp-file workflow** -- encodes to `.tmp` and atomically renames on success, so Jellyfin never indexes incomplete files (note: no cross-container locking — avoid pointing two encoders at the same destination subfolder)
- **Configurable quality presets** -- LOW, MEDIUM, and HIGH profiles with per-codec CQ/CRF tuning
