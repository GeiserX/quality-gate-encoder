<p align="center">
  <img src="https://raw.githubusercontent.com/GeiserX/quality-gate-encoder/main/docs/images/banner.svg" alt="quality-gate-encoder" width="900">
</p>

<p align="center"><strong>Your whole Jellyfin library, also in 720p</strong></p>

<p align="center">
  <a href="https://hub.docker.com/r/drumsergio/quality-gate-encoder/tags"><img src="https://img.shields.io/docker/v/drumsergio/quality-gate-encoder?sort=semver&style=flat-square&label=version" alt="Version"></a>
  <a href="https://github.com/GeiserX/quality-gate-encoder/actions/workflows/docker-build.yml"><img src="https://img.shields.io/github/actions/workflow/status/GeiserX/quality-gate-encoder/docker-build.yml?style=flat-square&label=CI" alt="CI"></a>
  <a href="https://github.com/GeiserX/quality-gate-encoder/blob/main/LICENSE"><img src="https://img.shields.io/github/license/GeiserX/quality-gate-encoder?style=flat-square" alt="License"></a>
  <a href="https://hub.docker.com/r/drumsergio/quality-gate-encoder"><img src="https://img.shields.io/docker/pulls/drumsergio/quality-gate-encoder?style=flat-square" alt="Docker pulls"></a>
  <a href="https://codecov.io/gh/GeiserX/quality-gate-encoder"><img src="https://img.shields.io/codecov/c/github/GeiserX/quality-gate-encoder?style=flat-square" alt="Coverage"></a>
</p>

**quality-gate-encoder** watches a Jellyfin library and adds a 720p copy beside every film and episode, so phones and remote viewers direct play the copy instead of making the server transcode live for each stream. It runs as a Docker container on Linux, encodes on an Intel or NVIDIA GPU or in software, leaves the original file untouched, and Jellyfin lists the copy as a second version of the same title. The [Quality Gate](https://github.com/GeiserX/quality-gate) plugin is optional: it caps chosen users at the 720p copy and tells the encoder which titles to make first.

<p align="center">
  <img src="https://raw.githubusercontent.com/GeiserX/quality-gate-encoder/main/docs/images/screenshots/jellyfin-versions.png" alt="A film's page in Jellyfin after the encoder ran: the Version menu is set to 720p and the video line below reads 720p H264" width="900">
</p>

## Features

- Keeps the original untouched and adds a `- 720p` copy beside it; Jellyfin shows both as versions of one title, never as a duplicate.
- Phones and remote viewers direct play the copy, so the server stops transcoding live for every stream.
- Encodes on an Intel iGPU (QSV) or an NVIDIA card (NVENC), decodes on the same GPU, and falls back to software by itself when the GPU refuses a file.
- Output in HEVC, H.264 or AV1; H.264 comes out as MP4 with AAC for the widest direct play, and switching codec never re-encodes what exists.
- Skips anything already 720p or lower, and a restart on a finished library checks the destination instead of re-reading the originals.
- Works on NFS and CIFS shares: it polls instead of relying on inotify, and a Jellyfin on another host gets a manifest instead of symlinks.
- The titles your viewers are about to watch get encoded first when the Quality Gate plugin writes the priority list.
- Jellyfin never sees a half-written file: encodes go to `.tmp` and are renamed once verified.
- A broken mount is caught before cleanup runs: orphan cleanup refuses when the source looks wrong, and delete events are rate-limited.
- Holds new encodes while the destination is under a free-space floor you set.

## Quick start

```bash
docker run -d --name quality-gate-encoder --restart always \
  --device /dev/dri:/dev/dri \
  -v /srv/media/movies:/app/source \
  -v /srv/media/movies-720p:/app/destination \
  -e HW_ENCODING_TYPE=intel \
  -e SYMLINK_TARGET_PREFIX=/srv/media/movies-720p \
  drumsergio/quality-gate-encoder:1.5.12
```

`SYMLINK_TARGET_PREFIX` is the destination folder as Jellyfin sees it, and the source mount must be writable, because the ` - 720p` link is written beside each original. It worked when `docker logs quality-gate-encoder` shows `Encoding succeeded` and `Created version symlink`, and the film's page in Jellyfin gets a Version menu with a 720p entry. The image is linux/amd64 only; drop `--device` to encode in software, and [Getting started](https://geiserx.github.io/quality-gate-encoder/getting-started/) has Docker Compose, NVIDIA and the switch from `drumsergio/jellyfin-encoder` (releases under the old name until 2027-03-31).

## Documentation

- [Getting started](https://geiserx.github.io/quality-gate-encoder/getting-started/): Docker Compose and CLI, Intel and NVIDIA, what the log and Jellyfin show when it worked, upgrading, moving from `jellyfin-encoder`
- [Configuration](https://geiserx.github.io/quality-gate-encoder/configuration/): every variable and its default, quality presets, H.264/MP4 output, free-space floor, priority list, FFmpeg log level
- [Cross-host manifest mode](https://geiserx.github.io/quality-gate-encoder/cross-host/): Jellyfin on a different box than the encoder
- [Utilities](https://geiserx.github.io/quality-gate-encoder/utilities/): `compare_encodes.py`, the coverage report
- [How it works](https://geiserx.github.io/quality-gate-encoder/how-it-works/): the pipeline, why it polls, what a rename costs
- [Safety and cleanup](https://geiserx.github.io/quality-gate-encoder/safety/): the guards that stop a bad mount from deleting encodes
- [Development](https://geiserx.github.io/quality-gate-encoder/development/): run from source, tests
- [Related projects](https://geiserx.github.io/quality-gate-encoder/related/): the plugin and the other Jellyfin tools

With the plugin: [One library, two qualities](https://github.com/GeiserX/quality-gate/blob/main/docs/one-library.md) and [Encode priority](https://github.com/GeiserX/quality-gate/blob/main/docs/encode-priority.md) on the Quality Gate side.

## License

[GPL-3.0-or-later](https://github.com/GeiserX/quality-gate-encoder/blob/main/LICENSE)
