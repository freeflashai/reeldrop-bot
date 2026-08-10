import tempfile
import unittest
from pathlib import Path

from database import Database
from downloader import cleanup_old_temp_files, delete_request_files, detect_platform, extract_url
from platforms import ReelDownloadError, VideoUnavailableError, _classify_error
from platforms.instagram import is_supported_instagram_url
from yt_dlp.utils import DownloadError


class PlatformTests(unittest.TestCase):
    def test_detection(self):
        cases = {"https://instagram.com/reel/x": "instagram", "https://instagram.com/stories/user.name/123456": "instagram", "https://instagram.com/user.name/live/": "instagram"}
        for url, expected in cases.items(): self.assertEqual(detect_platform(url), expected)

    def test_other_platforms_are_unsupported(self):
        for url in ("https://fb.watch/x", "https://snapchat.com/spotlight/x", "https://youtu.be/x"):
            self.assertEqual(detect_platform(url), "unsupported")

    def test_supported_instagram_content_paths(self):
        urls = (
            "https://instagram.com/reel/ABC_123/",
            "https://instagram.com/p/ABC_123/",
            "https://instagram.com/stories/user.name/123456/",
            "https://instagram.com/user.name/live/",
        )
        for url in urls:
            self.assertTrue(is_supported_instagram_url(url), url)

    def test_rejects_profile_and_image_paths(self):
        for url in ("https://instagram.com/user.name/", "https://instagram.com/explore/"):
            self.assertFalse(is_supported_instagram_url(url), url)

    def test_rejects_unsafe_and_lookalike_hosts(self):
        for url in ("file:///tmp/x", "http://localhost/x", "https://instagram.com.evil.test/reel/x", "not-a-url"):
            self.assertEqual(detect_platform(url), "unsupported")

    def test_extract_url(self):
        self.assertEqual(extract_url("see https://youtu.be/abc)."), "https://youtu.be/abc")

    def test_missing_format_is_not_reported_as_deleted(self):
        error = DownloadError("Requested format is not available")
        classified = _classify_error(error, "snapchat")
        self.assertIs(type(classified), ReelDownloadError)
        self.assertNotIsInstance(classified, VideoUnavailableError)


class DatabaseTests(unittest.TestCase):
    def test_migration_stats_and_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "test.db"); db.initialize()
            db.record_download(7, "success", "facebook", 720, "free")
            self.assertEqual(db.user_stats(7), (1, {"facebook": 1}))
            db.set_pro(7, 30); self.assertTrue(db.is_pro(7))
            db.remove_pro(7); self.assertFalse(db.is_pro(7))
            self.assertEqual(db.get_video_quality(7), 1080)
            db.set_video_quality(7, 480)
            self.assertEqual(db.get_video_quality(7), 480)
            with self.assertRaises(ValueError): db.set_video_quality(7, 999)

    def test_temp_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            request = Path(folder) / "1" / "abc"; request.mkdir(parents=True)
            (request / "video.mp4").write_bytes(b"x")
            delete_request_files(request)
            self.assertFalse(request.exists())
            cleanup_old_temp_files(Path(folder), 24)


if __name__ == "__main__": unittest.main()
