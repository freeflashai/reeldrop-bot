import tempfile
import unittest
from pathlib import Path

from database import Database
from downloader import cleanup_old_temp_files, delete_request_files, detect_platform, extract_url


class PlatformTests(unittest.TestCase):
    def test_detection(self):
        cases = {"https://instagram.com/reel/x": "instagram", "https://fb.watch/x": "facebook", "https://www.snapchat.com/spotlight/x": "snapchat", "https://youtu.be/x": "youtube"}
        for url, expected in cases.items(): self.assertEqual(detect_platform(url), expected)

    def test_rejects_unsafe_and_lookalike_hosts(self):
        for url in ("file:///tmp/x", "http://localhost/x", "https://instagram.com.evil.test/reel/x", "not-a-url"):
            self.assertEqual(detect_platform(url), "unsupported")

    def test_extract_url(self):
        self.assertEqual(extract_url("see https://youtu.be/abc)."), "https://youtu.be/abc")


class DatabaseTests(unittest.TestCase):
    def test_migration_stats_and_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "test.db"); db.initialize()
            db.record_download(7, "success", "facebook", 720, "free")
            self.assertEqual(db.user_stats(7), (1, {"facebook": 1}))
            db.set_pro(7, 30); self.assertTrue(db.is_pro(7))
            db.remove_pro(7); self.assertFalse(db.is_pro(7))

    def test_temp_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            request = Path(folder) / "1" / "abc"; request.mkdir(parents=True)
            (request / "video.mp4").write_bytes(b"x")
            delete_request_files(request)
            self.assertFalse(request.exists())
            cleanup_old_temp_files(Path(folder), 24)


if __name__ == "__main__": unittest.main()
