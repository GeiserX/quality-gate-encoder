"""Tests for H.264/AAC/MP4 output and the forward-only container switch.

The property these tests exist to protect: changing ENCODING_CODEC (and with it
the output container) must never re-encode a library that is already encoded.
An output on disk is done, whatever container it was written in.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import monitor


class EncodeTestBase(unittest.TestCase):
    """Temp source/dest folders with symlinks and manifest disabled."""

    def setUp(self):
        self.source_dir = tempfile.mkdtemp(prefix='encoder_src_')
        self.dest_dir = tempfile.mkdtemp(prefix='encoder_dst_')
        self.ffmpeg_commands = []
        self._patches = [
            patch.object(monitor, 'SOURCE_FOLDER', self.source_dir),
            patch.object(monitor, 'DEST_FOLDER', self.dest_dir),
            patch.object(monitor, 'SYMLINK_TARGET_PREFIX', ''),
            patch.object(monitor, 'SYMLINK_MANIFEST_TARGET', ''),
            patch.object(monitor, 'SYMLINK_VERSION_SUFFIX', ' - 720p'),
            patch.object(monitor, 'OUTPUT_CONTAINER', 'auto'),
            patch.object(monitor, 'AUDIO_CODEC', 'auto'),
            patch.object(monitor, 'AUDIO_BITRATE', 'auto'),
            patch.object(monitor, 'AUDIO_CHANNELS', 'auto'),
            # An unknown source codec decodes in software, the command these tests pin.
            patch.object(monitor, 'get_video_stream',
                         return_value={'codec': None, 'reoriented': False, 'duration': None}),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.source_dir, ignore_errors=True)
        shutil.rmtree(self.dest_dir, ignore_errors=True)

    def _touch(self, base_dir, rel_path, content=b'data'):
        full = os.path.join(base_dir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'wb') as f:
            f.write(content)
        return full

    def _managers(self):
        from multiprocessing import Manager
        mgr = Manager()
        self.addCleanup(mgr.shutdown)
        return mgr.dict(), mgr.dict()

    def _fake_popen(self, return_code=0):
        """Popen stand-in that records the command and writes the .tmp output."""
        commands = self.ffmpeg_commands

        def _side_effect(cmd, **kwargs):
            commands.append(list(cmd))
            tmp_path = cmd[-1] if cmd else None
            if return_code == 0 and tmp_path and tmp_path.endswith('.tmp'):
                os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
                with open(tmp_path, 'wb') as f:
                    f.write(b'fake encoded data')
            proc = MagicMock()
            proc.stdout = iter([])
            proc.wait.return_value = return_code
            return proc

        return _side_effect

    def _run_encode(self, source, codec='h264', hw='intel', hw_accel=True,
                    audio_streams=None, subtitles=None, return_code=0,
                    source_codec=None, reoriented=False, source_duration=None, encoded_duration=None,
                    popen=None, verify=None):
        processed, processing = self._managers()
        # A list gives one encoded length per encode, in order.
        encoded_lengths = iter(encoded_duration if isinstance(encoded_duration, list)
                               else [encoded_duration] * 10)
        if audio_streams is None:
            audio_streams = [{'index': 1, 'codec_name': 'ac3', 'channels': 6}]
        if subtitles is None:
            subtitles = {'copy': [], 'convert': []}
        with patch.object(monitor, 'ENCODING_CODEC', codec), \
             patch.object(monitor, 'HW_ENCODING_TYPE', hw), \
             patch.object(monitor, 'ENABLE_HW_ACCEL', hw_accel), \
             patch.object(monitor, 'ENCODING_QUALITY', 'LOW'), \
             patch.object(monitor, 'is_already_low_quality', return_value=False), \
             patch.object(monitor, 'SKIP_IF_LOW_QUALITY_EXISTS', False), \
             patch.object(monitor, 'get_metadata_info', return_value={}), \
             patch.object(monitor, 'wait_for_file_completion', return_value=True), \
             patch.object(monitor, 'get_audio_streams', return_value=audio_streams), \
             patch.object(monitor, 'get_subtitle_streams', return_value=subtitles), \
             patch.object(monitor, 'get_video_stream', side_effect=lambda p: {
                 'codec': source_codec, 'reoriented': reoriented,
                 'duration': next(encoded_lengths) if p.endswith('.tmp') else source_duration}), \
             patch.object(monitor, 'verify_encoded_file', side_effect=verify or (lambda p: True)), \
             patch('subprocess.Popen', side_effect=popen or self._fake_popen(return_code)):
            monitor.encode_video(source, processed, processing)
        return processed


# ── The forward-only guarantee ──────────────────────────────────────────────

class TestForwardOnlyContainerSwitch(EncodeTestBase):
    """Flipping codec/container must not re-encode an already-encoded library."""

    def test_existing_mkv_is_not_reencoded_when_targeting_mp4(self):
        """The regression this feature must never break.

        A library encoded as '<name> - 720p.mkv' stays done after the switch to
        H.264/MP4: no ffmpeg run, no new file, the original untouched.
        """
        source = self._touch(self.source_dir, 'Movie (2021).mkv')
        legacy = self._touch(self.dest_dir, 'Movie (2021) - 720p.mkv', b'already encoded')

        with patch.object(monitor, 'verify_encoded_file', return_value=True):
            processed = self._run_encode(source, codec='h264')

        self.assertEqual(self.ffmpeg_commands, [], 'ffmpeg must not run for an encoded title')
        self.assertTrue(os.path.exists(legacy))
        self.assertEqual(open(legacy, 'rb').read(), b'already encoded')
        self.assertFalse(os.path.exists(os.path.join(self.dest_dir, 'Movie (2021) - 720p.mp4')))
        self.assertTrue(processed.get(legacy))

    def test_existing_mp4_is_not_reencoded_when_targeting_mkv(self):
        """The mirror case: switching back to HEVC/MKV respects .mp4 outputs."""
        source = self._touch(self.source_dir, 'Movie.mkv')
        existing = self._touch(self.dest_dir, 'Movie - 720p.mp4', b'already encoded')

        processed = self._run_encode(source, codec='hevc')

        self.assertEqual(self.ffmpeg_commands, [])
        self.assertTrue(os.path.exists(existing))
        self.assertFalse(os.path.exists(os.path.join(self.dest_dir, 'Movie - 720p.mkv')))
        self.assertTrue(processed.get(existing))

    def test_whole_library_flip_produces_zero_reencodes(self):
        """Every title in a mixed library is recognised as done after the flip."""
        titles = [
            'Movie A (1999).mkv',
            'Movie B - 1080p.mkv',
            'Shows/Season 1/Episode 1 - 1080p.mkv',
            'Shows/Season 1/Episode 2.mp4',
            'Deep/Nested/Path/Feature - 4K.mkv',
        ]
        sources = []
        for rel in titles:
            sources.append(self._touch(self.source_dir, rel))
            stem, _ = os.path.splitext(rel)
            output_name = monitor.get_version_output_name(os.path.basename(stem))
            legacy_rel = os.path.join(os.path.dirname(rel), f'{output_name}.mkv')
            self._touch(self.dest_dir, legacy_rel, b'already encoded')

        for source in sources:
            self._run_encode(source, codec='h264')

        self.assertEqual(self.ffmpeg_commands, [],
                         'a codec flip must not re-encode any existing output')
        produced_mp4 = [f for _r, _d, files in os.walk(self.dest_dir)
                        for f in files if f.endswith('.mp4')]
        self.assertEqual(produced_mp4, [])

    def test_encodes_when_no_output_exists_in_any_container(self):
        """Positive control: the same setup does run ffmpeg when nothing is done.

        Without this, the assertions above could pass simply because encoding
        never happens in the test harness.
        """
        source = self._touch(self.source_dir, 'Movie.mkv')

        self._run_encode(source, codec='h264')

        self.assertEqual(len(self.ffmpeg_commands), 1)
        self.assertTrue(os.path.exists(os.path.join(self.dest_dir, 'Movie - 720p.mp4')))

    def test_corrupt_legacy_output_is_replaced_in_the_new_container(self):
        """A legacy output that fails verification is re-encoded, not kept."""
        source = self._touch(self.source_dir, 'Movie.mkv')
        legacy = self._touch(self.dest_dir, 'Movie - 720p.mkv', b'corrupt')

        processed, processing = self._managers()
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'), \
             patch.object(monitor, 'HW_ENCODING_TYPE', 'intel'), \
             patch.object(monitor, 'ENABLE_HW_ACCEL', True), \
             patch.object(monitor, 'ENCODING_QUALITY', 'LOW'), \
             patch.object(monitor, 'is_already_low_quality', return_value=False), \
             patch.object(monitor, 'SKIP_IF_LOW_QUALITY_EXISTS', False), \
             patch.object(monitor, 'get_metadata_info', return_value={}), \
             patch.object(monitor, 'wait_for_file_completion', return_value=True), \
             patch.object(monitor, 'get_audio_streams',
                          return_value=[{'index': 1, 'codec_name': 'ac3', 'channels': 2}]), \
             patch.object(monitor, 'get_subtitle_streams',
                          return_value={'copy': [], 'convert': []}), \
             patch.object(monitor, 'verify_encoded_file',
                          side_effect=lambda p: not p.endswith('- 720p.mkv')), \
             patch('subprocess.Popen', side_effect=self._fake_popen(0)):
            monitor.encode_video(source, processed, processing)

        self.assertFalse(os.path.exists(legacy))
        self.assertTrue(os.path.exists(os.path.join(self.dest_dir, 'Movie - 720p.mp4')))

    def test_a_corrupt_mp4_does_not_discard_a_valid_mkv(self):
        """Only the target container being corrupt must not cost a good encode."""
        source = self._touch(self.source_dir, 'Movie.mkv')
        corrupt = self._touch(self.dest_dir, 'Movie - 720p.mp4', b'corrupt')
        valid = self._touch(self.dest_dir, 'Movie - 720p.mkv', b'already encoded')

        processed, processing = self._managers()
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'), \
             patch.object(monitor, 'is_already_low_quality', return_value=False), \
             patch.object(monitor, 'SKIP_IF_LOW_QUALITY_EXISTS', False), \
             patch.object(monitor, 'get_metadata_info', return_value={}), \
             patch.object(monitor, 'verify_encoded_file',
                          side_effect=lambda p: p.endswith('.mkv')), \
             patch('subprocess.Popen', side_effect=self._fake_popen(0)), \
             patch.object(monitor, 'wait_for_file_completion') as mock_wait:
            monitor.encode_video(source, processed, processing)
            mock_wait.assert_not_called()

        self.assertEqual(self.ffmpeg_commands, [])
        self.assertTrue(os.path.exists(valid))
        self.assertTrue(processed.get(valid))
        self.assertTrue(os.path.exists(corrupt), 'a good encode must not trigger cleanup')

    def test_all_unusable_encodes_are_removed_before_re_encoding(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        mp4 = self._touch(self.dest_dir, 'Movie - 720p.mp4', b'corrupt')
        mkv = self._touch(self.dest_dir, 'Movie - 720p.mkv', b'corrupt')

        processed, processing = self._managers()
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'), \
             patch.object(monitor, 'is_already_low_quality', return_value=False), \
             patch.object(monitor, 'SKIP_IF_LOW_QUALITY_EXISTS', False), \
             patch.object(monitor, 'get_metadata_info', return_value={}), \
             patch.object(monitor, 'wait_for_file_completion', return_value=True), \
             patch.object(monitor, 'get_audio_streams',
                          return_value=[{'index': 1, 'codec_name': 'aac', 'channels': 2}]), \
             patch.object(monitor, 'get_subtitle_streams',
                          return_value={'copy': [], 'convert': []}), \
             patch.object(monitor, 'verify_encoded_file',
                          side_effect=lambda p: p.endswith('.tmp')), \
             patch('subprocess.Popen', side_effect=self._fake_popen(0)):
            monitor.encode_video(source, processed, processing)

        self.assertFalse(os.path.exists(mkv))
        self.assertTrue(os.path.exists(mp4), 'the new encode takes the .mp4 path')
        self.assertEqual(len(self.ffmpeg_commands), 1)

    def test_growing_temp_file_in_legacy_container_blocks_a_second_encode(self):
        """A .mkv.tmp still being written is respected while targeting .mp4."""
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._touch(self.dest_dir, 'Movie - 720p.mkv.tmp', b'partial')

        processed, processing = self._managers()
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'), \
             patch.object(monitor, 'is_already_low_quality', return_value=False), \
             patch.object(monitor, 'SKIP_IF_LOW_QUALITY_EXISTS', False), \
             patch.object(monitor, 'get_metadata_info', return_value={}), \
             patch.object(monitor, 'is_file_growing', return_value=True), \
             patch.object(monitor, 'wait_for_file_completion') as mock_wait:
            monitor.encode_video(source, processed, processing)
            mock_wait.assert_not_called()


# ── Codec and container resolution ──────────────────────────────────────────

class TestCodecAndContainerResolution(unittest.TestCase):

    def test_h264_targets_mp4(self):
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'), \
             patch.object(monitor, 'OUTPUT_CONTAINER', 'auto'):
            self.assertEqual(monitor.resolve_codec(), 'h264')
            self.assertEqual(monitor.resolve_container(), 'mp4')
            self.assertEqual(monitor.get_output_extension(), '.mp4')

    def test_hevc_and_av1_target_mkv(self):
        for codec in ('hevc', 'av1'):
            with patch.object(monitor, 'ENCODING_CODEC', codec), \
                 patch.object(monitor, 'OUTPUT_CONTAINER', 'auto'):
                self.assertEqual(monitor.resolve_container(), 'mkv')
                self.assertEqual(monitor.get_output_extension(), '.mkv')

    def test_codec_aliases(self):
        for alias, expected in (('avc', 'h264'), ('x264', 'h264'),
                                ('h265', 'hevc'), ('x265', 'hevc')):
            with patch.object(monitor, 'ENCODING_CODEC', alias):
                self.assertEqual(monitor.resolve_codec(), expected)

    def test_unknown_codec_falls_back_to_hevc_in_mkv(self):
        with patch.object(monitor, 'ENCODING_CODEC', 'vp9'), \
             patch.object(monitor, 'OUTPUT_CONTAINER', 'auto'):
            self.assertEqual(monitor.resolve_codec(), 'hevc')
            self.assertEqual(monitor.get_output_extension(), '.mkv')

    def test_explicit_container_overrides_codec_default(self):
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'), \
             patch.object(monitor, 'OUTPUT_CONTAINER', 'mkv'):
            self.assertEqual(monitor.get_output_extension(), '.mkv')
        with patch.object(monitor, 'ENCODING_CODEC', 'hevc'), \
             patch.object(monitor, 'OUTPUT_CONTAINER', 'mp4'):
            self.assertEqual(monitor.get_output_extension(), '.mp4')

    def test_unknown_container_falls_back_to_auto(self):
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'), \
             patch.object(monitor, 'OUTPUT_CONTAINER', 'avi'):
            self.assertEqual(monitor.resolve_container(), 'mp4')

    def test_is_output_filename_covers_both_containers(self):
        self.assertTrue(monitor.is_output_filename('Movie - 720p.mkv'))
        self.assertTrue(monitor.is_output_filename('Movie - 720p.mp4'))
        self.assertTrue(monitor.is_output_filename('Movie - 720p.mp4.tmp'))
        self.assertTrue(monitor.is_output_filename('Movie - 720p.MKV'))
        self.assertFalse(monitor.is_output_filename('notes.txt'))
        self.assertFalse(monitor.is_output_filename('Movie.avi'))
        self.assertFalse(monitor.is_output_filename('scratch.tmp'))


class TestExistingOutputs(EncodeTestBase):

    def test_lists_the_target_container_first(self):
        self._touch(self.dest_dir, 'Movie - 720p.mkv')
        self._touch(self.dest_dir, 'Movie - 720p.mp4')
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'):
            found = monitor.existing_outputs(self.dest_dir, 'Movie - 720p')
        self.assertEqual([os.path.splitext(p)[1] for p in found], ['.mp4', '.mkv'])

    def test_finds_the_legacy_container(self):
        self._touch(self.dest_dir, 'Movie - 720p.mkv')
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'):
            found = monitor.existing_outputs(self.dest_dir, 'Movie - 720p')
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].endswith('.mkv'))

    def test_empty_when_nothing_encoded(self):
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'):
            self.assertEqual(monitor.existing_outputs(self.dest_dir, 'Movie - 720p'), [])


# ── FFmpeg command shape ────────────────────────────────────────────────────

class TestH264CommandShape(EncodeTestBase):

    def _encode_and_get_command(self, **kwargs):
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, **kwargs)
        self.assertEqual(len(self.ffmpeg_commands), 1)
        return self.ffmpeg_commands[0]

    def test_intel_uses_h264_qsv(self):
        cmd = self._encode_and_get_command(codec='h264', hw='intel')
        self.assertIn('h264_qsv', cmd)
        self.assertIn('-global_quality', cmd)

    def test_nvidia_uses_h264_nvenc(self):
        cmd = self._encode_and_get_command(codec='h264', hw='nvidia')
        self.assertIn('h264_nvenc', cmd)

    def test_software_fallback_uses_libx264(self):
        cmd = self._encode_and_get_command(codec='h264', hw_accel=False)
        self.assertIn('libx264', cmd)
        self.assertIn('-crf', cmd)

    def test_mp4_output_format_and_faststart(self):
        cmd = self._encode_and_get_command(codec='h264')
        self.assertIn('mp4', cmd[cmd.index('-f') + 1])
        self.assertIn('-movflags', cmd)
        self.assertEqual(cmd[cmd.index('-movflags') + 1], '+faststart')
        self.assertTrue(cmd[-1].endswith('Movie - 720p.mp4.tmp'))

    def test_h264_forces_8bit_pixel_format(self):
        """10-bit sources must not fail the encode on hardware H.264."""
        cmd = self._encode_and_get_command(codec='h264')
        self.assertIn('format=yuv420p', cmd[cmd.index('-vf') + 1])

    def test_hevc_command_is_unchanged(self):
        cmd = self._encode_and_get_command(codec='hevc', hw='intel')
        self.assertIn('hevc_qsv', cmd)
        self.assertEqual(cmd[cmd.index('-vf') + 1], 'scale=-1:720')
        self.assertEqual(cmd[cmd.index('-f') + 1], 'matroska')
        self.assertNotIn('-movflags', cmd)
        self.assertTrue(cmd[-1].endswith('Movie - 720p.mkv.tmp'))


# ── Decoding and scaling on the GPU ─────────────────────────────────────────

class TestHardwareDecode(EncodeTestBase):
    """With a GPU encoder, decoding and scaling run on the GPU too, and any file the
    hardware path cannot finish is encoded again with software decoding."""

    def _encode(self, **kwargs):
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, **kwargs)
        self.output = os.path.join(self.dest_dir, 'Movie - 720p.mp4')
        return self.ffmpeg_commands

    def _fail_on_hardware_popen(self):
        """Popen stand-in where every GPU-decoded run fails and every other one works."""
        commands = self.ffmpeg_commands

        def _side_effect(cmd, **kwargs):
            commands.append(list(cmd))
            proc = MagicMock()
            proc.stdout = iter([])
            if '-hwaccel' in cmd:
                with open(cmd[-1], 'wb') as f:
                    f.write(b'half written')
                proc.wait.return_value = 1
            else:
                with open(cmd[-1], 'wb') as f:
                    f.write(b'fake encoded data')
                proc.wait.return_value = 0
            return proc

        return _side_effect

    @staticmethod
    def _input_args(cmd):
        return cmd[:cmd.index('-i')]

    @staticmethod
    def _encoder_args(cmd):
        start = cmd.index('-c:v')
        return cmd[start:cmd.index('-map', start)]

    def test_intel_decodes_and_scales_on_the_igpu(self):
        commands = self._encode(codec='h264', hw='intel', source_codec='h264')
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        before_input = self._input_args(cmd)
        self.assertEqual(before_input[before_input.index('-hwaccel') + 1], 'qsv')
        self.assertEqual(before_input[before_input.index('-hwaccel_output_format') + 1], 'qsv')
        # nv12 is 8-bit 4:2:0: a 10-bit source still ends up as 8-bit H.264.
        self.assertEqual(cmd[cmd.index('-vf') + 1], 'scale_qsv=w=-1:h=720:format=nv12')
        self.assertEqual(cmd[cmd.index('-c:v') + 1], 'h264_qsv')
        self.assertEqual(cmd[cmd.index('-global_quality') + 1], '28')

    def test_intel_hevc_output_keeps_the_source_bit_depth(self):
        """The software HEVC path forces no pixel format, so the GPU path must not either."""
        commands = self._encode(codec='hevc', hw='intel', source_codec='hevc')
        cmd = commands[0]
        self.assertEqual(cmd[cmd.index('-vf') + 1], 'scale_qsv=w=-1:h=720')
        self.assertEqual(cmd[cmd.index('-c:v') + 1], 'hevc_qsv')

    def test_nvidia_decodes_and_scales_with_cuda(self):
        commands = self._encode(codec='h264', hw='nvidia', source_codec='hevc')
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        before_input = self._input_args(cmd)
        self.assertEqual(before_input[before_input.index('-hwaccel') + 1], 'cuda')
        self.assertEqual(before_input[before_input.index('-hwaccel_output_format') + 1], 'cuda')
        self.assertEqual(cmd[cmd.index('-vf') + 1], 'scale_cuda=w=-1:h=720:format=nv12')
        self.assertEqual(cmd[cmd.index('-c:v') + 1], 'h264_nvenc')

    def test_a_codec_the_igpu_cannot_decode_goes_straight_to_software(self):
        """Xvid has no decoder on an Intel iGPU, so the hardware run is not even tried."""
        commands = self._encode(codec='h264', hw='intel', source_codec='mpeg4')
        self.assertEqual(len(commands), 1)
        self.assertNotIn('-hwaccel', commands[0])
        self.assertEqual(commands[0][commands[0].index('-vf') + 1], 'scale=-1:720,format=yuv420p')
        self.assertIn('h264_qsv', commands[0])

    def test_the_same_codec_decodes_on_nvidia(self):
        """The list is per GPU: NVDEC does decode MPEG-4 Part 2."""
        commands = self._encode(codec='h264', hw='nvidia', source_codec='mpeg4')
        self.assertIn('-hwaccel', self._input_args(commands[0]))

    def test_a_rotated_or_flipped_source_decodes_in_software(self):
        """FFmpeg skips the display matrix for GPU frames, so a phone video tagged 90
        degrees would come out sideways and still pass verification."""
        commands = self._encode(codec='h264', hw='intel', source_codec='h264', reoriented=True)
        self.assertEqual(len(commands), 1)
        self.assertNotIn('-hwaccel', commands[0])
        self.assertEqual(commands[0][commands[0].index('-vf') + 1], 'scale=-1:720,format=yuv420p')

    def test_an_unknown_source_codec_decodes_in_software(self):
        commands = self._encode(codec='h264', hw='intel', source_codec=None)
        self.assertEqual(len(commands), 1)
        self.assertNotIn('-hwaccel', commands[0])

    def test_hw_decode_false_restores_software_decoding(self):
        with patch.object(monitor, 'HW_DECODE', False):
            commands = self._encode(codec='h264', hw='intel', source_codec='h264')
        self.assertEqual(len(commands), 1)
        self.assertNotIn('-hwaccel', commands[0])
        self.assertEqual(commands[0][commands[0].index('-vf') + 1], 'scale=-1:720,format=yuv420p')
        self.assertIn('h264_qsv', commands[0])

    def test_software_encoding_never_decodes_on_a_gpu(self):
        commands = self._encode(codec='h264', hw_accel=False, source_codec='h264')
        self.assertEqual(len(commands), 1)
        self.assertNotIn('-hwaccel', commands[0])
        self.assertIn('libx264', commands[0])

    def test_a_failed_hardware_run_is_encoded_again_in_software(self):
        """A GPU that refuses the source must never leave it without its 720p copy."""
        with self.assertLogs(level='WARNING') as logs:
            commands = self._encode(codec='h264', hw='intel', source_codec='h264',
                                    popen=self._fail_on_hardware_popen())
        self.assertEqual(len(commands), 2)
        self.assertIn('-hwaccel', commands[0])
        self.assertNotIn('-hwaccel', commands[1])
        self.assertEqual(commands[1][commands[1].index('-vf') + 1], 'scale=-1:720,format=yuv420p')
        self.assertEqual(self._encoder_args(commands[0]), self._encoder_args(commands[1]))
        self.assertEqual(open(self.output, 'rb').read(), b'fake encoded data')
        self.assertTrue(any('Hardware decode failed' in line for line in logs.output), logs.output)

    def test_a_hardware_encode_that_fails_verification_is_encoded_again_in_software(self):
        """Exit 0 is not enough: an output that fails verification falls back too."""
        verdicts = iter([False, True])
        commands = self._encode(codec='h264', hw='intel', source_codec='h264',
                                verify=lambda p: next(verdicts))
        self.assertEqual(len(commands), 2)
        self.assertIn('-hwaccel', commands[0])
        self.assertNotIn('-hwaccel', commands[1])
        self.assertTrue(os.path.exists(self.output))

    def test_a_short_hardware_encode_is_encoded_again_in_software(self):
        """A decoder that gives up part way still exits 0.  The short video must not stand."""
        commands = self._encode(codec='h264', hw='intel', source_codec='h264',
                                source_duration=2400.0, encoded_duration=[800.0, 2400.0])
        self.assertEqual(len(commands), 2)
        self.assertIn('-hwaccel', commands[0])
        self.assertNotIn('-hwaccel', commands[1])
        self.assertTrue(os.path.exists(self.output))

    def test_a_software_encode_is_kept_whatever_its_probed_length(self):
        """A timestamp jump in an MPEG-TS recording inflates the probed source length, so
        software output is accepted on verification alone, as it always was."""
        commands = self._encode(codec='h264', hw_accel=False, source_codec='h264',
                                source_duration=5030.0, encoded_duration=90.0)
        self.assertEqual(len(commands), 1)
        self.assertTrue(os.path.exists(self.output))

    def test_a_ts_source_that_fails_the_gpu_length_check_still_gets_its_encode(self):
        commands = self._encode(codec='h264', hw='intel', source_codec='h264',
                                source_duration=5030.0, encoded_duration=[90.0, 90.0])
        self.assertEqual(len(commands), 2)
        self.assertNotIn('-hwaccel', commands[1])
        self.assertTrue(os.path.exists(self.output))

    def test_a_success_on_the_gpu_logs_which_path_it_took(self):
        with self.assertLogs(level='INFO') as logs:
            self._encode(codec='h264', hw='intel', source_codec='h264')
        self.assertTrue(any('Encoding succeeded (hardware decode)' in line for line in logs.output), logs.output)

    def test_a_failed_hardware_run_goes_straight_to_software_with_subtitles(self):
        """No GPU retry without subtitles: software runs next and keeps its own retry."""
        commands = self.ffmpeg_commands

        def _popen(cmd, **kwargs):
            commands.append(list(cmd))
            proc = MagicMock()
            proc.stdout = iter([])
            failed = '-hwaccel' in cmd or '-c:s:0' in cmd
            with open(cmd[-1], 'wb') as f:
                f.write(b'half written' if failed else b'fake encoded data')
            proc.wait.return_value = 1 if failed else 0
            return proc

        self._encode(codec='h264', hw='intel', source_codec='h264', popen=_popen,
                     subtitles={'copy': [], 'convert': [(2, 'subrip')]})
        self.assertEqual([('-hwaccel' in c, '-sn' in c) for c in commands],
                         [(True, False), (False, False), (False, True)])
        self.assertEqual(open(self.output, 'rb').read(), b'fake encoded data')

    def test_when_both_paths_fail_nothing_is_left_behind(self):
        commands = self._encode(codec='h264', hw='intel', source_codec='h264', return_code=1)
        self.assertEqual(len(commands), 2)
        self.assertFalse(os.path.exists(self.output))
        self.assertFalse(os.path.exists(self.output + '.tmp'))


class TestEncodeIsFullLength(unittest.TestCase):

    def _check(self, source, encoded):
        with patch.object(monitor, 'get_video_stream',
                          return_value={'codec': 'h264', 'reoriented': False, 'duration': encoded}) as probe:
            return monitor.encode_is_full_length('/out.mp4.tmp', source), probe

    def test_a_short_video_fails(self):
        self.assertFalse(self._check(2400.0, 2300.0)[0])
        self.assertFalse(self._check(20.0, 17.5)[0])

    def test_small_differences_pass(self):
        """80 existing encodes differed from their source by at most 0.1 s."""
        self.assertTrue(self._check(2400.0, 2400.0)[0])
        self.assertTrue(self._check(2400.0, 2399.9)[0])
        self.assertTrue(self._check(20.0, 18.5)[0])      # under the 2 s floor
        self.assertTrue(self._check(7200.0, 7170.0)[0])  # under 0.5 % of a film
        self.assertTrue(self._check(2400.0, 2410.0)[0])  # longer is never a truncation

    def test_an_unknown_source_length_skips_the_check_without_probing(self):
        ok, probe = self._check(None, 1.0)
        self.assertTrue(ok)
        probe.assert_not_called()

    def test_an_unknown_encoded_length_skips_the_check(self):
        self.assertTrue(self._check(2400.0, None)[0])

    @unittest.skipIf(shutil.which('ffmpeg') is None or shutil.which('ffprobe') is None,
                     'needs ffmpeg and ffprobe')
    def test_real_files_with_short_video_under_long_audio(self):
        """2 s of video under 20 s of audio: verify_encoded_file passes it, this does not."""
        tmp = tempfile.mkdtemp(prefix='encoder_len_')
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for ext in ('mp4', 'mkv'):
            with self.subTest(container=ext):
                short, full = os.path.join(tmp, f'short.{ext}'), os.path.join(tmp, f'full.{ext}')
                for path, seconds in ((short, 2), (full, 20)):
                    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                                    f'testsrc2=s=160x120:d={seconds}', '-f', 'lavfi', '-i', 'sine=d=20',
                                    '-c:v', 'mpeg4', '-c:a', 'aac', path], check=True)
                self.assertTrue(monitor.verify_encoded_file(short))
                self.assertFalse(monitor.encode_is_full_length(short, 20.0))
                self.assertTrue(monitor.encode_is_full_length(full, 20.0))


class TestStallWatchdog(unittest.TestCase):
    """A hung FFmpeg is killed so the software path can run; a slow one is left alone.
    Real child processes stand in for FFmpeg, since _run_ffmpeg only reads command[-1]."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='encoder_stall_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.output = os.path.join(self.tmp, 'Movie - 720p.mp4.tmp')
        for p in (patch.object(monitor, 'FFMPEG_STALL_SECONDS', 0.5),
                  patch.object(monitor, 'STALL_CHECK_SECONDS', 0.05)):
            p.start()
            self.addCleanup(p.stop)

    def _run(self, script):
        start = time.monotonic()
        code = monitor._run_ffmpeg([sys.executable, '-c', script, self.output])
        return code, time.monotonic() - start

    def test_a_run_that_stops_writing_is_killed(self):
        with self.assertLogs(level='ERROR') as logs:
            code, elapsed = self._run('import sys, time\n'
                                      'open(sys.argv[1], "wb").write(b"header")\n'
                                      'time.sleep(60)')
        self.assertNotEqual(code, 0)
        self.assertLess(elapsed, 20)
        self.assertTrue(any('wrote nothing' in line for line in logs.output), logs.output)

    def test_a_run_that_never_creates_its_output_is_killed(self):
        code, elapsed = self._run('import time; time.sleep(60)')
        self.assertNotEqual(code, 0)
        self.assertLess(elapsed, 20)

    def test_a_slow_run_that_keeps_writing_is_left_alone(self):
        """Over twice the stall limit in total, but never a pause as long as the limit.
        The limit is 2 s here so a child interpreter that is slow to start is not a stall."""
        with patch.object(monitor, 'FFMPEG_STALL_SECONDS', 2.0):
            code, elapsed = self._run('import sys, time\n'
                                      'for _ in range(25):\n'
                                      '    with open(sys.argv[1], "ab") as f: f.write(b"x")\n'
                                      '    time.sleep(0.2)')
        self.assertEqual(code, 0)
        self.assertGreater(elapsed, 5.0)


