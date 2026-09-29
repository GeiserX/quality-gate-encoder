<p align="center">
  <img src="https://raw.githubusercontent.com/GeiserX/quality-gate-encoder/main/docs/images/banner.svg" alt="quality-gate-encoder" width="900"/>
</p>

<p align="center">
  <strong>The encoder of Quality Gate: automatic 720p versions of a Jellyfin library</strong>
</p>

<p align="center">
  <a href="https://github.com/GeiserX/quality-gate-encoder/releases"><img src="https://img.shields.io/github/v/release/GeiserX/quality-gate-encoder?style=flat-square" alt="GitHub Release"></a>
  <a href="https://github.com/GeiserX/quality-gate-encoder/actions/workflows/docker-build.yml"><img src="https://github.com/GeiserX/quality-gate-encoder/actions/workflows/docker-build.yml/badge.svg" alt="Build"></a>
  <a href="https://github.com/GeiserX/quality-gate-encoder/blob/main/LICENSE"><img src="https://img.shields.io/github/license/GeiserX/quality-gate-encoder?style=flat-square" alt="License"></a>
  <a href="https://hub.docker.com/r/drumsergio/quality-gate-encoder"><img src="https://img.shields.io/docker/pulls/drumsergio/quality-gate-encoder?style=flat-square" alt="Docker Pulls"></a>
  <a href="https://codecov.io/gh/GeiserX/quality-gate-encoder"><img src="https://codecov.io/gh/GeiserX/quality-gate-encoder/graph/badge.svg" alt="codecov"></a>
</p>

**quality-gate-encoder** is the encoder of [Quality Gate](https://github.com/GeiserX/quality-gate), the Jellyfin plugin. It watches your media library and transcodes each video to a 720p HEVC, H.264 or AV1 copy for mobile and remote streaming, and Jellyfin shows both versions.

> **Formerly jellyfin-encoder.** The image moved to `drumsergio/quality-gate-encoder`. Every release is also published as `drumsergio/jellyfin-encoder` until 2027-03-31, and those images log a notice at startup; after that date the old name stays pullable but gets no new versions.

## Features

- Polls source folders for new, renamed and deleted files, so it works on NFS and CIFS.
- NVIDIA NVENC and Intel QSV encoding and GPU decoding, with automatic software fallback.
- Skips files already at 720p or lower.
- Jellyfin version symlinks on the same host, or a manifest for a Jellyfin on another host.
- H.264 / AAC / MP4 output for direct play; switching codec never re-encodes existing files.
- Audio normalization and subtitle conversion.
- Guarded orphan cleanup that refuses to run when the source mount looks broken.
- Priority list, free-space floor and LOW / MEDIUM / HIGH quality presets.
- Writes to `.tmp` and renames on success, so Jellyfin never indexes half-written files.

## Quick start

```bash
docker run -d --name quality-gate-encoder --device /dev/dri:/dev/dri \
  -v /path/to/source:/app/source -v /path/to/destination:/app/destination \
  -e HW_ENCODING_TYPE=intel --restart always drumsergio/quality-gate-encoder:1.5.12
```

Docker Compose, NVIDIA setup and the full option list are in [Getting started](https://github.com/GeiserX/quality-gate-encoder/blob/main/docs/getting-started.md) and [Configuration](https://github.com/GeiserX/quality-gate-encoder/blob/main/docs/configuration.md).

## Documentation

- [Getting started](https://github.com/GeiserX/quality-gate-encoder/blob/main/docs/getting-started.md): Docker Compose and CLI, NVIDIA and Intel, GPU decoding, software fallback, upgrading
- [Configuration](https://github.com/GeiserX/quality-gate-encoder/blob/main/docs/configuration.md): environment variables, quality presets, H.264/MP4 output, free-space floor, priority list, FFmpeg log level
- [How it works](https://github.com/GeiserX/quality-gate-encoder/blob/main/docs/how-it-works.md): pipeline, design decisions, polling interval
- [Safety and cleanup](https://github.com/GeiserX/quality-gate-encoder/blob/main/docs/safety.md)
- [Cross-host manifest mode](https://github.com/GeiserX/quality-gate-encoder/blob/main/docs/cross-host.md)
- [Utilities](https://github.com/GeiserX/quality-gate-encoder/blob/main/docs/utilities.md): `compare_encodes.py`
- [Development](https://github.com/GeiserX/quality-gate-encoder/blob/main/docs/development.md)
- [Related projects](https://github.com/GeiserX/quality-gate-encoder/blob/main/docs/related.md)

## License

[GPL-3.0-or-later](https://github.com/GeiserX/quality-gate-encoder/blob/main/LICENSE)
