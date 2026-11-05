from pathlib import Path
import tempfile
import unittest
from unittest import mock

import media_encode


class EncoderTests(unittest.TestCase):
    def test_cpu_mode_does_not_probe_gpus(self):
        with mock.patch.object(media_encode, "_run") as run:
            self.assertEqual(media_encode.select_encoder(Path("ffmpeg"), "cpu", lambda: False), "libx264")
            run.assert_not_called()

    def test_real_probe_failure_tries_next_vendor(self):
        with mock.patch.object(media_encode, "_run", side_effect=[(1, "no NVIDIA device"), (0, "")]) as run:
            self.assertEqual(media_encode.select_encoder(Path("ffmpeg"), "auto", lambda: False), "h264_qsv")
            self.assertEqual(run.call_count, 2)

    def test_no_gpu_falls_back_to_cpu(self):
        with mock.patch.object(media_encode, "_run", return_value=(1, "no device")):
            self.assertEqual(media_encode.select_encoder(Path("ffmpeg"), "auto", lambda: False), "libx264")

    def test_cancellation_does_not_start_cpu_fallback(self):
        with mock.patch.object(media_encode, "_run", side_effect=media_encode.EncodingCancelled), self.assertRaises(media_encode.EncodingCancelled):
            media_encode.select_encoder(Path("ffmpeg"), "auto", lambda: True)

    def test_failed_gpu_encode_retries_cpu_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.webm", Path(directory) / "temp.mp4"
            source.write_bytes(b"source")
            def run(command, *args):
                output.write_bytes(b"output")
                return (1, "GPU rejected source") if "h264_nvenc" in command else (0, "")
            with mock.patch.object(media_encode, "select_encoder", return_value="h264_nvenc"), mock.patch.object(media_encode, "_run", side_effect=run):
                encoder = media_encode.encode_mp4(Path("ffmpeg"), source, output, 1, "auto", lambda: False, lambda _: None, lambda *_: None)
            self.assertEqual(encoder, "libx264")
            self.assertEqual(source.read_bytes(), b"source")
            self.assertEqual(output.read_bytes(), b"output")

    def test_remux_does_not_probe_or_reencode(self):
        with mock.patch.object(media_encode, "select_encoder") as probe, mock.patch.object(media_encode, "_run", return_value=(0, "")) as run:
            result = media_encode.encode_mp4(Path("ffmpeg"), Path("input.mkv"), Path("out.mp4"), 1, "copy", lambda: False, lambda _: None, lambda *_: None)
            self.assertEqual(result, "copy")
            probe.assert_not_called()
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-c:v") + 1], "copy")
            self.assertEqual(command[command.index("-c:a") + 1], "copy")