class _FakeClock:
    """Stands in for the time module inside the watchdog, so a freeze can be scripted."""

    def __init__(self, steps):
        self.now = 1000.0
        self.steps = list(steps)

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += self.steps.pop(0) if self.steps else seconds


class _FakeProcess:
    """Runs for `checks` watchdog checks, calling `on_poll` at each one."""

    pid = -1  # no /proc entry, so only the output file counts

    def __init__(self, checks, on_poll=None):
        self.checks, self.on_poll, self.killed = checks, on_poll, False

    def poll(self):
        if self.killed or self.checks == 0:
            return 0
        self.checks -= 1
        if self.on_poll:
            self.on_poll()
        return None

    def kill(self):
        self.killed = True


class TestStallWatchdogClock(unittest.TestCase):
    """The watchdog's decisions, on a scripted clock: stall limit 10 s, a check every 1 s."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='encoder_stall_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.output = os.path.join(self.tmp, 'Movie - 720p.mp4.tmp')
        with open(self.output, 'wb') as f:
            f.write(b'moov and mdat')
        for p in (patch.object(monitor, 'FFMPEG_STALL_SECONDS', 10),
                  patch.object(monitor, 'STALL_CHECK_SECONDS', 1)):
            p.start()
            self.addCleanup(p.stop)

    def _watch(self, process, steps=()):
        with patch.object(monitor, 'time', _FakeClock(steps)):
            monitor._kill_if_stalled(process, self.output)
        return process.killed

    def test_a_silent_run_is_killed(self):
        self.assertTrue(self._watch(_FakeProcess(checks=30)))

    def test_a_rewrite_that_keeps_the_size_is_progress(self):
        """+faststart moves data inside the file: same size, new mtime at every write."""
        mtime = [1_000_000_000]

        def rewrite_in_place():
            mtime[0] += 1_000_000
            os.utime(self.output, ns=(mtime[0], mtime[0]))

        self.assertFalse(self._watch(_FakeProcess(checks=30, on_poll=rewrite_in_place)))

    def test_a_freeze_restarts_the_clock_instead_of_killing(self):
        """docker pause or SIGSTOP: one check arrives 100 s late, then 5 quiet seconds."""
        self.assertFalse(self._watch(_FakeProcess(checks=8), steps=[1, 1, 100, 1, 1, 1, 1, 1]))

    def test_a_stall_after_a_freeze_is_still_killed(self):
        self.assertTrue(self._watch(_FakeProcess(checks=30), steps=[1, 100]))

    @unittest.skipUnless(os.path.exists(f'/proc/{os.getpid()}/io'), 'needs /proc/<pid>/io (Linux)')
    def test_linux_counts_bytes_the_process_wrote(self):
        before = monitor._write_progress(os.getpid(), self.output)
        with open(os.path.join(self.tmp, 'elsewhere'), 'wb') as f:
            f.write(b'x' * 4096)
        after = monitor._write_progress(os.getpid(), self.output)
        self.assertIsNotNone(before[2])
        self.assertNotEqual(before[2], after[2])
        self.assertEqual(before[:2], after[:2])


class TestHwDecodeSetting(unittest.TestCase):
    """HW_DECODE is read once, at import, so only a fresh import proves its name and default."""

    def _hw_decode_from_environment(self, value):
        app_dir = os.path.join(os.path.dirname(__file__), '..', 'app')
        env = dict(os.environ)
        env.pop('HW_DECODE', None)
        if value is not None:
            env['HW_DECODE'] = value
        result = subprocess.run(
            [sys.executable, '-c', 'import monitor; print("HW_DECODE=" + str(monitor.HW_DECODE))'],
            cwd=app_dir, env=env, capture_output=True, text=True, timeout=120)
        return result.stdout.strip().splitlines()[-1]

    def test_on_by_default(self):
        self.assertEqual(self._hw_decode_from_environment(None), 'HW_DECODE=True')

    def test_false_turns_it_off(self):
        self.assertEqual(self._hw_decode_from_environment('false'), 'HW_DECODE=False')


def _matrix(*rows):
    """ffprobe's displaymatrix dump for three rows of three numbers."""
    return ''.join(f'\n{i:08x}: {row[0]:12d}' + ''.join(f' {v:11d}' for v in row[1:])
                   for i, row in enumerate(rows)) + '\n'


