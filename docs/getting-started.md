# Getting started

## Docker Compose

```yaml
services:
  quality-gate-encoder:
    image: drumsergio/quality-gate-encoder:1.5.12
    container_name: quality-gate-encoder
    devices:
      - /dev/dri:/dev/dri  # Intel QSV -- remove if using NVIDIA or software encoding
    volumes:
      - /path/to/source:/app/source
      - /path/to/destination:/app/destination
    environment:
      ENABLE_HW_ACCEL: "true"
      HW_ENCODING_TYPE: "intel"   # nvidia | intel
      ENCODING_QUALITY: "LOW"     # LOW | MEDIUM | HIGH
      ENCODING_CODEC: "hevc"      # hevc | av1
      POLL_INTERVAL: "60"         # seconds between scans of the source tree
    restart: always

    # For NVIDIA GPU support, replace the devices block above with:
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - capabilities: [gpu]
```

## Docker CLI

```bash
docker run -d \
  --name quality-gate-encoder \
  --device /dev/dri:/dev/dri \
  -v /path/to/source:/app/source \
  -v /path/to/destination:/app/destination \
  -e ENABLE_HW_ACCEL=true \
  -e HW_ENCODING_TYPE=intel \
  -e ENCODING_CODEC=hevc \
  -e ENCODING_QUALITY=LOW \
  -e POLL_INTERVAL=60 \
  --restart always \
  drumsergio/quality-gate-encoder:1.5.12
```

## Hardware Acceleration

### NVIDIA (NVENC)

Requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Add a GPU reservation to your Compose file:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - capabilities: [gpu]
```

Set `HW_ENCODING_TYPE: "nvidia"`. Supported encoders: `hevc_nvenc`, `h264_nvenc`, `av1_nvenc`.

### Intel (Quick Sync Video)

Pass the render device into the container:

```yaml
devices:
  - /dev/dri:/dev/dri
```

Set `HW_ENCODING_TYPE: "intel"`. Supported encoders: `hevc_qsv`, `h264_qsv`, `av1_qsv`.

### Decoding on the GPU

With a hardware encoder, the source is decoded and scaled to 720p on the same GPU, so the frames never pass through the CPU. Intel uses `-hwaccel qsv` with `scale_qsv`, NVIDIA uses `-hwaccel cuda` with `scale_cuda`. The encoder settings are the same as on the software path. For H.264 output the GPU converts to 8-bit 4:2:0 (`nv12`), so 10-bit sources still produce 8-bit H.264; HEVC and AV1 keep the source bit depth, as they do in software.

On 1080p sources this cut the CPU time of an encode by 10 to 16 times on an Intel iGPU, and by about 40 times on an NVIDIA card.

Every file still gets its encode:

- A source in a codec the GPU does not decode (for example MPEG-4 Part 2, which covers Xvid and DivX, on Intel) is decoded in software from the start.
- A source whose display matrix rotates or flips the picture (a phone video shot in portrait, say) is decoded in software too. FFmpeg does not rotate or flip GPU frames, so the encode would come out sideways or upside down.
- If the GPU run fails, or its output fails verification, the file is encoded again straight away with software decoding and scaling. This covers profiles the card refuses, such as 10-bit H.264.
- An FFmpeg run that has written nothing for 10 minutes is killed and counts as failed, so a GPU that stops answering falls back to software instead of holding the worker forever. Writing means the output file's size or modification time changed, so the in-place `+faststart` rewrite at the end of an MP4 counts and FFmpeg's own log lines do not. A slow encode still writes every few seconds and is never stopped, and a freeze of the whole container (`docker pause`, a suspended host) restarts the clock instead of counting as a stall.
- Verification of a GPU run also compares the encode's video length with the source's, because FFmpeg exits 0 when a decoder gives up part way. A video more than 2 s or 0.5% short fails and falls back to software. When the source has no per-stream length (some Matroska files lack the `DURATION` tag), that check is skipped rather than read the whole file. Software output is not length-checked: a timestamp jump in an MPEG-TS recording inflates the probed length, and the check would throw away a correct encode.

The log says which path each file took (`Encoding succeeded (hardware decode)` or `(software decode)`) and why a fallback happened. Set `HW_DECODE: "false"` to decode and scale in software as releases before this one did.

### Software Fallback

If hardware acceleration is disabled or unavailable, the encoder falls back to `libx265` (HEVC), `libx264` (H.264), or `libsvtav1` (AV1) using CRF-based quality control. Worker count scales to the number of available CPU cores.

## Upgrading

### Upgrading from < 1.1.0

Starting with v1.1.0, encoded outputs always include the version suffix (e.g., `Movie - 720p.mkv` instead of `Movie.mkv`). Existing encodes without the suffix will be re-encoded. To avoid this, rename them before upgrading:

```bash
# Dry-run (shows what would be renamed)
docker exec quality-gate-encoder python /app/scripts/migrate_encode_names.py

# Apply renames
docker exec quality-gate-encoder python /app/scripts/migrate_encode_names.py --apply
```

### Upgrading to 1.4.0

Two behaviours change for an existing install; both are described under
[Polling interval](how-it-works.md#polling-interval).

- The source tree is scanned every 60 seconds instead of every second. Set
  `POLL_INTERVAL=1` to keep the old cadence.
- A video renamed inside the source tree, or a renamed folder, is now handled within one
  poll. Before, it waited for the next container restart. Since 1.5.2 the finished encode
  moves with it; 1.4.0 through 1.5.1 re-encoded it under the new name.
