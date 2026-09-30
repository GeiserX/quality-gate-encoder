# Configuration

All settings are controlled via environment variables.

| Variable | Default | Description |
|---|---|---|
| `SOURCE_FOLDER` | `/app/source` | Path to the directory containing original videos |
| `DEST_FOLDER` | `/app/destination` | Path to the directory for encoded output |
| `ENABLE_HW_ACCEL` | `true` | Enable hardware-accelerated encoding |
| `HW_ENCODING_TYPE` | `nvidia` | Hardware encoder: `nvidia` or `intel` |
| `HW_DECODE` | `true` | Decode and scale on the GPU as well as encode; `false` decodes and scales in software (see [Decoding on the GPU](getting-started.md#decoding-on-the-gpu)) |
| `ENCODING_CODEC` | `hevc` | Output codec: `hevc`, `h264`, or `av1` |
| `OUTPUT_CONTAINER` | `auto` | Container: `auto` (MP4 for H.264, MKV otherwise), `mkv`, or `mp4` |
| `ENCODING_QUALITY` | `LOW` | Quality preset: `LOW`, `MEDIUM`, or `HIGH` |
| `AUDIO_CODEC` | `auto` | Audio codec: `auto` (AAC for MP4, AC3 for MKV), `aac`, or `ac3` |
| `AUDIO_BITRATE` | `auto` | Bitrate per audio track: `auto` (192k stereo, 384k multichannel) or a value such as `256k` |
| `AUDIO_CHANNELS` | `auto` | Channels per audio track: `auto` (AAC keeps up to 5.1, AC3 downmixes to stereo) or a count such as `2` |
| `SYMLINK_TARGET_PREFIX` | _(empty)_ | Absolute path prefix for Jellyfin version symlinks (same-host mode) |
| `SYMLINK_MANIFEST_TARGET` | _(empty)_ | Path prefix for cross-host manifest-based symlinks (see [Cross-Host Setup](cross-host.md)) |
| `SYMLINK_VERSION_SUFFIX` | ` - 720p` | Suffix appended to symlink filenames |
| `CLEANUP_INTERVAL_HOURS` | `6` | Hours between automatic orphan cleanup runs |
| `POLL_INTERVAL` | `60` | Seconds the folder watcher waits between scans of the source tree (see [Polling interval](how-it-works.md#polling-interval)) |
| `DEST_MIN_FREE_GB` | `0` | Free-space floor for the destination, in GB: encodes wait while the destination filesystem has less than this free (see [Free-space floor](configuration.md#free-space-floor)) |
| `FFMPEG_LOGLEVEL` | `warning` | What FFmpeg writes to the container log during an encode (see [FFmpeg log level](configuration.md#ffmpeg-log-level)) |
| `PRIORITY_FILE` | `$SOURCE_FOLDER/.encoder-priority.json` | JSON list of source paths to encode before the rest (see [Priority list](configuration.md#priority-list)) |
| `PRIORITY_MAX_AGE_HOURS` | `0` | Hours a priority list counts after its `generated` time; older lists are ignored. `0` turns the check off (see [Priority list](configuration.md#priority-list)) |
| `MAX_HW_WORKERS` | `1` | Encodes run at once on the GPU; ignored when `ENABLE_HW_ACCEL` is `false` (software runs one worker per CPU core) |
| `SKIP_IF_LOW_QUALITY_EXISTS` | `true` | Skip a source when a sibling file already at 720p or lower sits beside it |
| `IMAGE_MOVED_TO` | _(empty)_ | Set only on `drumsergio/jellyfin-encoder` images; makes the startup log say where the image moved |

## Quality Presets

Each preset defines constant-quality (CQ) values for hardware encoding and constant rate factor (CRF) values for software fallback.

| Preset | HEVC CQ / CRF | H.264 CQ / CRF | AV1 CQ / CRF | Intended Use |
|---|---|---|---|---|
| **LOW** | 32 / 30 | 28 / 26 | 45 / 40 | Mobile devices, minimal storage footprint |
| **MEDIUM** | 26 / 26 | 24 / 23 | 35 / 35 | Balanced quality and file size |
| **HIGH** | 22 / 22 | 21 / 20 | 28 / 28 | Higher fidelity, larger files |

## H.264, AAC and MP4 Output

Set `ENCODING_CODEC: "h264"` and new encodes come out as H.264 video with AAC audio in an MP4 container. Nothing else about the setup changes.

| Aspect | What you get |
|---|---|
| Video encoder | `h264_qsv` (Intel), `h264_nvenc` (NVIDIA), `libx264` (software fallback) |
| Container | `.mp4`, with the index written at the front so players can start before reading the whole file |
| Audio | AAC, source channel layout up to 5.1, at 192 kbps stereo or 384 kbps multichannel |
| Pixel format | Forced to 8-bit `yuv420p`, so 10-bit sources encode instead of failing on hardware H.264 |

`hevc` and `av1` still produce `.mkv` with the stereo AC3 audio they always have. To pair a codec with a different container, set `OUTPUT_CONTAINER` explicitly.

### Switching codec never re-encodes what you already have

Changing `ENCODING_CODEC` on a library that is already encoded produces zero re-encodes.

An output on disk counts as done whatever container it is in. If your destination is full of `Movie - 720p.mkv` files and you switch to `ENCODING_CODEC: "h264"`, the encoder leaves those files alone. It picks up only the titles that have no encode at all, and those come out as `.mp4`. Switching back to `hevc` works the same way in reverse, respecting the `.mp4` outputs you already have.

The skip check, orphan cleanup, the symlink manifest, and source-deletion handling all match on the filename stem rather than the extension. A destination folder holding a mix of `.mkv` and `.mp4` works fine, so the two formats can coexist for as long as you like.

### Subtitles in MP4

MP4 carries text subtitles only. The encoder converts text tracks (SRT, ASS/SSA, WebVTT) to `mov_text` and drops bitmap tracks (PGS, DVB), which have no MP4 equivalent. Keep external `.srt` sidecars next to the encode if you need those. If FFmpeg fails with subtitles mapped, the encoder retries once without them. A subtitle track FFmpeg cannot handle costs you the subtitles, never the encode.

## Free-space floor

`DEST_MIN_FREE_GB=1000` makes the encoder hold each new encode while the destination filesystem has less than 1 TB free, re-check every five minutes, and carry on by itself when space returns. Encodes already running finish, and the floor is checked again after the wait for a still-growing source, right before ffmpeg starts. If the free space cannot be read at all, the encode proceeds and ffmpeg reports whatever is really wrong, so the floor is a courtesy to the disk's other tenants, not a guarantee against ENOSPC. Use it when the destination shares a disk with something that must never see ENOSPC, such as an object store node or a database. The default `0` keeps the old behaviour: encode until the disk is full.

## Priority list

At every start the encoder queues every source in the order the folder walk finds them, so
on a large library the next episode of a show people are watching can sit thousands of files
down the queue. `PRIORITY_FILE` lets something outside the encoder put those first; the
[Quality Gate plugin](https://github.com/GeiserX/quality-gate/blob/main/docs/encode-priority.md)
writes it from what capped viewers are about to watch, and anything else may write the same format. The
encoder only reads it, so it can live on a read-only source mount.

```json
{
  "generated": "2026-01-01T00:00:00Z",
  "paths": [
    "Show A (2001)/Season 02/",
    "Film B (2002)/Film B (2002).mkv",
    "Show C (2003)/"
  ]
}
```

- The file is UTF-8 JSON. A leading byte order mark, as some Windows tools write, is fine.
- Each entry is a path relative to `SOURCE_FOLDER`: a folder (ends with `/`) or one file.
  The list is in priority order, highest first.
- A queued file belongs to the first entry that is its own path or a folder holding it.
  Matching is on whole path components, so `Show A/` covers `Show A/S01/E01.mkv` and not
  `Show AB/S01/E01.mkv`.
- Both sides are compared in Unicode NFC, so an accented name matches whether the list or
  the filesystem spells `é` as one character or as `e` plus a combining accent. Nothing else
  is folded: `show a/` does not match `Show A/`.
- Files of an earlier entry encode before files of a later one. Within one entry they go in
  path order, so `S01E01` comes before `S01E02`. Files no entry covers go last, in the order
  they were queued.
- Before each pick the encoder checks the file's modification time and size, and re-reads it
  when either changed. A new list re-orders what is still waiting; encodes already running
  finish. A file the watcher finds later goes straight to its place in the order.
- A missing, unreadable, empty or invalid file changes nothing. The queue runs in the order
  files were found, as it did before this setting existed, and the encoder logs each change
  of state once, not on every pick.
- `PRIORITY_MAX_AGE_HOURS` guards against a producer that stopped running. When it is above
  `0`, a list whose `generated` time is older than that many hours counts as absent, and so
  does a list whose `generated` is missing or is not an ISO 8601 extended time, with a `T`
  between date and time and a `Z` or UTC offset (`2026-01-01T00:00:00Z`,
  `2026-01-01T01:00:00+01:00`). The age is checked at every
  pick, so a list expires without being touched, and it counts again once it is rewritten
  with a recent time. The log says why the list was set aside, once per change. A producer
  should rewrite the file at least once a day, and the setting should leave room for a
  missed run: with a daily producer, `48` survives one failure and ignores the list after
  the second. The default `0` never reads `generated`.

At startup, and on every reload, the log says how many waiting files the list matched and
which one runs first:

```
Priority list /app/source/.encoder-priority.json: 3 entries, 42 of 51876 pending files match; first: Show A (2001)/Season 02/S02E05.mkv
```

## FFmpeg log level

At `warning`, the default, FFmpeg prints nothing for a healthy encode and everything it
complains about for a failing one. The encoder's own lines stay either way: the full command
it ran, `Encoding succeeded:` with the finished path, and `FFmpeg encoding failed (exit N)`
with the code FFmpeg died on.

The encoder used to run FFmpeg at `verbose`, which redraws a progress line twice a second.
Python reads FFmpeg's output in text mode, where the carriage return that redraws the line
counts as a newline, so every redraw became a log record of its own. A Docker json-file log
at the default few megabytes then held a few hours, and anything older was gone before
anyone went looking for it.

Set `FFMPEG_LOGLEVEL=verbose` on one container when a single file needs the full FFmpeg dump.
The nine level names work: `quiet`, `panic`, `fatal`, `error`, `warning`, `info`, `verbose`,
`debug`, `trace`. FFmpeg's numeric levels and its flag syntax, `repeat+level+verbose`, are
not passed through. Anything outside the nine falls back to `warning` and logs a line naming
what it takes, because a level FFmpeg does not know makes it exit before it opens the input,
which would fail every encode.