# What ffprobe prints for the display matrices FFmpeg writes with -display_rotation and
# -display_vflip.  It reports 270 degrees as -90 and 180 as -180, and a flip as 0.
IDENTITY = _matrix((65536, 0, 0), (0, 65536, 0), (0, 0, 1073741824))
ROTATE_90 = _matrix((0, -65536, 0), (65536, 0, 0), (0, 0, 1073741824))
ROTATE_270 = _matrix((0, 65536, 0), (-65536, 0, 0), (0, 0, 1073741824))
ROTATE_180 = _matrix((-65536, 0, 0), (0, -65536, 0), (0, 0, 1073741824))
VFLIP = _matrix((65536, 0, 0), (0, -65536, 0), (0, 0, 1073741824))


class TestGetVideoStream(unittest.TestCase):

    def _probe(self, stdout, returncode=0):
        with patch('subprocess.run', return_value=MagicMock(returncode=returncode, stdout=stdout)) as run:
            info = monitor.get_video_stream('/x.mkv')
        return info, run

    def _side_data(self, **side_data):
        return self._probe(json.dumps({'streams': [{'codec_name': 'h264', 'side_data_list': [side_data]}]}))[0]

    def test_reads_the_codec_and_asks_for_the_matrix(self):
        info, run = self._probe('{"streams": [{"codec_name": "h264"}]}')
        self.assertEqual(info, {'codec': 'h264', 'reoriented': False, 'duration': None})
        cmd = run.call_args[0][0]
        self.assertIn('v:0', cmd)
        self.assertIn('displaymatrix', cmd[cmd.index('-show_entries') + 1])

    def test_every_rotation_matrix_is_reoriented(self):
        for matrix, rotation in ((ROTATE_90, 90), (ROTATE_270, -90), (ROTATE_180, -180)):
            with self.subTest(rotation=rotation):
                self.assertTrue(self._side_data(displaymatrix=matrix, rotation=rotation)['reoriented'])

    def test_a_flip_is_reoriented_although_its_rotation_is_zero(self):
        self.assertTrue(self._side_data(displaymatrix=VFLIP, rotation=0)['reoriented'])

    def test_an_identity_matrix_is_upright(self):
        self.assertFalse(self._side_data(displaymatrix=IDENTITY, rotation=0)['reoriented'])

    def test_an_unreadable_matrix_counts_as_reoriented(self):
        self.assertTrue(self._side_data(displaymatrix='garbled', rotation=0)['reoriented'])

    def test_a_rotation_without_a_matrix_dump(self):
        """Negative angles, as ffprobe prints them, and whole turns."""
        for rotation, expected in ((-90, True), (-180, True), (90, True), (0, False), (360, False), (-360, False)):
            with self.subTest(rotation=rotation):
                self.assertEqual(self._side_data(rotation=rotation)['reoriented'], expected)

    def test_the_legacy_rotate_tag(self):
        for tag, expected in (('90', True), ('-90', True), ('-180', True), ('0', False), ('360', False), ('junk', False)):
            with self.subTest(tag=tag):
                info, _ = self._probe(json.dumps({'streams': [{'codec_name': 'h264', 'tags': {'rotate': tag}}]}))
                self.assertEqual(info['reoriented'], expected)

    def test_a_failed_probe_is_unknown(self):
        self.assertEqual(self._probe('', returncode=1)[0], {'codec': None, 'reoriented': False, 'duration': None})
        with patch('subprocess.run', side_effect=OSError('no ffprobe')):
            self.assertEqual(monitor.get_video_stream('/x.mkv'), {'codec': None, 'reoriented': False, 'duration': None})

    def test_parse_duration_tag(self):
        self.assertEqual(monitor._parse_duration_tag('00:43:12.345000000'), 2592.345)
        self.assertEqual(monitor._parse_duration_tag('02:00:00.000000000'), 7200.0)
        for bad in (None, '', '43:12', 'N/A', '00:xx:12.0'):
            with self.subTest(value=bad):
                self.assertIsNone(monitor._parse_duration_tag(bad))

    @unittest.skipIf(shutil.which('ffmpeg') is None or shutil.which('ffprobe') is None,
                     'needs ffmpeg and ffprobe')
    def test_real_files(self):
        """The same probe against files FFmpeg itself tagged, not hand-written replies."""
        tmp = tempfile.mkdtemp(prefix='encoder_rot_')
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        plain = os.path.join(tmp, 'plain.mp4')
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=320x240:d=1',
                        '-c:v', 'mpeg4', plain], check=True)
        self.assertEqual(monitor.get_video_stream(plain), {'codec': 'mpeg4', 'reoriented': False, 'duration': 1.0})
        for name, option in (('rotate90', ['-display_rotation:v:0', '90']),
                             ('rotate270', ['-display_rotation:v:0', '270']),
                             ('rotate180', ['-display_rotation:v:0', '180']),
                             ('vflip', ['-display_vflip:v:0'])):
            with self.subTest(name=name):
                path = os.path.join(tmp, f'{name}.mp4')
                subprocess.run(['ffmpeg', '-v', 'error'] + option + ['-i', plain, '-c', 'copy', path], check=True)
                self.assertEqual(monitor.get_video_stream(path),
                                 {'codec': 'mpeg4', 'reoriented': True, 'duration': 1.0})


