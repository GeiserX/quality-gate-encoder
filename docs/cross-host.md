# Cross-host manifest mode

When the encoder and Jellyfin run on **different hosts** (e.g., encoder on a NAS, Jellyfin on another server connected via CIFS/SMB), real symlinks cannot be created over the network mount. The manifest mode solves this:

1. **Encoder** writes a `.symlink-manifest.json` to `DEST_FOLDER` listing all encoded files and their Jellyfin container target paths.
2. **Jellyfin host** reads the manifest via a CIFS mount and creates real local symlinks.

## Encoder Configuration

Set `SYMLINK_MANIFEST_TARGET` to the path prefix as seen **inside the Jellyfin container**:

```yaml
services:
  quality-gate-encoder:
    image: drumsergio/quality-gate-encoder:1.5.12
    environment:
      SYMLINK_MANIFEST_TARGET: "/media-720/Peliculas"  # Jellyfin container path
      # ...other settings
```

The manifest is updated on encode, delete, and cleanup, and fully rebuilt at startup.

## Jellyfin Host

Install `scripts/symlink-from-manifest.sh` on the Jellyfin host and run it via cron:

```bash
# Copy script to Jellyfin host
cp scripts/symlink-from-manifest.sh /boot/config/symlink-from-manifest.sh
chmod +x /boot/config/symlink-from-manifest.sh

# Add cron (runs every 5 minutes)
echo '*/5 * * * * /boot/config/symlink-from-manifest.sh' | crontab -
```

Edit the script's configuration variables (`REMOTE_ROOT`, `MEDIA_ROOT`, `LIBRARIES`) to match your setup. The script creates symlinks in `MEDIA_ROOT` pointing to the Jellyfin container path from the manifest, and removes orphaned symlinks not present in the manifest.

## Manifest Format

```json
{
  "version": 1,
  "symlinks": {
    "Movie (2024)/Movie (2024) - 720p.mkv": "/media-720/Peliculas/Movie (2024)/Movie (2024) - 720p.mkv"
  }
}
```

## Same-Host vs Cross-Host

| Mode | Variable | Use Case |
|---|---|---|
| **Same-host** | `SYMLINK_TARGET_PREFIX` | Encoder and Jellyfin share a filesystem — encoder creates real symlinks directly |
| **Cross-host** | `SYMLINK_MANIFEST_TARGET` | Encoder and Jellyfin on different hosts — encoder writes manifest, Jellyfin host creates symlinks |

Both modes can coexist. If only `SYMLINK_MANIFEST_TARGET` is set, symlinks are managed exclusively via the manifest.
