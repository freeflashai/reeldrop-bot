import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

from database import Database
from downloader import cleanup_old_temp_files, delete_request_files, detect_platform, extract_url, is_supported_url
from platforms import ReelDownloadError, VideoUnavailableError, _classify_error
from platforms.instagram import is_supported_instagram_url
from platforms.youtube import is_supported_youtube_url
from platforms.facebook import is_supported_facebook_url
from platforms.snapchat import is_supported_snapchat_url
from bot import _has_channel_access, _cache_key
from yt_dlp.utils import DownloadError


class PlatformTests(unittest.TestCase):
    def test_channel_access_statuses(self):
        for status in ("creator", "administrator", "member"):
            self.assertTrue(_has_channel_access(SimpleNamespace(status=status)))
        self.assertTrue(_has_channel_access(SimpleNamespace(status="restricted", is_member=True)))
        for status in ("left", "kicked"):
            self.assertFalse(_has_channel_access(SimpleNamespace(status=status)))
        self.assertFalse(_has_channel_access(SimpleNamespace(status="restricted", is_member=False)))

    def test_detection(self):
        cases = {
            "https://instagram.com/reel/x": "instagram",
            "https://instagram.com/stories/user.name/123456": "instagram",
            "https://instagram.com/user.name/live/": "instagram",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ": "youtube",
            "https://youtu.be/dQw4w9WgXcQ": "youtube",
            "https://youtube.com/shorts/abcdef12345": "youtube",
            "https://www.facebook.com/reel/123456789": "facebook",
            "https://fb.watch/abcdef/": "facebook",
            "https://www.snapchat.com/spotlight/abcdef": "snapchat",
            "https://story.snapchat.com/s/abcdef": "snapchat",
        }
        for url, expected in cases.items():
            self.assertEqual(detect_platform(url), expected, url)

    def test_other_platforms_are_unsupported(self):
        for url in (
            "https://tiktok.com/@user/video/123456",
            "https://twitter.com/user/status/123456",
            "https://x.com/user/status/123456",
            "https://vimeo.com/123456",
        ):
            self.assertEqual(detect_platform(url), "unsupported", url)

    def test_supported_instagram_content_paths(self):
        urls = (
            "https://instagram.com/reel/ABC_123/",
            "https://instagram.com/p/ABC_123/",
            "https://instagram.com/stories/user.name/123456/",
            "https://instagram.com/user.name/live/",
        )
        for url in urls:
            self.assertTrue(is_supported_instagram_url(url), url)
            valid, platform = is_supported_url(url)
            self.assertTrue(valid)
            self.assertEqual(platform, "instagram")

    def test_supported_youtube_content_paths(self):
        urls = (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://youtube.com/shorts/123456abcdef",
        )
        for url in urls:
            self.assertTrue(is_supported_youtube_url(url), url)
            valid, platform = is_supported_url(url)
            self.assertTrue(valid)
            self.assertEqual(platform, "youtube")

    def test_supported_facebook_content_paths(self):
        urls = (
            "https://www.facebook.com/reel/123456789",
            "https://www.facebook.com/watch/?v=123456789",
            "https://www.facebook.com/share/r/123456789/",
            "https://www.facebook.com/share/v/123456789/",
            "https://fb.watch/123456789/",
            "https://www.facebook.com/username/videos/123456789/",
        )
        for url in urls:
            self.assertTrue(is_supported_facebook_url(url), url)
            valid, platform = is_supported_url(url)
            self.assertTrue(valid)
            self.assertEqual(platform, "facebook")

    def test_supported_snapchat_content_paths(self):
        urls = (
            "https://www.snapchat.com/spotlight/123456789",
            "https://www.snapchat.com/p/abcdef123",
            "https://www.snapchat.com/t/abcdef123",
            "https://story.snapchat.com/s/123456",
            "https://www.snapchat.com/add/user.name/story/123456",
        )
        for url in urls:
            self.assertTrue(is_supported_snapchat_url(url), url)
            valid, platform = is_supported_url(url)
            self.assertTrue(valid)
            self.assertEqual(platform, "snapchat")

    def test_rejects_profile_and_non_media_paths(self):
        reject_urls = (
            "https://instagram.com/user.name/",
            "https://instagram.com/explore/",
            "https://youtube.com/@channelname",
            "https://youtube.com/feed/trending",
            "https://facebook.com/profile.php",
            "https://facebook.com/username",
            "https://snapchat.com/settings",
        )
        for url in reject_urls:
            valid, _ = is_supported_url(url)
            self.assertFalse(valid, url)

    def test_rejects_unsafe_and_lookalike_hosts(self):
        for url in ("file:///tmp/x", "http://localhost/x", "https://instagram.com.evil.test/reel/x", "not-a-url"):
            self.assertEqual(detect_platform(url), "unsupported")

    def test_extract_url(self):
        self.assertEqual(extract_url("see https://youtu.be/abc1234)."), "https://youtu.be/abc1234")

    def test_cache_key_preserves_youtube_video_id(self):
        key1 = _cache_key("https://www.youtube.com/watch?v=video1&t=10", "video:720")
        key2 = _cache_key("https://www.youtube.com/watch?v=video2&t=10", "video:720")
        self.assertNotEqual(key1, key2)

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
            db.record_download(7, "success", "youtube", 1080, "free")
            db.record_download(7, "success", "snapchat", 720, "free")
            total, breakdown = db.user_stats(7)
            self.assertEqual(total, 3)
            self.assertEqual(breakdown.get("facebook"), 1)
            self.assertEqual(breakdown.get("youtube"), 1)
            self.assertEqual(breakdown.get("snapchat"), 1)
            db.set_pro(7, 30); self.assertTrue(db.is_pro(7))
            db.remove_pro(7); self.assertFalse(db.is_pro(7))
            self.assertEqual(db.get_video_quality(7), 1080)
            db.set_video_quality(7, 480)
            self.assertEqual(db.get_video_quality(7), 480)
            with self.assertRaises(ValueError): db.set_video_quality(7, 999)
            db.replace_cached_media("key", [("file-a", "video", "Title"), ("file-b", "photo", None)])
            self.assertEqual(db.get_cached_media("key"), [
                {"telegram_file_id": "file-a", "file_type": "video", "title": "Title"},
                {"telegram_file_id": "file-b", "file_type": "photo", "title": None},
            ])
            db.replace_cached_media("key", [("file-c", "document", None)])
            self.assertEqual(len(db.get_cached_media("key")), 1)

    def test_temp_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            request = Path(folder) / "1" / "abc"; request.mkdir(parents=True)
            (request / "video.mp4").write_bytes(b"x")
            delete_request_files(request)
            self.assertFalse(request.exists())
            cleanup_old_temp_files(Path(folder), 24)


if __name__ == "__main__": unittest.main()