# ── Audio ───────────────────────────────────────────────────────────────────

class TestAudioDefaults(EncodeTestBase):

    def test_mp4_uses_aac_and_preserves_surround(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, codec='h264',
                         audio_streams=[{'index': 1, 'codec_name': 'dts', 'channels': 6}])
        cmd = self.ffmpeg_commands[0]
        self.assertEqual(cmd[cmd.index('-c:a:0') + 1], 'aac')
        self.assertEqual(cmd[cmd.index('-ac:a:0') + 1], '6')
        self.assertEqual(cmd[cmd.index('-b:a:0') + 1], '384k')

    def test_mp4_caps_channels_at_five_point_one(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, codec='h264',
                         audio_streams=[{'index': 1, 'codec_name': 'truehd', 'channels': 8}])
        cmd = self.ffmpeg_commands[0]
        self.assertEqual(cmd[cmd.index('-ac:a:0') + 1], '6')

    def test_mp4_stereo_source_stays_stereo_at_192k(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, codec='h264',
                         audio_streams=[{'index': 1, 'codec_name': 'aac', 'channels': 2}])
        cmd = self.ffmpeg_commands[0]
        self.assertEqual(cmd[cmd.index('-ac:a:0') + 1], '2')
        self.assertEqual(cmd[cmd.index('-b:a:0') + 1], '192k')

    def test_mkv_keeps_the_ac3_stereo_downmix(self):
        """Existing MKV behaviour is unchanged by this feature."""
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, codec='hevc',
                         audio_streams=[{'index': 1, 'codec_name': 'dts', 'channels': 6}])
        cmd = self.ffmpeg_commands[0]
        self.assertEqual(cmd[cmd.index('-c:a:0') + 1], 'ac3')
        self.assertEqual(cmd[cmd.index('-ac:a:0') + 1], '2')
        self.assertEqual(cmd[cmd.index('-b:a:0') + 1], '192k')

    def test_missing_channel_count_falls_back_to_stereo(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, codec='h264',
                         audio_streams=[{'index': 1, 'codec_name': 'aac'}])
        cmd = self.ffmpeg_commands[0]
        self.assertEqual(cmd[cmd.index('-ac:a:0') + 1], '2')

    def test_explicit_audio_settings_win(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        with patch.object(monitor, 'AUDIO_CODEC', 'ac3'), \
             patch.object(monitor, 'AUDIO_CHANNELS', '2'), \
             patch.object(monitor, 'AUDIO_BITRATE', '256k'):
            self._run_encode(source, codec='h264',
                             audio_streams=[{'index': 1, 'codec_name': 'dts', 'channels': 6}])
        cmd = self.ffmpeg_commands[0]
        self.assertEqual(cmd[cmd.index('-c:a:0') + 1], 'ac3')
        self.assertEqual(cmd[cmd.index('-ac:a:0') + 1], '2')
        self.assertEqual(cmd[cmd.index('-b:a:0') + 1], '256k')

    def test_invalid_channel_override_falls_back_to_auto(self):
        with patch.object(monitor, 'AUDIO_CHANNELS', 'many'):
            self.assertEqual(
                monitor.resolve_audio_channels({'channels': 6}, 'aac'), 6)

    def test_every_audio_stream_is_mapped(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, codec='h264', audio_streams=[
            {'index': 1, 'codec_name': 'ac3', 'channels': 6},
            {'index': 2, 'codec_name': 'aac', 'channels': 2},
        ])
        cmd = self.ffmpeg_commands[0]
        self.assertEqual(cmd[cmd.index('-c:a:0') + 1], 'aac')
        self.assertEqual(cmd[cmd.index('-ac:a:0') + 1], '6')
        self.assertEqual(cmd[cmd.index('-c:a:1') + 1], 'aac')
        self.assertEqual(cmd[cmd.index('-ac:a:1') + 1], '2')


# ── Subtitles ───────────────────────────────────────────────────────────────

class TestSubtitleHandling(EncodeTestBase):

    def _probe_result(self, streams):
        result = MagicMock()
        result.returncode = 0
        result.stdout = __import__('json').dumps({'streams': streams})
        return result

    def test_mp4_converts_text_subtitles_and_drops_bitmap(self):
        streams = [
            {'index': 2, 'codec_name': 'subrip'},
            {'index': 3, 'codec_name': 'hdmv_pgs_subtitle'},
            {'index': 4, 'codec_name': 'dvb_subtitle'},
            {'index': 5, 'codec_name': 'ass'},
        ]
        with patch('subprocess.run', return_value=self._probe_result(streams)):
            result = monitor.get_subtitle_streams('/fake/movie.mkv', 'mp4')
        self.assertEqual(result['copy'], [])
        self.assertEqual([i for i, _c in result['convert']], [2, 5])

    def test_mkv_categorisation_is_unchanged(self):
        streams = [
            {'index': 2, 'codec_name': 'subrip'},
            {'index': 3, 'codec_name': 'hdmv_pgs_subtitle'},
            {'index': 4, 'codec_name': 'mov_text'},
        ]
        with patch('subprocess.run', return_value=self._probe_result(streams)):
            result = monitor.get_subtitle_streams('/fake/movie.mkv', 'mkv')
        self.assertEqual([i for i, _c in result['copy']], [2, 3])
        self.assertEqual([i for i, _c in result['convert']], [4])

    def test_container_defaults_to_the_configured_one(self):
        streams = [{'index': 2, 'codec_name': 'hdmv_pgs_subtitle'}]
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'), \
             patch.object(monitor, 'OUTPUT_CONTAINER', 'auto'), \
             patch('subprocess.run', return_value=self._probe_result(streams)):
            result = monitor.get_subtitle_streams('/fake/movie.mkv')
        self.assertEqual(result, {'copy': [], 'convert': []})

    def test_mp4_encode_uses_mov_text(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, codec='h264',
                         subtitles={'copy': [], 'convert': [(2, 'subrip')]})
        cmd = self.ffmpeg_commands[0]
        self.assertEqual(cmd[cmd.index('-c:s:0') + 1], 'mov_text')

    def test_mkv_encode_still_uses_srt(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, codec='hevc',
                         subtitles={'copy': [], 'convert': [(2, 'mov_text')]})
        cmd = self.ffmpeg_commands[0]
        self.assertEqual(cmd[cmd.index('-c:s:0') + 1], 'srt')

    def test_a_failing_subtitle_stream_never_costs_the_encode(self):
        """FFmpeg failing with subtitles mapped is retried without them."""
        source = self._touch(self.source_dir, 'Movie.mkv')
        attempts = []

        def _popen(cmd, **kwargs):
            attempts.append(list(cmd))
            proc = MagicMock()
            proc.stdout = iter([])
            # First attempt (with subtitles) fails, the retry succeeds.
            if '-sn' in cmd:
                tmp_path = cmd[-1]
                with open(tmp_path, 'wb') as f:
                    f.write(b'fake encoded data')
                proc.wait.return_value = 0
            else:
                proc.wait.return_value = 1
            return proc

        processed, processing = self._managers()
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'), \
             patch.object(monitor, 'is_already_low_quality', return_value=False), \
             patch.object(monitor, 'SKIP_IF_LOW_QUALITY_EXISTS', False), \
             patch.object(monitor, 'get_metadata_info', return_value={}), \
             patch.object(monitor, 'wait_for_file_completion', return_value=True), \
             patch.object(monitor, 'get_audio_streams',
                          return_value=[{'index': 1, 'codec_name': 'aac', 'channels': 2}]), \
             patch.object(monitor, 'get_subtitle_streams',
                          return_value={'copy': [], 'convert': [(2, 'subrip')]}), \
             patch.object(monitor, 'verify_encoded_file', return_value=True), \
             patch('subprocess.Popen', side_effect=_popen):
            monitor.encode_video(source, processed, processing)

        self.assertEqual(len(attempts), 2)
        self.assertNotIn('-sn', attempts[0])
        self.assertIn('-sn', attempts[1])
        self.assertNotIn('-c:s:0', attempts[1])
        self.assertTrue(os.path.exists(os.path.join(self.dest_dir, 'Movie - 720p.mp4')))

    def test_no_retry_when_there_were_no_subtitles(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        self._run_encode(source, codec='h264', return_code=1)
        self.assertEqual(len(self.ffmpeg_commands), 1)


# ── Cleanup, manifest and symlinks across containers ────────────────────────

class TestCleanupAcrossContainers(EncodeTestBase):

    def test_cleanup_keeps_legacy_mkv_encodes_while_targeting_mp4(self):
        self._touch(self.source_dir, 'Movie.mkv')
        legacy = self._touch(self.dest_dir, 'Movie - 720p.mkv')
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'):
            monitor.cleanup_destination()
        self.assertTrue(os.path.exists(legacy))

    def test_cleanup_removes_orphaned_mp4_encodes(self):
        self._touch(self.source_dir, 'Movie.mkv')
        self._touch(self.dest_dir, 'Movie - 720p.mp4')
        orphan = self._touch(self.dest_dir, 'Deleted Movie - 720p.mp4')
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'):
            monitor.cleanup_destination()
        self.assertFalse(os.path.exists(orphan))
        self.assertTrue(os.path.exists(os.path.join(self.dest_dir, 'Movie - 720p.mp4')))

    def test_cleanup_ignores_files_we_never_write(self):
        self._touch(self.source_dir, 'Movie.mkv')
        keep = self._touch(self.dest_dir, 'poster.jpg')
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'):
            monitor.cleanup_destination()
        self.assertTrue(os.path.exists(keep))

    def test_manifest_full_sync_includes_mp4_outputs(self):
        self._touch(self.dest_dir, 'Movie - 720p.mp4')
        self._touch(self.dest_dir, 'Old Movie - 720p.mkv')
        self._touch(self.dest_dir, 'Partial - 720p.mp4.tmp')
        with patch.object(monitor, 'SYMLINK_MANIFEST_TARGET', '/media-720'):
            monitor._manifest_full_sync()
            manifest = monitor._read_manifest()
        self.assertIn('Movie - 720p.mp4', manifest)
        self.assertIn('Old Movie - 720p.mkv', manifest)
        self.assertNotIn('Partial - 720p.mp4.tmp', manifest)

    def test_delete_encoded_video_removes_the_legacy_container(self):
        source = os.path.join(self.source_dir, 'Movie.mkv')
        legacy = self._touch(self.dest_dir, 'Movie - 720p.mkv')
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'):
            monitor.delete_encoded_video(source)
        self.assertFalse(os.path.exists(legacy))

    def test_delete_encoded_video_removes_both_containers(self):
        source = os.path.join(self.source_dir, 'Movie.mkv')
        mkv = self._touch(self.dest_dir, 'Movie - 720p.mkv')
        mp4 = self._touch(self.dest_dir, 'Movie - 720p.mp4')
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'):
            monitor.delete_encoded_video(source)
        self.assertFalse(os.path.exists(mkv))
        self.assertFalse(os.path.exists(mp4))

    def test_version_symlink_follows_the_encode_container(self):
        with patch.object(monitor, 'SYMLINK_TARGET_PREFIX', self.dest_dir):
            source = self._touch(self.source_dir, 'Movie.mkv')
            dest = self._touch(self.dest_dir, 'Movie - 720p.mp4')
            link = monitor.create_version_symlink(source, dest)
        self.assertTrue(link.endswith('Movie - 720p.mp4'))
        self.assertTrue(os.path.islink(link))

    def test_delete_version_symlink_removes_the_legacy_link(self):
        with patch.object(monitor, 'SYMLINK_TARGET_PREFIX', self.dest_dir):
            source = self._touch(self.source_dir, 'Movie.mkv')
            dest = self._touch(self.dest_dir, 'Movie - 720p.mkv')
            link = monitor.create_version_symlink(source, dest)
            self.assertTrue(os.path.islink(link))
            with patch.object(monitor, 'ENCODING_CODEC', 'h264'):
                monitor.delete_version_symlink(source)
        self.assertFalse(os.path.islink(link))

    def test_orphaned_mp4_symlink_is_cleaned_up(self):
        with patch.object(monitor, 'SYMLINK_TARGET_PREFIX', self.dest_dir):
            self._touch(self.source_dir, 'Movie.mkv')
            dest = self._touch(self.dest_dir, 'Movie - 720p.mp4')
            source = os.path.join(self.source_dir, 'Movie.mkv')
            link = monitor.create_version_symlink(source, dest)
            os.remove(dest)
            monitor.cleanup_orphaned_symlinks()
        self.assertFalse(os.path.islink(link))

    def test_is_version_symlink_recognises_both_containers(self):
        with patch.object(monitor, 'SYMLINK_TARGET_PREFIX', self.dest_dir):
            source = self._touch(self.source_dir, 'Movie.mkv')
            for ext in ('.mkv', '.mp4'):
                dest = self._touch(self.dest_dir, f'Movie - 720p{ext}')
                link = monitor.create_version_symlink(source, dest)
                self.assertTrue(monitor.is_version_symlink(link), ext)

    def test_versioned_mp4_is_not_treated_as_a_source_file(self):
        self.assertFalse(monitor.is_video_file('Movie - 720p.mp4'))
        self.assertFalse(monitor.is_video_file('Movie - 720p.mkv'))
        self.assertTrue(monitor.is_video_file('Movie.mp4'))


class TestEncoderHelperEdgeCases(EncodeTestBase):

    def test_unknown_audio_codec_falls_back_to_auto(self):
        with patch.object(monitor, 'AUDIO_CODEC', 'opus'):
            self.assertEqual(monitor.resolve_audio_codec('mp4'), 'aac')
            self.assertEqual(monitor.resolve_audio_codec('mkv'), 'ac3')

    def test_non_numeric_channel_count_falls_back_to_stereo(self):
        self.assertEqual(monitor.resolve_audio_channels({'channels': 'six'}, 'aac'), 2)
        self.assertEqual(monitor.resolve_audio_channels({}, 'aac'), 2)

    def test_ffmpeg_output_is_logged(self):
        proc = MagicMock()
        proc.stdout = iter(['frame= 1 fps=0.0', 'frame= 2 fps=24'])
        proc.wait.return_value = 0
        with patch('subprocess.Popen', return_value=proc), \
             self.assertLogs(level='INFO') as logged:
            self.assertEqual(monitor._run_ffmpeg(['ffmpeg', '-i', 'in', 'out']), 0)
        self.assertTrue(any('frame= 2' in line for line in logged.output))

    def test_retry_discards_the_partial_output_of_the_failed_attempt(self):
        source = self._touch(self.source_dir, 'Movie.mkv')
        partial_seen = []

        def _popen(cmd, **kwargs):
            tmp_path = cmd[-1]
            proc = MagicMock()
            proc.stdout = iter([])
            if '-sn' in cmd:
                # The retry must not find the failed attempt's leftovers.
                partial_seen.append(os.path.exists(tmp_path))
                with open(tmp_path, 'wb') as f:
                    f.write(b'fake encoded data')
                proc.wait.return_value = 0
            else:
                with open(tmp_path, 'wb') as f:
                    f.write(b'half written')
                proc.wait.return_value = 1
            return proc

        processed, processing = self._managers()
        with patch.object(monitor, 'ENCODING_CODEC', 'h264'), \
             patch.object(monitor, 'is_already_low_quality', return_value=False), \
             patch.object(monitor, 'SKIP_IF_LOW_QUALITY_EXISTS', False), \
             patch.object(monitor, 'get_metadata_info', return_value={}), \
             patch.object(monitor, 'wait_for_file_completion', return_value=True), \
             patch.object(monitor, 'get_audio_streams',
                          return_value=[{'index': 1, 'codec_name': 'aac', 'channels': 2}]), \
             patch.object(monitor, 'get_subtitle_streams',
                          return_value={'copy': [], 'convert': [(2, 'subrip')]}), \
             patch.object(monitor, 'verify_encoded_file', return_value=True), \
             patch('subprocess.Popen', side_effect=_popen):
            monitor.encode_video(source, processed, processing)

        self.assertEqual(partial_seen, [False], 'the failed attempt output must be removed')
        self.assertTrue(os.path.exists(os.path.join(self.dest_dir, 'Movie - 720p.mp4')))


class TestLowQualitySiblingAcrossContainers(EncodeTestBase):
    """A 720p sibling counts as done regardless of its container."""

    def test_mp4_sibling_of_an_mkv_source_skips_the_encode(self):
        self._touch(self.source_dir, 'Movie - 1080p.mkv')
        self._touch(self.source_dir, 'Movie - 720p.mp4')
        source = os.path.join(self.source_dir, 'Movie - 1080p.mkv')
        with patch.object(monitor, 'is_already_low_quality',
                          side_effect=lambda p: '720p' in p):
            self.assertTrue(monitor.has_low_quality_sibling(source))

    def test_mkv_sibling_of_an_mp4_source_skips_the_encode(self):
        self._touch(self.source_dir, 'Movie - 1080p.mp4')
        self._touch(self.source_dir, 'Movie - 720p.mkv')
        source = os.path.join(self.source_dir, 'Movie - 1080p.mp4')
        with patch.object(monitor, 'is_already_low_quality',
                          side_effect=lambda p: '720p' in p):
            self.assertTrue(monitor.has_low_quality_sibling(source))


if __name__ == '__main__':
    unittest.main()
