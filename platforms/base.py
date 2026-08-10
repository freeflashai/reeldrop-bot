"""Common platform handler contract."""

from pathlib import Path
from typing import Protocol

from . import DownloadResult


class PlatformHandler(Protocol):
    def can_handle(self, url: str) -> bool: ...
    def download(self, url: str, quality_limit: int, temp_dir: Path, user_id: int) -> DownloadResult: ...
