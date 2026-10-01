# Development

Contributions are welcome. Open an issue to discuss a change before a pull request.

## Run from source

```bash
git clone https://github.com/GeiserX/quality-gate-encoder.git && cd quality-gate-encoder
python3 -m venv venv && . venv/bin/activate && pip install -r app/requirements.txt
SOURCE_FOLDER=/path/to/source DEST_FOLDER=/path/to/destination ENABLE_HW_ACCEL=false python app/monitor.py
```

FFmpeg and ffprobe must be on `PATH`; the Docker image takes them from `lscr.io/linuxserver/ffmpeg`.

## Tests

```bash
pip install pytest pytest-cov
python -m pytest tests/ -v -rs
```

FFmpeg must be installed: some tests encode real files. CI (`.github/workflows/docker-build.yml`) runs the same
command on Python 3.12 with `--cov --cov-report=xml`. Every push to `main` then builds the image for
`linux/amd64`, pushes it with the next patch version (also under the old name until 2027-03-31), and tags
that version in git. CI pushes no `latest` tag. A push that only changes `docs/**`, `mkdocs.yml`, Markdown
files, or the `docs.yml`, `stale.yml` and `dockerhub-description.yml` workflows skips the whole run.

## Pull requests

Fork, branch from `main`, keep the change small, and open the PR against `main`. CI must be green.
