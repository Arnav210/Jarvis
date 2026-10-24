import fcntl
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

CAMERA = Path(__file__).resolve().parents[1] / "bin/jarvis-camera"

class CameraCaptureTests(unittest.TestCase):
    def capture(self, fake_body, locked=False, stream_url="", weekday="1"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "bin"
            tools.mkdir()
            fake_date = tools / "date"
            fake_date.write_text('#!/bin/bash\nif [[ "$1" == +%u ]]; then [[ "$TZ" == America/Los_Angeles ]] || exit 98; echo ' + weekday + '; else /bin/date "$@"; fi\n')
            fake_date.chmod(0o700)
            fake = tools / "ffmpeg"
            fake.write_text("#!/bin/bash\n" + fake_body)
            fake.chmod(0o700)
            env = dict(os.environ, JARVIS_HOME=str(root), XDG_RUNTIME_DIR=str(root),
                       PATH=str(tools) + ":" + os.environ["PATH"],
                       JARVIS_CAMERA_STREAM_URL=stream_url)
            with (root / f"jarvis-camera-{os.getuid()}.lock").open("w") as lock:
                if locked:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run([str(CAMERA)], env=env, capture_output=True,
                                        text=True, timeout=10)
            pictures = list((root / "Footage").glob("*.jpg"))
            contents = [p.read_bytes() for p in pictures]
            partials = list((root / "Footage").glob("*.part"))
            return result, contents, partials

    def test_weekends_and_invalid_day_block_before_camera_access(self):
        for weekday in ("6", "7", "invalid"):
            for stream in ("", "http://127.0.0.1:8766/stream.mjpg"):
                with self.subTest(weekday=weekday, stream=stream):
                    result, pictures, partials = self.capture('exit 99\n', stream_url=stream, weekday=weekday)
                    self.assertEqual(result.returncode, 1)
                    self.assertTrue("disabled" in result.stderr or "blocked" in result.stderr)
                    self.assertFalse(pictures)
                    self.assertFalse(partials)

    def test_success_publishes_one_complete_private_picture(self):
        result, pictures, partials = self.capture('printf complete > "${@: -1}"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(pictures, [b"complete"])
        self.assertFalse(partials)
        self.assertRegex(result.stdout, r"/Footage/\d{4}-\d{2}-\d{2}_.*\.jpg\n$")

    def test_shared_feed_is_used_without_opening_webcam(self):
        result, pictures, partials = self.capture(
            '[[ "$*" == *"-f mpjpeg -i http://127.0.0.1:8766/stream.mjpg"* ]] || exit 98\n'
            '[[ "$*" != *"/dev/video"* ]] || exit 97\n'
            'printf shared > "${@: -1}"\n',
            stream_url="http://127.0.0.1:8766/stream.mjpg")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(pictures, [b"shared"])
        self.assertFalse(partials)

    def test_failure_never_publishes_a_partial_picture(self):
        result, pictures, partials = self.capture('printf incomplete > "${@: -1}"\nexit 1\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(pictures)
        self.assertFalse(partials)

    def test_overlapping_capture_is_rejected_before_camera_opens(self):
        result, pictures, partials = self.capture('exit 99\n', locked=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already running", result.stderr)
        self.assertFalse(pictures)
        self.assertFalse(partials)

if __name__ == "__main__":
    unittest.main()
