"""verify_encoded_file reads the duration from ffprobe's stdout and nothing else."""
import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app'))
import monitor  # noqa: E402


def _fake_ffprobe(tmp_path, monkeypatch, stdout, stderr='', code=0):
    script = tmp_path / 'ffprobe'
    script.write_text(
        '#!/bin/sh\n'
        f"printf '%s' '{stderr}' >&2\n"
        f"printf '%s' '{stdout}'\n"
        f'exit {code}\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{os.environ.get("PATH", "")}')


def test_a_warning_on_stderr_does_not_fail_a_good_encode(tmp_path, monkeypatch):
    # What FFmpeg 9's ffprobe prints for an MP4 written from a source with chapters.
    _fake_ffprobe(tmp_path, monkeypatch, '5848.681833\n',
                  '[mov,mp4,m4a,3gp,3g2,mj2 @ 0x5] Referenced QT chapter track not found\n')
    assert monitor.verify_encoded_file('/x/Movie - 720p.mp4.tmp') is True


def test_a_plain_duration_passes(tmp_path, monkeypatch):
    _fake_ffprobe(tmp_path, monkeypatch, '12.5\n')
    assert monitor.verify_encoded_file('/x/a.mkv.tmp') is True


@pytest.mark.parametrize('stdout,code', [('0.000000\n', 0), ('N/A\n', 0), ('', 1)])
def test_no_usable_duration_fails(tmp_path, monkeypatch, stdout, code):
    _fake_ffprobe(tmp_path, monkeypatch, stdout, 'something broke\n', code)
    assert monitor.verify_encoded_file('/x/a.mkv.tmp') is False
